"""The two contracts: skills compared by what the board recorded, and outside signals that enter the board only with sources."""
import json
import sqlite3

import pytest

from caos_harness import app, radar, skill_eval, skills
from caos_harness.board.core import Board
from caos_harness.traces.store import Trace


class _Instant:
    def is_idle(self, agent):
        return True

    def send(self, agent, text):
        pass


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        self.t += 1
        return self.t


def run_task(b, skill, agent="a1", redos=0, accept=True, note="missing the test output"):
    tid = b.add("do it", queue=agent, skill=skill)
    for _ in range(redos):
        assert b.assign(tid, agent, _Instant()).ok and b.deliver(tid, "x") and b.review(tid, "redo", note)
    assert b.assign(tid, agent, _Instant()).ok and b.deliver(tid, "x")
    if accept:
        assert b.review(tid, "ok", "fine")
    return tid


@pytest.fixture
def board(tmp_path):
    return Board(":memory:", clock=Clock(), trace=Trace(tmp_path / "trace.db"))


def test_first_pass_counts_only_tasks_accepted_without_a_return(board):
    for _ in range(6):
        run_task(board, "coder")
    run_task(board, "coder", redos=2)                 # accepted in the end, but not at the first attempt
    run_task(board, "coder", redos=1, accept=False)   # returned and still open: already a first-pass failure
    run_task(board, "coder", accept=False)            # delivered, never judged: not evidence yet
    run_task(board, "qa", agent="a2")
    board.add("no skill at all", queue="a1")
    ev = {e.skill: e for e in skill_eval.evidence(board)}
    c = ev["coder"]
    assert (c.decided, c.first_pass, c.redos, c.open) == (8, 6, 3, 1) and c.rate == 0.75
    assert 0 < c.lower < 0.75 < c.upper <= 1 and c.median_seconds is not None
    assert ev["qa"].decided == 1 and set(ev) == {"coder", "qa"}
    per_agent = skill_eval.evidence(board, by_agent=True)
    assert {(e.skill, e.agent) for e in per_agent} == {("coder", "a1"), ("qa", "a2")}


def test_redo_notes_keep_every_return_even_after_the_task_was_accepted(board):
    run_task(board, "coder", redos=2, note="no evidence of the run")
    run_task(board, "coder")
    notes = skill_eval.redo_notes(board, "coder")
    assert [n["note"] for n in notes] == ["no evidence of the run"] * 2 and notes[0]["agent"] == "a1"
    assert skill_eval.redo_notes(board, "qa") == []


def test_history_splits_the_evidence_at_each_recorded_change_of_the_skill(board, tmp_path):
    old = skills.Skill("coder", "d", "old rules", tmp_path / "SKILL.md")
    new = skills.Skill("coder", "d", "new rules", tmp_path / "SKILL.md")
    for _ in range(3):
        run_task(board, "coder", redos=1)
    first = skill_eval.record_change(tmp_path, old, "baseline", clock=lambda: 1.0)
    assert skill_eval.record_change(tmp_path, old, "same text again", clock=lambda: 2.0) == first   # unchanged content is not a change
    skill_eval.record_change(tmp_path, new, "ask for the test output", clock=board.clock)
    for _ in range(4):
        run_task(board, "coder")
    h = skill_eval.history(board, tmp_path, "coder")
    assert [(v["sha"], v["evidence"].decided, v["evidence"].first_pass) for v in h] == [
        (skill_eval.fingerprint(old), 3, 0), (skill_eval.fingerprint(new), 4, 4)]
    assert len(skill_eval.changes(tmp_path)) == 2


def ev(decided, passed):
    lo, hi = skill_eval.wilson(passed, decided)
    return skill_eval.SkillEvidence("coder", None, decided, passed, 0, 0, round(passed / decided, 3), lo, hi, None)


