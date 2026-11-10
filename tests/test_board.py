import json
import threading

import pytest
from caos_harness.board import Board, DispatchTimeout
from caos_harness.board.demo import run


class Disp:
    def __init__(self, idle=True, error=None):
        self.idle, self.error, self.sent = idle, error, []

    def is_idle(self, agent):
        return self.idle

    def send(self, agent, text):
        if self.error:
            raise self.error
        self.sent.append((agent, text))


def test_happy_path_needs_review_to_close():
    b, d = Board(), Disp()
    t = b.add("write the report", queue="a")
    assert b.assign(t, "a", d).ok and d.sent == [("a", "write the report")]
    assert b.to_review() == []                      # sent but not delivered: nothing to review yet
    assert b.deliver(t, "done") and [r["id"] for r in b.to_review()] == [t]
    assert b.review(t, "ok") and b.to_review() == []
    assert b.get(t)["status"] == "sent" and b.get(t)["review"] == "ok"


def test_busy_agent_receives_nothing():
    b, d = Board(), Disp(idle=False)
    t = b.add("x task")
    res = b.assign(t, "a", d)
    assert not res.ok and res.reason == "agent_busy" and d.sent == [] and b.get(t)["status"] == "pending"


def test_dispatch_error_returns_task_to_queue():
    b = Board()
    t = b.add("x task")
    res = b.assign(t, "a", Disp(error=ConnectionError()))
    assert res.reason == "dispatch_failed:ConnectionError" and b.get(t)["status"] == "pending" and b.get(t)["agent"] is None
    assert b.assign(t, "a", Disp()).ok              # and it can be sent again


def test_dispatch_timeout_stays_visible_and_is_not_resent():
    b = Board()
    t = b.add("x task")
    assert b.assign(t, "a", Disp(error=DispatchTimeout())).reason == "dispatch_unconfirmed"
    assert b.get(t)["status"] == "sending"
    d = Disp()
    assert b.assign(t, "a", d).reason == "not_pending" and d.sent == []


def test_only_one_of_many_simultaneous_assignments_wins():
    b, t_count = Board(), 8
    gate = threading.Barrier(t_count)

    class Racing(Disp):
        def is_idle(self, agent):
            gate.wait(timeout=5)  # every caller has already seen the task as pending before anyone claims it
            return True

    d = Racing()
    t = b.add("x task")
    results = []
    threads = [threading.Thread(target=lambda: results.append(b.assign(t, "a", d).ok)) for _ in range(t_count)]
    [th.start() for th in threads]
    [th.join() for th in threads]
    assert results.count(True) == 1 and len(d.sent) == 1


def test_redo_goes_back_to_its_agent_with_the_note_first():
    b, d = Board(), Disp()
    t = b.add("summarise the log", queue="b")
    b.assign(t, "a", d)
    b.deliver(t, "v1")
    assert b.review(t, "redo", "the dates are missing")
    row = b.get(t)
    assert row["status"] == "pending" and row["queue"] == "a"
    b.assign(t, "a", d)
    assert d.sent[-1][1].startswith("Returned by the reviewer") and "the dates are missing" in d.sent[-1][1] and d.sent[-1][1].endswith("summarise the log")
    assert b.get(t)["result"] is None and b.get(t)["review"] is None  # the old delivery no longer counts
    assert b.stats()["returned_at_least_once"] == 1


def test_verdict_rules():
    b, d = Board(), Disp()
    t = b.add("x task")
    assert not b.review(t, "ok")                    # cannot close what was never sent
    b.assign(t, "a", d)
    b.deliver(t, "r")
    assert b.review(t, "verify", "check the figure") and [r["id"] for r in b.to_review()] == [t]
    assert b.review(t, "superseded", "done elsewhere") and b.to_review() == []
    assert not b.review(t, "verify")                # a closed task does not reopen as verify
    with pytest.raises(ValueError):
        b.review(t, "great")


def test_control_characters_never_reach_the_agent():
    b, d = Board(), Disp()
    t = b.add("line one\nline two\x03 end")
    b.assign(t, "a", d)
    assert d.sent[0][1] == "line one line two end"
    with pytest.raises(ValueError):
        b.add("\n\x00")


def test_discard_only_while_pending():
    b, d = Board(), Disp()
    t1, t2 = b.add("one task"), b.add("two task")
    b.assign(t2, "a", d)
    assert b.discard(t1) and not b.discard(t2)


def test_stats_carry_no_task_text():
    b, d = Board(), Disp()
    t = b.add("secret client name")
    b.assign(t, "a", d)
    assert "secret" not in json.dumps(b.stats())


def test_demo_is_deterministic_and_loses_nothing():
    a, c = run(7), run(7)
    assert a == c and a["lost"] == 0 and a["left_without_review"] == 0
    assert a["routed_to_a_person"] + a["closed_ok"] + a["closed_bad_input"] + a["open_for_human_review"] == a["tasks"] == 25
    assert a["routed_to_a_person"] == 5 and "person" not in a["by_agent"]   # the critical tier never reaches an agent
    assert a["dispatch_errors_requeued"] == 1 and a["held_while_agent_busy"] > 0
