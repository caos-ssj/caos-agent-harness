import asyncio

from caos_harness.engines import native
from caos_harness.memory.server import InMemoryKnowledge, KnowledgeBase, rows_of, search
from caos_harness.policy.guard import Policy

NOTES = {"conocimiento/Notas/reintentos.md": "Los reintentos con espera exponencial evitan saturar una API con límite de peticiones.",
         "conocimiento/Notas/citas.md": "Una cita solo vale si salió de lo que devolvió una herramienta."}


class Script:
    def __init__(self, msgs):
        self.msgs = list(msgs)

    def chat(self, messages, tools):
        return self.msgs.pop(0)


def tc(name, **args):
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}


def test_search_ranks_the_matching_note_first_with_a_score():
    rows = asyncio.run(search(InMemoryKnowledge(NOTES), "¿Para qué sirven los reintentos con espera exponencial?", 2))
    assert rows[0]["ruta"] == "conocimiento/Notas/reintentos.md" and rows[0]["puntos"] > rows[1]["puntos"] >= 1.0


def test_rows_ignore_anything_that_is_not_a_search_row():
    res = type("R", (), {"content": [type("C", (), {"text": t})() for t in ('{"ruta": "a", "puntos": 1.2}', "plain text", '{"other": 1}', "[1]")]})()
    assert rows_of(res) == [{"ruta": "a", "puntos": 1.2}] and rows_of(type("R", (), {"content": None})()) == []


def test_agent_answers_from_memory_and_the_citation_is_grounded():
    kb = InMemoryKnowledge(NOTES)
    llm = Script([tc("buscar_notas", pregunta="reintentos espera exponencial"), {"role": "assistant", "content": "Evitan saturar la API.\nNOTA: conocimiento/Notas/reintentos"}])
    r = asyncio.run(native.run_agent("¿reintentos?", kb, llm, []))
    assert r.status == "answered" and r.cited == "conocimiento/Notas/reintentos"


def test_agent_abstains_when_memory_scores_the_cited_note_low():
    kb = InMemoryKnowledge(NOTES)
    llm = Script([tc("buscar_notas", pregunta="capital de Mongolia"), {"role": "assistant", "content": "Ulán Bator.\nNOTA: conocimiento/Notas/citas"}])
    r = asyncio.run(native.run_agent("¿capital?", kb, llm, []))
    assert r.status == "abstained" and r.reason.startswith("low_relevance")


def test_guard_stops_a_read_outside_the_notes_before_memory_sees_it():
    kb = InMemoryKnowledge(NOTES)
    llm = Script([tc("leer_nota", ruta="../../etc/passwd"), {"role": "assistant", "content": "SIN RESPUESTA"}])
    r = asyncio.run(native.run_agent("q", kb, llm, [], Policy()))
    assert kb.calls == [] and r.blocked


def test_knowledge_base_reads_its_location_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("CEREBRO_DIR", str(tmp_path))
    kb = KnowledgeBase.from_env()
    assert kb.root == tmp_path and kb.command.startswith(str(tmp_path)) and kb.args[0].endswith("servidor_mcp.py")