def test_the_regression_gate_decides_on_interval_bounds_not_on_rates():
    base = ev(40, 28)                                                        # 0.70
    assert skill_eval.gate(base, ev(10, 10))["decision"] == "insufficient"    # 10/10 is not enough to say anything
    assert skill_eval.gate(base, ev(40, 38))["decision"] == "promote"
    assert skill_eval.gate(base, ev(40, 8))["decision"] == "reject"
    assert skill_eval.gate(base, ev(40, 26))["decision"] == "insufficient"    # a lower rate with overlapping intervals proves nothing
    assert skill_eval.gate(base, ev(40, 30))["decision"] == "promote"         # 0.75: its lower bound is not under the baseline's
    out = skill_eval.gate(ev(5, 5), ev(40, 38))
    assert out["decision"] == "insufficient" and "baseline" in out["reason"] and set(skill_eval.DECISIONS) >= {out["decision"]}


# ── radar ──

CASE = {"campos": {"titulo": "New release of an open workflow engine", "que_paso": "According to the project, version 3 adds native agents.",
                   "por_que_caos": "Matches the automation topic.", "accion_sugerida": "Review the original source.",
                   "falta_verificar": ["Confirm with a second independent source."]},
        "evidencia": [{"cita": "Version 3 adds native agents and a new queue mode.", "url": "https://example.org/blog/v3", "fuente": "example.org", "fecha": "2026-11-10"}],
        "origen": "plantilla"}


@pytest.fixture
def case_db(tmp_path):
    path = tmp_path / "cases.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE casos (case_id INTEGER PRIMARY KEY, event_id INTEGER, payload TEXT NOT NULL, valor REAL NOT NULL, "
               "confianza TEXT NOT NULL, estado TEXT NOT NULL DEFAULT 'nuevo', created_at INTEGER NOT NULL, delivered_at INTEGER)")
    no_source = {**CASE, "evidencia": [{"cita": "A quote with no link behind it at all.", "url": "", "fuente": ""}]}
    onion = {**CASE, "evidencia": [{"cita": "A quote behind a scheme that is not http.", "url": "javascript:alert(1)"}]}
    rows = [(1, json.dumps(CASE), 0.9, "A", "util"), (2, json.dumps(no_source), 0.8, "B", "util"), (3, "not json", 0.7, "C", "util"),
            (4, json.dumps(CASE), 0.95, "A", "nuevo"), (5, json.dumps(CASE), 0.2, "C", "util"), (6, json.dumps(onion), 0.6, "B", "util")]
    db.executemany("INSERT INTO casos (case_id, event_id, payload, valor, confianza, estado, created_at) VALUES (?,?,?,?,?,?,1)",
                   [(i, i, p, v, c, e) for i, p, v, c, e in rows])
    db.commit()
    db.close()
    return path


def test_only_cases_a_person_marked_useful_and_that_carry_a_source_become_signals(case_db):
    before = case_db.read_bytes()
    good, rejected = radar.read_cases(case_db)
    assert [s.id for s in good] == ["centinela:1", "centinela:5"]            # best first; the unjudged case 4 is not read at all
    assert {r["id"] for r in rejected} == {"centinela:2", "centinela:3", "centinela:6"}
    s = good[0]
    assert s.title.startswith("New release") and s.confidence == "A" and s.evidence[0].url == "https://example.org/blog/v3"
    assert s.to_verify == ("Confirm with a second independent source.",) and not radar.validate(s)
    assert [x.id for x in radar.read_cases(case_db, min_value=0.5)[0]] == ["centinela:1"]
    assert "centinela:4" in [x.id for x in radar.read_cases(case_db, states=("nuevo", "util"))[0]]
    assert case_db.read_bytes() == before                                    # the watcher's store is never written
    with pytest.raises(FileNotFoundError):
        radar.read_cases(case_db.parent / "missing.db")
    old = case_db.parent / "old.db"
    sqlite3.connect(old).execute("CREATE TABLE findings (finding_id INTEGER PRIMARY KEY)").connection.close()
    with pytest.raises(radar.StoreError, match="case engine"):          # a store from before cases existed
        radar.read_cases(old)


