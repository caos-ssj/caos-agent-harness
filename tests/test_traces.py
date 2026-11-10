import asyncio
import json

import pytest
from caos_harness.board import Board
from caos_harness.board.demo import run
from caos_harness.engines.native import Result
from caos_harness.traces.store import Trace, record_agent


class Disp:
    def is_idle(self, a):
        return True

    def send(self, a, t):
        pass


def test_one_run_id_gives_the_whole_life_of_a_task_in_order():
    tr = Trace()
    b = Board(trace=tr)
    t = b.add("private client text")
    b.assign(t, "a", Disp())
    b.deliver(t, "r")
    b.review(t, "redo", "missing dates")
    b.assign(t, "a", Disp())
    b.deliver(t, "r2")
    b.review(t, "ok")
    line = [(e["source"], e["kind"], e["status"]) for e in tr.timeline(f"task:{t}")]
    assert line == [("board", "transition", "pending"), ("board", "transition", "sending"), ("board", "transition", "sent"),
                    ("board", "transition", "pending"), ("review", "verdict", "redo"),
                    ("board", "transition", "sending"), ("board", "transition", "sent"), ("review", "verdict", "ok")]
    assert "private client text" not in json.dumps(tr.timeline(f"task:{t}"))


def test_a_refused_verdict_leaves_no_event():
    tr = Trace()
    b = Board(trace=tr)
    t = b.add("x task")
    assert not b.review(t, "ok")
    assert [e["source"] for e in tr.timeline(f"task:{t}")] == ["board"]


def test_agent_run_records_tool_calls_blocks_and_final():
    tr = Trace()
    res = Result(status="abstained", steps=2, seconds=1.5, reason="low_relevance:1.0",
                 tool_calls=[{"name": "buscar_notas", "args": {}, "ok": True}, {"name": "leer_nota", "args": {}, "ok": False}],
                 blocked=["path_outside_notes:../../etc/passwd"])
    record_agent(tr, "run1", "langgraph", "m", res)
    ev = tr.timeline("run1")
    assert [(e["kind"], e["name"], e["status"]) for e in ev] == [("tool_call", "buscar_notas", "ok"), ("tool_call", "leer_nota", "failed"),
                                                                ("policy_block", "path_outside_notes", "blocked"), ("final", "langgraph", "abstained")]
    assert ev[-1]["seconds"] == 1.5 and ev[-1]["data"] == {"model": "m", "steps": 2, "cited": None}
    assert tr.timeline("other") == []


def test_unknown_source_is_refused():
    with pytest.raises(ValueError):
        Trace().event("r", "somewhere", "k")


def test_demo_trace_accounts_for_every_task():
    tr = Trace()
    res = run(7, tr)
    c = tr.counts()
    verdicts = sum(n for k, n in c.items() if k.startswith("review.verdict."))
    outcomes = sum(n for k, n in c.items() if k.startswith("validation.outcome."))
    handled = res["tasks"] - res["routed_to_a_person"]
    assert verdicts == outcomes == c["board.transition.sent"] == handled
    assert c["board.transition.sending"] == handled + res["dispatch_errors_requeued"]
    assert c["router.decision.human_review"] == res["routed_to_a_person"] and c["router.decision.route"] == handled
