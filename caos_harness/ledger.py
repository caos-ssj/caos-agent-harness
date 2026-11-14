"""The cost ledger: what every call to an agent measurably cost, and nothing that was not measured.

One event per call (`source="agent"`, `kind="call"`): seconds on the clock, characters sent and received, the agent's cost tier,
and whether it failed. Tokens are recorded only when the tool that was called reports them; a subscription CLI that prints only
its answer leaves them empty, and they stay empty. No price is stored or computed: a subscription has no price per call, so the
figure that matters is how much accepted work each paid call bought.
"""
from __future__ import annotations

import json
import time

RUN = "ledger"


def record(project, agent: str, seconds: float, chars_in: int, chars_out: int, ok: bool, tokens_in: int | None = None, tokens_out: int | None = None) -> None:
    """Never raises: the ledger must not be the reason a dispatch fails."""
    try:
        from . import scout
        a = project.agents.get(agent)
        trace = project.board.trace
        if a is None or trace is None:
            return
        trace.event(RUN, "agent", "call", agent, "ok" if ok else "failed", "", round(seconds, 2), tier=scout.cost_tier(a),
                    chars_in=int(chars_in), chars_out=int(chars_out), tokens_in=tokens_in, tokens_out=tokens_out)
    except Exception:
        pass


class timed:
    """`with ledger.timed(project, agent, text) as t: ...; t.out = answer` records one call, failed if the block raised."""
    def __init__(self, project, agent: str, text: str):
        self.project, self.agent, self.chars_in, self.out, self.tokens = project, agent, len(text or ""), "", (None, None)

    def __enter__(self):
        self.t0 = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb):
        record(self.project, self.agent, time.monotonic() - self.t0, self.chars_in, len(self.out or ""), exc_type is None, *self.tokens)
        return False


def summary(project) -> dict:
    """Per agent: calls, failures, seconds, characters, tokens where reported. And the two counts behind the headline: paid calls,
    and tasks accepted without ever being returned."""
    trace, rows = project.board.trace, {}
    if trace:
        with trace.lock:
            events = trace.db.execute("SELECT name, status, seconds, data FROM events WHERE source='agent' AND kind='call' ORDER BY seq").fetchall()
        for name, status, seconds, data in events:
            try:
                d = json.loads(data or "{}")
            except ValueError:
                d = {}
            r = rows.setdefault(name, {"agent": name, "tier": d.get("tier") or "", "calls": 0, "failed": 0, "seconds": 0.0, "chars_in": 0, "chars_out": 0,
                                       "tokens_in": None, "tokens_out": None, "calls_with_tokens": 0})
            r["tier"] = d.get("tier") or r["tier"]
            r["calls"] += 1
            r["failed"] += status != "ok"
            r["seconds"] = round(r["seconds"] + (seconds or 0), 2)
            r["chars_in"] += int(d.get("chars_in") or 0)
            r["chars_out"] += int(d.get("chars_out") or 0)
            if d.get("tokens_in") is not None or d.get("tokens_out") is not None:
                r["calls_with_tokens"] += 1
                r["tokens_in"] = (r["tokens_in"] or 0) + int(d.get("tokens_in") or 0)
                r["tokens_out"] = (r["tokens_out"] or 0) + int(d.get("tokens_out") or 0)
    b = project.board
    with b.lock:
        accepted = b.conn.execute("SELECT COUNT(*) FROM tasks WHERE review='ok'").fetchone()[0]
        first = b.conn.execute("SELECT COUNT(*) FROM tasks WHERE review='ok' AND id NOT IN (SELECT task_id FROM transitions WHERE frm='sent' AND too='pending')").fetchone()[0]
    scout_briefs = scout_cached = paid_avoided_calls = 0
    if trace:
        with trace.lock:
            sevs = trace.db.execute("SELECT status, data FROM events WHERE source='scout' AND kind='brief' ORDER BY seq").fetchall()
        for status, data in sevs:
            scout_briefs += 1
            if status == "cached":
                scout_cached += 1
            try:
                if json.loads(data or "{}").get("executor_tier") == "paid":
                    paid_avoided_calls += 1
            except ValueError:
                pass
    agents = sorted(rows.values(), key=lambda r: (-r["calls"], r["agent"]))
    return {"agents": agents, "calls": sum(r["calls"] for r in agents), "paid_calls": sum(r["calls"] for r in agents if r["tier"] == "paid"),
            "seconds": round(sum(r["seconds"] for r in agents), 1), "accepted": accepted, "accepted_first_attempt": first,
            "scout_briefs": scout_briefs, "scout_cached": scout_cached, "paid_avoided_calls": paid_avoided_calls}


def _calls(project) -> list[tuple]:
    trace = project.board.trace
    if not trace:
        return []
    with trace.lock:
        return trace.db.execute("SELECT ts, name, status, seconds, data FROM events WHERE source='agent' AND kind='call' ORDER BY seq").fetchall()


def activity(project, minutes: int = 120, bucket: int = 300, clock=time.time) -> list[dict]:
    """Calls per `bucket` seconds over the last `minutes`, oldest first: [{"t", "calls", "failed", "seconds"}]. Empty buckets are
    included, so the series is the time axis itself."""
    now = clock()
    n = max(1, int(minutes * 60 // bucket))
    start = (int(now) // bucket - n + 1) * bucket
    out = [{"t": start + i * bucket, "calls": 0, "failed": 0, "seconds": 0.0} for i in range(n)]
    for ts, _name, status, seconds, _data in _calls(project):
        i = int((ts - start) // bucket)
        if 0 <= i < n:
            out[i]["calls"] += 1
            out[i]["failed"] += status != "ok"
            out[i]["seconds"] = round(out[i]["seconds"] + (seconds or 0), 1)
    return out


def last_calls(project) -> dict[str, dict]:
    """Per agent, its most recent call: {"ts", "status", "seconds"}."""
    out: dict[str, dict] = {}
    for ts, name, status, seconds, _data in _calls(project):
        out[name] = {"ts": ts, "status": status, "seconds": round(seconds or 0, 1)}
    return out


def since(project, ts: float) -> dict:
    """Calls made after `ts`: how many, and how many of them were paid."""
    calls = paid = 0
    for t, _name, _status, _seconds, data in _calls(project):
        if t > ts:
            calls += 1
            try:
                paid += json.loads(data or "{}").get("tier") == "paid"
            except ValueError:
                pass
    return {"calls": calls, "paid_calls": paid}
