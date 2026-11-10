"""One trace format for everything the harness does: board transitions, agent steps, validation outcomes and reviews.

Every event carries a `run_id`, so one query returns the whole life of a task, from the queue to the review verdict.
Events hold identifiers, statuses and reasons. Task text is not stored, so a trace can be shared.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, run_id TEXT NOT NULL, source TEXT NOT NULL,
  kind TEXT NOT NULL, name TEXT, status TEXT, reason TEXT, seconds REAL, data TEXT);
CREATE INDEX IF NOT EXISTS events_run ON events(run_id, seq);"""
SOURCES = ("board", "agent", "validation", "review", "router")


class Trace:
    def __init__(self, path: str | Path = ":memory:", clock=time.time):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.lock, self.clock = threading.Lock(), clock

    def event(self, run_id: str, source: str, kind: str, name: str = "", status: str = "", reason: str = "", seconds: float | None = None, **data) -> None:
        if source not in SOURCES:
            raise ValueError(f"unknown source: {source}")
        with self.lock:
            self.db.execute("INSERT INTO events(ts,run_id,source,kind,name,status,reason,seconds,data) VALUES (?,?,?,?,?,?,?,?,?)",
                            (self.clock(), str(run_id), source, kind, name, status, reason, seconds, json.dumps(data, ensure_ascii=False) if data else None))
            self.db.commit()

    def timeline(self, run_id: str) -> list[dict]:
        cols = ("seq", "ts", "run_id", "source", "kind", "name", "status", "reason", "seconds", "data")
        with self.lock:
            rows = self.db.execute(f"SELECT {','.join(cols)} FROM events WHERE run_id=? ORDER BY seq", (str(run_id),)).fetchall()
        return [dict(zip(cols, r), data=json.loads(r[-1]) if r[-1] else {}) for r in rows]

    def counts(self) -> dict[str, int]:
        with self.lock:
            return {f"{s}.{k}.{st}": n for s, k, st, n in self.db.execute("SELECT source, kind, COALESCE(status,''), COUNT(*) FROM events GROUP BY 1,2,3 ORDER BY 1,2,3")}


def record_agent(trace: Trace, run_id: str, engine: str, model: str, res) -> None:
    """Writes one agent run (`engines.native.Result`): each tool call, each policy block and the final verdict."""
    for c in res.tool_calls:
        trace.event(run_id, "agent", "tool_call", c["name"], "ok" if c["ok"] else "failed")
    for b in res.blocked:
        trace.event(run_id, "agent", "policy_block", b.split(":", 1)[0], "blocked", b)
    trace.event(run_id, "agent", "final", engine, res.status, res.reason, res.seconds, model=model, steps=res.steps, cited=res.cited)


def record_outcome(trace: Trace, run_id: str, outcome) -> None:
    """Writes one validation outcome (`validation.pipeline.Outcome`)."""
    trace.event(run_id, "validation", "outcome", outcome.label or "", outcome.status, outcome.reason, attempts=outcome.attempts, waits=outcome.waits)
