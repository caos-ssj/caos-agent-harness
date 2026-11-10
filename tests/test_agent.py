import asyncio
import json

import pytest
from caos_harness.policy.guard import Blocked, Policy
import sys

from caos_harness.engines import native
from caos_harness.engines.native import parse_final

run_agent = native.run_agent


@pytest.fixture(autouse=True, params=["native", "langgraph"])
def engine(request, monkeypatch):
    """Every test in this file runs against both engines: same policy, same checks, two orchestrators."""
    if request.param == "langgraph":
        pytest.importorskip("langgraph")
        from caos_harness.engines import langgraph_engine
        monkeypatch.setattr(sys.modules[__name__], "run_agent", langgraph_engine.run_agent)
    return request.param


class Res:
    def __init__(self, text, err=False):
        self.content = [type("C", (), {"text": text})()]
        self.isError = err
        self.structuredContent = None


class FakeSession:
    def __init__(self, puntos=1.3):
        self.calls, self.puntos = [], puntos

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return Res(json.dumps({"ruta": "conocimiento/Notas/a.md", "puntos": self.puntos}))


class Script:
    """Modelo guionizado: devuelve mensajes en orden."""
    def __init__(self, msgs):
        self.msgs, self.latencies = list(msgs), []

    def chat(self, messages, tools):
        return self.msgs.pop(0)


def tc(name, **args):
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}


def final(text):
    return {"role": "assistant", "content": text}


def run(msgs, policy=None, puntos=1.3):
    s = FakeSession(puntos)
    r = asyncio.run(run_agent("pregunta", s, Script(msgs), [], policy))
    return r, s


def test_happy_path_cites_note():
    r, s = run([tc("buscar_notas", pregunta="x"), final("Respuesta.\nNOTA: conocimiento/Notas/a")])
    assert r.status == "answered" and r.cited == "conocimiento/Notas/a" and r.steps == 2


def test_abstains_when_no_answer():
    r, _ = run([tc("buscar_notas", pregunta="x"), final("No está.\nSIN RESPUESTA")])
    assert r.status == "abstained" and r.cited is None


@pytest.mark.parametrize("path", ["../../etc/passwd", "/etc/passwd", "~/.ssh/id_rsa", "conocimiento/../../x", "otra/cosa"])
def test_path_traversal_is_blocked_and_tool_not_called(path):
    r, s = run([tc("leer_nota", ruta=path), final("SIN RESPUESTA")])
    assert s.calls == [] and r.blocked and r.blocked[0].startswith("path_outside_notes")


def test_unknown_tool_blocked():
    r, s = run([tc("borrar_todo", x=1), final("SIN RESPUESTA")])
    assert s.calls == [] and r.blocked == ["tool_not_allowed:borrar_todo"]


def test_step_budget_stops_infinite_loop():
    msgs = [tc("buscar_notas", pregunta="x") for _ in range(10)]
    r, _ = run(msgs, Policy(max_steps=3, max_tool_calls=10))
    assert r.status == "budget_exhausted" and r.steps <= 3


def test_tool_call_budget():
    msgs = [tc("buscar_notas", pregunta="x") for _ in range(10)]
    r, s = run(msgs, Policy(max_steps=10, max_tool_calls=2))
    assert r.status == "budget_exhausted" and r.reason == "tool_calls" and len(s.calls) == 2


def test_llm_failure_does_not_crash_harness():
    class Boom:
        latencies = []
        def chat(self, m, t):
            raise TimeoutError

    r = asyncio.run(run_agent("q", FakeSession(), Boom(), []))
    assert r.status == "error" and r.reason == "llm:TimeoutError"


def test_n_is_clamped():
    assert Policy().check("buscar_notas", {"pregunta": "x", "n": 99})["n"] == 10
    with pytest.raises(Blocked):
        Policy().check("buscar_notas", {"pregunta": "x", "n": "mucho"})


def test_parse_final_variants():
    assert parse_final("Ok\nNOTA: `conocimiento/Notas/a.md`") == ("answered", "conocimiento/Notas/a")
    assert parse_final("sin respuesta") == ("abstained", None)
    assert parse_final("sin formato") == ("answered", None)


def test_citation_not_returned_by_any_tool_is_ungrounded():
    r, _ = run([tc("buscar_notas", pregunta="x"), final("Ok\nNOTA: conocimiento/Notas/inventada-123")])
    assert r.status == "ungrounded_citation"


def test_missing_note_line_is_flagged():
    r, _ = run([tc("buscar_notas", pregunta="x"), final("Respuesta sin cita")])
    assert r.status == "no_citation"


@pytest.mark.parametrize("puntos", [1.0, 0.0])
def test_low_relevance_citation_becomes_abstention(puntos):
    r, _ = run([tc("buscar_notas", pregunta="x"), final("Ok\nNOTA: conocimiento/Notas/a")], puntos=puntos)
    assert r.status == "abstained" and r.cited is None and r.reason.startswith("low_relevance")


def test_relevant_citation_at_threshold_is_answered():
    r, _ = run([tc("buscar_notas", pregunta="x"), final("Ok\nNOTA: conocimiento/Notas/a")], puntos=Policy().min_relevance)
    assert r.status == "answered"


def test_cited_note_read_but_never_scored_fails_closed():
    class ReadOnly(FakeSession):
        async def call_tool(self, name, args):
            self.calls.append((name, args))
            return Res("conocimiento/Notas/a contenido")

    r = asyncio.run(run_agent("q", ReadOnly(), Script([tc("leer_nota", ruta="conocimiento/Notas/a"), final("Ok\nNOTA: conocimiento/Notas/a")]), []))
    assert r.status == "abstained" and r.reason == "low_relevance:sin_puntos"
