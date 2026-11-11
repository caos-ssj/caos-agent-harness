"""End-to-end demo with synthetic data and no model: tickets go through the board to two simulated agents,
each result passes the validation pipeline, and whatever the system is not sure about lands in the review queue.

    python -m caos_harness.board.demo [--seed 7]

Deterministic: same seed, same table. The agents are the keyword classifier of `validation.sut`; `agent-b`
has injected timeouts, rate limits and schema drift. Swap `Worker.call` for a real model to use it for real.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

from ..validation.pipeline import process
from ..validation.queue import ReviewQueue
from ..validation.sut import FlakyClient
from ..router.route import choose, load_profiles, load_tiers
from ..traces.store import Trace, record_outcome
from .core import Board

ROOT = Path(__file__).resolve().parent.parent.parent
PKG = ROOT / "caos_harness"


class Worker:
    """In-process agent: receives a task, runs the validated pipeline and keeps the outcome until it delivers."""
    def __init__(self, name: str, client: FlakyClient):
        self.name, self.client, self.busy, self.outbox = name, client, False, []

    def run(self, record: dict):
        return process(record, self.client.call)


class LocalDispatcher:
    def __init__(self, workers: dict[str, Worker], records: dict[str, dict], fail_first_send_of: str | None = None):
        self.workers, self.records, self.fail = workers, records, fail_first_send_of

    def is_idle(self, agent: str) -> bool:
        return not self.workers[agent].busy

    def send(self, agent: str, text: str) -> None:
        if self.fail == agent:  # one injected dispatch error: the task must return to the queue, not vanish
            self.fail = None
            raise ConnectionError("agent terminal not reachable")
        rid = text.split("#", 1)[1].split(":", 1)[0]
        w = self.workers[agent]
        w.outbox.append((rid, w.run(self.records[rid])))


def run(seed: int = 7, trace: Trace | None = None) -> dict:
    golden = [json.loads(l) for l in (PKG / "data" / "golden.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    records = {r["id"]: r for r in golden}
    workers = {"agent-a": Worker("agent-a", FlakyClient(seed=seed)),
               "agent-b": Worker("agent-b", FlakyClient(seed=seed, p_timeout=0.25, p_rate_limit=0.15, p_drift=0.1))}
    board, humans = Board(trace=trace), ReviewQueue()
    disp = LocalDispatcher(workers, records, fail_first_send_of="agent-b")
    # The router decides first: every fifth ticket is one where a wrong answer is expensive ("critical"); the rest are "medium".
    # A tier no measured system reaches never gets an agent: the task waits in the queue of a person.
    profiles, tiers = load_profiles(), load_tiers()
    ids, to_person = {}, 0
    for i, r in enumerate(golden):
        tier = "critical" if int(r["id"]) % 5 == 0 else "medium"
        d = choose(profiles, tiers[tier])
        queue = ("agent-a", "agent-b")[i % 2] if d.action == "route" else "person"
        to_person += queue == "person"
        tid = board.add(f"Classify ticket #{r['id']}: {r.get('text') or '(empty)'}", queue=queue)
        ids[tid] = r["id"]
        if trace:
            trace.event(f"task:{tid}", "router", "decision", d.system or "", d.action, d.reason, tier=tier)
    workers["agent-a"].busy = True  # agent-a starts busy: its first task must wait, not be sent anyway
    log = {"agent_busy": 0, "dispatch_failed": 0}
    for _round in range(3):
        for t in board.pending():
            if t["queue"] == "person":
                continue
            res = board.assign(t["id"], t["queue"], disp)
            if not res.ok:
                log[res.reason.split(":")[0]] = log.get(res.reason.split(":")[0], 0) + 1
        workers["agent-a"].busy = False
        for w in workers.values():  # agents deliver; nothing is closed yet
            for rid, outcome in w.outbox:
                tid = next(k for k, v in ids.items() if v == rid)
                board.deliver(tid, json.dumps(asdict(outcome), ensure_ascii=False))
                if trace:
                    record_outcome(trace, f"task:{tid}", outcome)
            w.outbox.clear()
    wrong = 0
    for t in board.to_review():  # the reviewer: closes what checks out, keeps the rest open with a reason
        out, rec = json.loads(t["result"]), records[ids[t["id"]]]
        if out["status"] == "rejected":
            board.review(t["id"], "superseded", out["reason"])
        elif out["status"] == "escalated":
            board.review(t["id"], "verify", out["reason"])
            humans.add(type("O", (), {"id": rec["id"], "reason": out["reason"], "label": out["label"]})(), rec.get("text") or "")
        elif out["label"] == rec.get("label"):
            board.review(t["id"], "ok", "matches reference")
        else:
            wrong += 1
            board.review(t["id"], "verify", f"answered {out['label']}, reference says {rec.get('label')}")
    stats = board.stats()
    lost = len(golden) - stats["tasks"]
    waiting_person = len(board.pending("person"))
    open_unreviewed = stats["review"].get("unreviewed", 0) + stats["by_status"].get("pending", 0) - waiting_person + stats["by_status"].get("sending", 0)
    return {"seed": seed, "tasks": stats["tasks"], "routed_to_a_person": waiting_person, "closed_ok": stats["review"].get("ok", 0), "closed_bad_input": stats["review"].get("superseded", 0),
            "open_for_human_review": stats["review"].get("verify", 0), "of_which_wrong_answers_caught": wrong,
            "human_queue": len(humans.pending()), "held_while_agent_busy": log["agent_busy"], "dispatch_errors_requeued": log["dispatch_failed"],
            "lost": lost, "left_without_review": open_unreviewed, "by_agent": stats["by_agent"]}


def main() -> int:
    seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 7
    trace = Trace(sys.argv[sys.argv.index("--trace") + 1]) if "--trace" in sys.argv else None
    res = run(seed, trace)
    print(json.dumps(res, indent=2))
    if trace:
        print("trace:", json.dumps(trace.counts(), indent=2))
    ok = res["lost"] == 0 and res["left_without_review"] == 0 and res["routed_to_a_person"] + res["closed_ok"] + res["closed_bad_input"] + res["open_for_human_review"] == res["tasks"]
    print("PASS every task ends reviewed or with a person: closed, or open with a reason" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
