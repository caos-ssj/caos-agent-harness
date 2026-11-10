import pytest
from caos_harness.validation.pipeline import MAX_RETRIES, process
from caos_harness.validation.sut import FlakyClient, RateLimited, classify


def rec(text="La app muestra un error al guardar", id="t"):
    return {"id": id, "text": text}


def test_ok_path():
    o = process(rec(), classify)
    assert (o.status, o.label, o.reason) == ("ok", "bug", "classified")


@pytest.mark.parametrize("text", ["", "   ", "ok", None])
def test_dq_rejects_bad_text(text):
    o = process({"id": "x", "text": text}, classify)
    assert o.status == "rejected" and o.reason == "dq_empty_or_short_text"


def test_retry_then_success_with_backoff():
    calls = {"n": 0}

    def flaky(text):
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError
        return classify(text)

    waited = []
    o = process(rec(), flaky, sleep=waited.append)
    assert o.status == "ok" and o.attempts == 3
    assert waited == [0.5, 1.0]  # backoff exponencial


def test_retries_exhausted_escalates_not_guesses():
    def always(text):
        raise TimeoutError

    o = process(rec(), always)
    assert o.status == "escalated" and o.reason == "retries_exhausted"
    assert o.label is None and o.attempts == MAX_RETRIES


def test_rate_limit_respects_retry_after():
    seq = iter([RateLimited(retry_after=2.0), None])

    def call(text):
        e = next(seq)
        if e:
            raise e
        return classify(text)

    waited = []
    o = process(rec(), call, sleep=waited.append)
    assert o.status == "ok" and waited == [2.0]


def test_schema_drift_is_escalated_with_reason():
    o = process(rec(), lambda t: {"category": "bug", "score": 0.9})
    assert o.status == "escalated" and o.reason == "schema_drift"


def test_invalid_label_escalated():
    o = process(rec(), lambda t: {"label": "spam", "confidence": 0.99})
    assert o.status == "escalated" and o.reason == "invalid_label"


def test_low_confidence_escalated_keeps_candidate_label():
    o = process(rec("Quisiera saber los horarios"), classify)
    assert o.status == "escalated" and o.reason == "low_confidence"


def test_flaky_client_is_deterministic_by_seed():
    a = FlakyClient(seed=3, p_timeout=0.5)
    b = FlakyClient(seed=3, p_timeout=0.5)

    def run(c):
        out = []
        for _ in range(20):
            try:
                c.call("hola mundo")
                out.append("ok")
            except TimeoutError:
                out.append("t")
        return out

    assert run(a) == run(b)


def test_missing_confidence_is_schema_drift():
    o = process(rec(), lambda t: {"label": "bug"})
    assert (o.status, o.reason) == ("escalated", "schema_drift")


@pytest.mark.parametrize("conf", [None, "alta", 1.5, -0.1, True])
def test_invalid_confidence_is_escalated_not_a_crash(conf):
    o = process(rec(), lambda t: {"label": "bug", "confidence": conf})
    assert (o.status, o.reason) == ("escalated", "invalid_confidence")
