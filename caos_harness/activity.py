"""What happened on the board while you were not looking, and every registered workspace's open tasks, read-only.

Both read only what the boards already hold (`tasks` and `transitions`): no extra store, no stream. The feed is
computed on request from the rows, so it cannot disagree with the board. Other workspaces are opened read-only; nothing
is written to them and nothing is cached.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import app, workspaces

KINDS = ("intent", "delegated", "done", "blocked", "returned")
CLOSED = ("ok", "superseded", "discarded")


def _short(text: str, n: int = 90) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def feed(project: app.Project, limit: int = 60) -> dict:
    """Newest first. `kind`: intent (a task was written), delegated (sent to an agent), done (delivered or accepted),
    blocked (waiting for a person, or marked verify), returned (sent back with a note)."""
    b = project.board
    rows = {r["id"]: r for r in b.rows()}
    events: list[dict] = []

    def add(ts, kind, r, note=""):
        if ts:
            events.append({"ts": float(ts), "kind": kind, "task_id": r["id"], "text": _short(r["text"]), "agent": r["agent"] or r["queue"] or "", "note": _short(note, 140)})

    for r in rows.values():
        add(r["created"], "blocked" if r["queue"] == app.PERSON else "intent", r, "waiting for a person" if r["queue"] == app.PERSON else "")
        if r["sent_at"]:
            add(r["sent_at"], "delegated", r, f"sent to {r['agent'] or r['queue']}")
        if r["reviewed_at"]:
            verdict = r["review"] or ""
            kind = {"ok": "done", "superseded": "done", "redo": "returned", "verify": "blocked"}.get(verdict, "done")
            add(r["reviewed_at"], kind, r, f"{verdict}" + (f": {r['review_note']}" if r["review_note"] else ""))
    for t, tid, frm, too, agent in b.conn.execute("SELECT t, task_id, frm, too, agent FROM transitions ORDER BY t DESC LIMIT 400").fetchall():
        r = rows.get(tid)
        if r is None:
            continue
        if frm == "sent" and too == "pending" and r["review"] == "redo":
            continue   # already told by the review itself
        if too == "sent" and r["result"] is not None:
            add(t, "done", r, f"delivered by {agent or r['agent'] or r['queue']}, waiting for review")
    events.sort(key=lambda e: -e["ts"])
    seen, out = set(), []
    for e in events:   # the same moment told twice (a review and its transition) is told once
        k = (e["task_id"], e["kind"], round(e["ts"]))
        if k not in seen:
            seen.add(k)
            out.append(e)
    states = [app.task_state(r) for r in rows.values()]
    return {
        "events": out[:limit],
        "summary": {"needs_you": sum(s in ("to_review", "verify", "person") for s in states), "running": states.count("sending"),
                    "pending": sum(s in ("pending", "returned") for s in states), "to_review": sum(s in ("to_review", "verify") for s in states),
                    "with_person": states.count("person"), "closed": sum(s in CLOSED for s in states)},
    }


def _open_readonly(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1)
    conn.row_factory = sqlite3.Row
    return conn


def consolidated(current: app.Project, per_workspace: int = 40) -> dict:
    """Open tasks of every workspace on the list, current one first. A folder that is gone, has no board yet, or whose
    board cannot be read is listed with `error` rather than skipped, so a missing workspace is visible."""
    paths = [str(current.root)] + [p for p in workspaces.registered() if p != str(current.root)]
    out = []
    for raw in paths:
        root = Path(raw)
        info = {"name": root.name or raw, "path": raw, "current": raw == str(current.root), "tasks": [], "counts": {"needs_you": 0, "open": 0}, "error": ""}
        try:
            proj = app.load(root / app.CONFIG)
            if not proj.db.exists():
                info["error"] = "no board yet"
                out.append(info)
                continue
            with _open_readonly(proj.db) as conn:
                rows = conn.execute("SELECT * FROM tasks ORDER BY id DESC").fetchall()
            for r in rows:
                state = app.task_state(r)
                if state in CLOSED:
                    continue
                info["counts"]["open"] += 1
                needs = state in ("to_review", "verify", "person")
                info["counts"]["needs_you"] += needs
                if len(info["tasks"]) < per_workspace:
                    info["tasks"].append({"id": r["id"], "state": state, "queue": r["queue"], "text": _short(r["text"], 120), "created": r["created"], "needs_you": needs})
            info["tasks"].sort(key=lambda t: (not t["needs_you"], -t["id"]))
        except (app.ConfigError, sqlite3.Error, OSError) as e:
            info["error"] = str(e)[:120]
        out.append(info)
    return {"workspaces": out, "readonly": True}


def recent_sessions(current: app.Project, limit: int = 40) -> dict:
    """The newest sessions of every workspace on the list, read from each one's `sessions.json` and never written.
    Only the list's own fields travel (title, mode, target, counts): no message text leaves its workspace's folder."""
    paths = [str(current.root)] + [p for p in workspaces.registered() if p != str(current.root)]
    items = []
    for raw in paths:
        try:
            data = json.loads((Path(raw) / ".harness" / "sessions.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for sess in data if isinstance(data, list) else []:
            if isinstance(sess, dict) and isinstance(sess.get("id"), str):
                items.append({"id": sess["id"], "title": str(sess.get("title") or "Sin título")[:120], "mode": sess.get("mode", "plan"), "target": sess.get("target"),
                              "messages_count": int(sess.get("messages_count") or 0), "updated_at": float(sess.get("updated_at") or 0),
                              "workspace": Path(raw).name or raw, "workspace_path": raw, "current": raw == str(current.root)})
    items.sort(key=lambda x: -x["updated_at"])
    return {"sessions": items[:limit], "readonly": True}