def test_a_signal_goes_to_the_board_once_fenced_as_data_with_its_sources(case_db, tmp_path):
    app.init(tmp_path)
    with open(tmp_path / "harness.toml", "a", encoding="utf-8") as f:
        f.write('[agents.writer]\ncommand = ["cat"]\n')
    project = app.load(tmp_path / "harness.toml")
    good, _ = radar.read_cases(case_db)
    added = radar.ingest(project, good, queue="writer", kind="content")
    assert [a["signal"] for a in added] == ["centinela:1", "centinela:5"]
    row = project.board.get(added[0]["task"])
    text = row["text"]
    assert text.index("third-party text") < text.index("<<<SIGNAL centinela:1") < text.index("https://example.org/blog/v3") < text.index("SIGNAL>>>")
    assert "Version 3 adds native agents" in text and row["queue"] == "writer" and "source" in row["criteria"]
    assert radar.ingest(project, good, queue="writer") == []                 # already taken: no duplicates on the next read
    with pytest.raises(ValueError):
        radar.task_text(good[0], kind="spam")
    bad = radar.Signal("x:1", "x", "t", "s", evidence=())
    assert radar.validate(bad) and radar.ingest(project, [bad], queue="writer") == []


def test_radar_pull_from_the_command_line_shows_first_and_adds_only_when_given_a_queue(case_db, tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path
    proj = tmp_path / "proj"
    proj.mkdir()
    app.init(proj)
    with open(proj / "harness.toml", "a", encoding="utf-8") as f:
        f.write('[agents.writer]\ncommand = ["cat"]\n')
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parent.parent)}
    run = lambda *a: subprocess.run([sys.executable, "-m", "caos_harness", "radar", "pull", "--db", str(case_db), "--json", *a], capture_output=True, text=True, cwd=proj, env=env)
    dry = json.loads(run().stdout)
    assert dry["dry_run"] and [s["id"] for s in dry["signals"]] == ["centinela:1", "centinela:5"] and len(dry["rejected"]) == 3 and dry["added"] == []
    real = json.loads(run("--queue", "writer", "--kind", "code", "--min-value", "0.5").stdout)
    assert [a["signal"] for a in real["added"]] == ["centinela:1"] and not real["dry_run"]
    text = app.load(proj / "harness.toml").board.get(real["added"][0]["task"])["text"]
    assert text.startswith("Propose one small change to this repository") and "https://example.org/blog/v3" in text
    assert run("--queue", "ghost").returncode != 0


def test_a_skill_proposal_must_be_anchored_to_recorded_returns_and_to_the_current_text(tmp_path):
    skill = skills.Skill("coder", "d", "Rules\n- Read the file first.\n- Keep changes small.\n", tmp_path / "SKILL.md")
    notes = [{"task": 41, "agent": "a1", "note": "no evidence of the run"}, {"task": 57, "agent": "a1", "note": "says the tests pass but shows no output"}]
    good = {"skill": "coder", "base_sha": skill_eval.fingerprint(skill), "problem": "returned for lacking test output", "expected": "those returns stop",
            "evidence": [{"task": 41, "quote": "no evidence of the run"}, {"task": 57, "quote": "shows no output"}],
            "change": {"kind": "add_rule", "anchor": None, "text": "End every delivery with the test command and its output."}}
    assert skill_eval.validate_proposal(good, skill, notes) == []
    bad = lambda **kw: skill_eval.validate_proposal({**good, **kw}, skill, notes)
    assert any("base_sha" in p for p in bad(base_sha="stale"))
    assert any("quote" in p for p in bad(evidence=[{"task": 41, "quote": "the reviewer never wrote this"}, {"task": 57, "quote": "shows no output"}]))
    assert any("fewer than 2" in p for p in bad(evidence=[{"task": 41, "quote": "no evidence of the run"}]))
    assert any("anchor" in p for p in bad(change={"kind": "replace_rule", "anchor": "- A line that is not there.", "text": "x" * 20}))
    assert bad(change={"kind": "remove_rule", "anchor": "- Keep changes small."}) == []
    assert any("already says" in p for p in bad(change={"kind": "add_rule", "text": "- Read the file first."}))
    assert any("at most" in p for p in bad(change={"kind": "add_rule", "text": "x" * 601}))
    assert skill_eval.validate_proposal("LGTM", skill, notes) == ["not an object"]
