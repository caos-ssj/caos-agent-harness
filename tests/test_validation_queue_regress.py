import pytest
from caos_harness.validation.pipeline import Outcome
from caos_harness.validation.queue import ReviewQueue
from caos_harness.validation.regress import compare


def esc(i="a", label="billing"):
    return Outcome(i, "escalated", label, "low_confidence", 1)


def test_queue_is_idempotent_and_resolves(tmp_path):
    q = ReviewQueue(tmp_path / "q.db")
    assert q.add(esc("a"), "texto de prueba") is True
    assert q.add(esc("a"), "texto de prueba") is False  # no duplica
    assert len(q.pending()) == 1
    q.resolve("a", "billing", "ana")
    assert q.pending() == []
    assert q.stats()["reviewer_agrees_with_candidate"] == 1


def test_resolve_twice_or_bad_label_fails():
    q = ReviewQueue()
    q.add(esc("a"), "x" * 10)
    with pytest.raises(ValueError):
        q.resolve("a", "spam", "ana")
    q.resolve("a", "bug", "ana")
    with pytest.raises(KeyError):
        q.resolve("a", "bug", "ana")


def test_export_golden_closes_the_loop(tmp_path):
    q = ReviewQueue()
    q.add(esc("a"), "No puedo entrar a mi cuenta")
    q.resolve("a", "access", "ana")
    out = tmp_path / "g.jsonl"
    assert q.export_golden(out) == 1
    assert '"label": "access"' in out.read_text()


def test_regress_detects_drop_within_and_beyond_tolerance():
    base = {"precision": 0.9, "coverage": 0.8}
    assert compare(base, {"precision": 0.89, "coverage": 0.79}) == []
    assert len(compare(base, {"precision": 0.80, "coverage": 0.8})) == 1
    assert len(compare(base, {"precision": 0.80, "coverage": 0.5})) == 2
