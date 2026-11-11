"""Task board: one queue per agent, dispatch only to idle agents, and a review step before a task counts as done.

Lifecycle of a task:

    pending ──claim──▶ sending ──dispatch ok──▶ sent ──review──▶ ok | superseded
       ▲                  │                       │
       │                  └─ dispatch error ──────┤ (back to pending)
       └───────────── review = redo ──────────────┘ (back to its agent's queue, with the reviewer's note first)

Rules the board enforces:
  * A task is claimed with a conditional UPDATE *before* anything is sent, so two simultaneous
    assignments cannot both win.
  * A task is only dispatched to an agent that reports itself idle.
  * A dispatch that fails returns the task to the queue; a dispatch that times out stays in
    `sending`, visible, because the agent may already have received it.
  * Nothing is closed by the agent that did it: closing needs a review verdict.
"""
from __future__ import annotations

import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, created REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending', queue TEXT, skill TEXT, agent TEXT, sent_at REAL,
  result TEXT, review TEXT, review_note TEXT, reviewed_at REAL);
CREATE TABLE IF NOT EXISTS transitions (t REAL, task_id INTEGER, frm TEXT, too TEXT, agent TEXT);
"""
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")  # a newline would send half a message to a terminal; Ctrl-C would cut it
VERDICTS = ("verify", "ok", "superseded", "redo")


class DispatchTimeout(Exception):
    """The agent did not confirm in time: it may or may not have received the task."""


class Dispatcher(Protocol):
    def is_idle(self, agent: str) -> bool: ...
    def send(self, agent: str, text: str) -> None: ...


@dataclass
class Assigned:
    ok: bool
    reason: str = ""


class Board:
    def __init__(self, path: str | Path = ":memory:", clock=time.time, trace=None):
        self.trace = trace  # optional traces.Trace: every transition and verdict is also written there as run "task:<id>"
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.lock = threading.Lock()
        self.clock = clock

    # ─ writes ─
    def _move(self, task_id: int, frm: str, too: str, agent: str | None = None) -> None:
        self.conn.execute("INSERT INTO transitions VALUES (?,?,?,?,?)", (self.clock(), task_id, frm, too, agent))
        if self.trace:
            self.trace.event(f"task:{task_id}", "board", "transition", agent or "", too, f"from:{frm}" if frm else "")

    def add(self, text: str, queue: str | None = None, skill: str | None = None) -> int:
        """`skill` names the role skill the agent must load first (see `caos_harness.skills`)."""
        text = " ".join(CONTROL_RE.sub(" ", text).split())
        if not text:
            raise ValueError("empty task")
        with self.lock:
            cur = self.conn.execute("INSERT INTO tasks (text, created, queue, skill) VALUES (?,?,?,?)", (text, self.clock(), queue, skill))
            self._move(cur.lastrowid, "", "pending")
            self.conn.commit()
        return cur.lastrowid

    def assign(self, task_id: int, agent: str, dispatcher: Dispatcher) -> Assigned:
        row = self.get(task_id)
        if not row or row["status"] != "pending":
            return Assigned(False, "not_pending")
        if not dispatcher.is_idle(agent):
            return Assigned(False, "agent_busy")
        text = row["text"]
        if row["review"] == "redo" and row["review_note"]:  # what to fix goes first
            text = f"Returned by the reviewer, fix this and keep what was already right: {row['review_note']} — Original task: {text}"
        if row["skill"]:  # the pointer to the skill goes first, so the agent starts from the same rules every time
            text = f"Load the skill '{row['skill']}' before starting. Task: {text}"
        with self.lock:  # claim before sending: atomic, only one caller wins
            claimed = self.conn.execute("UPDATE tasks SET status='sending', agent=?, sent_at=? WHERE id=? AND status='pending'",
                                        (agent, self.clock(), task_id)).rowcount
            if claimed:
                self._move(task_id, "pending", "sending", agent)
            self.conn.commit()
        if not claimed:
            return Assigned(False, "not_pending")
        try:
            dispatcher.send(agent, text)
        except DispatchTimeout:
            return Assigned(False, "dispatch_unconfirmed")  # stays in `sending`: resending could duplicate the work
        except Exception as e:
            with self.lock:
                self.conn.execute("UPDATE tasks SET status='pending', agent=NULL WHERE id=? AND status='sending'", (task_id,))
                self._move(task_id, "sending", "pending", agent)
                self.conn.commit()
            return Assigned(False, f"dispatch_failed:{type(e).__name__}")
        with self.lock:
            self.conn.execute("UPDATE tasks SET status='sent', review=NULL, result=NULL WHERE id=? AND status='sending'", (task_id,))
            self._move(task_id, "sending", "sent", agent)
            self.conn.commit()
        return Assigned(True)

    def deliver(self, task_id: int, result: str) -> bool:
        """The agent hands in its result. The task stays open until it is reviewed."""
        with self.lock:
            n = self.conn.execute("UPDATE tasks SET result=? WHERE id=? AND status='sent'", (result, task_id)).rowcount
            self.conn.commit()
        return n == 1

    def review(self, task_id: int, verdict: str, note: str = "") -> bool:
        """`ok` and `superseded` close the task; `verify` keeps it open for a check with evidence; `redo` returns it to its agent."""
        if verdict not in VERDICTS:
            raise ValueError(f"unknown verdict: {verdict}")
        now = self.clock()
        with self.lock:
            if verdict == "redo":
                n = self.conn.execute("UPDATE tasks SET status='pending', queue=COALESCE(agent, queue), review='redo', review_note=?, "
                                      "reviewed_at=? WHERE id=? AND status='sent'", (note, now, task_id)).rowcount
                if n:
                    self._move(task_id, "sent", "pending")
            elif verdict == "verify":
                n = self.conn.execute("UPDATE tasks SET review='verify', review_note=?, reviewed_at=? WHERE id=? AND status='sent' "
                                      "AND (review IS NULL OR review='verify')", (note, now, task_id)).rowcount
            else:
                n = self.conn.execute("UPDATE tasks SET review=?, review_note=?, reviewed_at=? WHERE id=? AND status='sent'",
                                      (verdict, note, now, task_id)).rowcount
            self.conn.commit()
        if n and self.trace:
            self.trace.event(f"task:{task_id}", "review", "verdict", "", verdict, note)
        return n == 1

    def requeue(self, task_id: int, queue: str) -> bool:
        """Moves a task that has not been sent to another queue. A task being sent, delivered or closed stays where it is:
        the claim made when it was sent is never undone from here."""
        with self.lock:
            row = self.conn.execute("SELECT queue FROM tasks WHERE id=? AND status='pending'", (task_id,)).fetchone()
            if not row or row["queue"] == queue:
                return False
            n = self.conn.execute("UPDATE tasks SET queue=? WHERE id=? AND status='pending'", (queue, task_id)).rowcount
            if n and self.trace:
                self.trace.event(f"task:{task_id}", "board", "requeue", queue, "pending", f"from:{row['queue']}")
            self.conn.commit()
        return n == 1

    def discard(self, task_id: int) -> bool:
        with self.lock:
            n = self.conn.execute("UPDATE tasks SET status='discarded' WHERE id=? AND status='pending'", (task_id,)).rowcount
            if n:
                self._move(task_id, "pending", "discarded")
            self.conn.commit()
        return n == 1

    # ─ reads ─
    def get(self, task_id: int):
        with self.lock:
            return self.conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()

    def pending(self, queue: str | None = None) -> list:
        q = "SELECT * FROM tasks WHERE status='pending'" + (" AND queue=?" if queue else "") + " ORDER BY id"
        with self.lock:
            return self.conn.execute(q, (queue,) if queue else ()).fetchall()

    def to_review(self) -> list:
        """Delivered and not closed: the reviewer's queue."""
        with self.lock:
            return self.conn.execute("SELECT * FROM tasks WHERE status='sent' AND result IS NOT NULL AND (review IS NULL OR review='verify') ORDER BY id").fetchall()

    def stats(self) -> dict:
        """Aggregates only: safe to publish, no task text."""
        with self.lock:
            by_status = dict(self.conn.execute("SELECT status, COUNT(*) FROM tasks GROUP BY 1").fetchall())
            by_review = dict(self.conn.execute("SELECT COALESCE(review,'unreviewed'), COUNT(*) FROM tasks WHERE status='sent' GROUP BY 1").fetchall())
            redone = self.conn.execute("SELECT COUNT(DISTINCT task_id) FROM transitions WHERE frm='sent' AND too='pending'").fetchone()[0]
            by_agent = dict(self.conn.execute("SELECT agent, COUNT(*) FROM tasks WHERE agent IS NOT NULL GROUP BY 1").fetchall())
        return {"tasks": sum(by_status.values()), "by_status": by_status, "review": by_review, "returned_at_least_once": redone, "by_agent": by_agent}
