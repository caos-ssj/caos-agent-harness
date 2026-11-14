"""Skills that learn from returns: evidence pack → a cheap reader proposes → code validates → a person starts a trial → the gate
promotes or restores. The reader is a stand-in command; what is under test is what the harness does with its answer."""
import json
import subprocess

import pytest

from caos_harness import app, providers, skill_eval, skills

BODY = "# Rules\n\n- Read the file first.\n- Never push without asking. [fixed]\n- Keep changes small.\n"


class Instant:
    is_idle = lambda self, a: True
    send = lambda self, a, t: None


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(providers.shutil, "which", lambda b: "/usr/bin/" + b)
    app.init(tmp_path)
    with open(tmp_path / "harness.toml", "a", encoding="utf-8") as f:
        f.write('[agents.worker]\ncommand = ["cat"]\n[agents.reader]\ncost = "free"\ncommand = ["opencode", "run", "-m", "opencode/some-free"]\n')
    skills.save_local_skill(tmp_path, "house", "How we change code in this house", BODY)
    return app.load(tmp_path / "harness.toml")


def task(project, redos=0, note="no output of the test run", accept=True):
    b = project.board
    tid = b.add("change the parser", queue="worker", skill="house")
    for _ in range(redos):
        assert b.assign(tid, "worker", Instant()).ok and b.deliver(tid, "x") and b.review(tid, "redo", note)
    assert b.assign(tid, "worker", Instant()).ok and b.deliver(tid, "x")
    if accept:
        b.review(tid, "ok", "fine")
    return tid


def reader(project, answer):
    """A factory whose reader agent prints `answer` (a dict is sent as JSON, with chatter around it)."""
    calls = []

    def run(cmd, input="", **kw):
        calls.append(input or next((c for c in cmd if len(c) > 40), ""))
        return subprocess.CompletedProcess(cmd, 0, f"Sure, here it is:\n{json.dumps(answer) if isinstance(answer, dict) else answer}\n", "")
    return (lambda cwd=None, override=None: app.CommandDispatcher(project, run, cwd=cwd, override=override)), calls


def good(project, a, b, **change):
    skill = skills.load_all(project_root=project.root)["house"]
    return {"skill": "house", "base_sha": skill_eval.fingerprint(skill), "problem": "deliveries lack the test output", "expected": "those returns stop",
            "evidence": [{"task": a, "quote": "no output of the test run"}, {"task": b, "quote": "output of the test"}],
            "change": change or {"kind": "add_rule", "anchor": None, "text": "End every delivery with the test command and its output."}}


def test_the_pack_holds_only_this_skills_numbers_and_notes_and_the_reader_gets_it(project):
    a, b = task(project, redos=1), task(project, redos=2)
    project.board.add("write a post", queue="worker", skill="writer")
    skill = skills.load_all(project_root=project.root)["house"]
    text = skill_eval.pack(project.board, skill)
    assert f"task {a} (worker): no output of the test run" in text and "returns: 3" in text and "write a post" not in text
    factory, calls = reader(project, good(project, a, b))
    out = skill_eval.propose(project, "house", factory=factory)
    assert out["reader"] == "reader" and out["problems"] == [] and out["proposal"]["change"]["kind"] == "add_rule"
    assert "<<<SKILL house" in calls[0] and "Never push without asking. [fixed]" in calls[0] and skill_eval.fingerprint(skill) in calls[0]
    assert skills.load_all(project_root=project.root)["house"].body == skill.body       # proposing writes nothing


def test_a_proposal_from_the_reader_is_checked_before_anyone_sees_it(project):
    a, b = task(project, redos=1), task(project, redos=1)
    bad_quote = good(project, a, b)
    bad_quote["evidence"][1]["quote"] = "the reviewer never wrote these words"
    for answer, expect in ((bad_quote, "quote"), ("I think the skill is fine as it is.", "did not answer"),
                           (good(project, a, b, kind="remove_rule", anchor="- Never push without asking. [fixed]"), "[fixed]"),
                           (good(project, a, b, kind="replace_rule", anchor="- Never push without asking. [fixed]", text="Push freely."), "[fixed]")):
        factory, _ = reader(project, answer)
        assert any(expect in p for p in skill_eval.propose(project, "house", factory=factory)["problems"]), expect
    with pytest.raises(ValueError):
        skill_eval.propose(project, "ghost")


def test_without_two_returned_tasks_no_model_is_called(project):
    task(project, redos=1)
    factory, calls = reader(project, {})
    out = skill_eval.propose(project, "house", factory=factory)
    assert out["proposal"] is None and "not enough evidence" in out["problems"][0] and calls == []


def test_a_trial_changes_the_projects_copy_and_a_rejected_one_restores_the_exact_text(project):
    a, b = task(project, redos=1), task(project, redos=1)
    before = skills.load_all(project_root=project.root)["house"]
    with pytest.raises(ValueError, match="not valid"):
        skill_eval.start_trial(project, {**good(project, a, b), "base_sha": "stale"})
    t = skill_eval.start_trial(project, good(project, a, b))
    during = skills.load_all(project_root=project.root)["house"]
    assert during.body.rstrip().endswith("- End every delivery with the test command and its output.") and "[fixed]" in during.body
    assert skill_eval.fingerprint(during) == t["candidate_sha"] != t["base_sha"] == skill_eval.fingerprint(before)
    with pytest.raises(ValueError, match="already has an open trial"):
        skill_eval.start_trial(project, good(project, a, b))
    st = skill_eval.trial_status(project, "house")
    assert st["gate"]["decision"] == "insufficient" and st["gate"]["baseline"]["decided"] == 2 and st["gate"]["candidate"]["decided"] == 0
    assert skill_eval.close_trial(project, "house")["decision"] == "insufficient" and "house" in skill_eval.open_trials(project.root)

    out = skill_eval.close_trial(project, "house", force="reject")          # the person decides with less evidence than the gate asks for
    assert out == {"skill": "house", "decision": "reject", "forced": True, "gate": out["gate"], "restored_sha": t["base_sha"]}
    assert skills.load_all(project_root=project.root)["house"].body == before.body and skill_eval.open_trials(project.root) == {}
    assert [c["note"].split(":")[0] for c in skill_eval.changes(project.root)] == ["baseline before trial", "trial", "trial rejected"]


def test_the_gate_promotes_a_trial_only_on_evidence_from_after_it_started(project):
    ids = [task(project, redos=1) for _ in range(6)] + [task(project) for _ in range(4)]     # before: 4 of 10 at the first attempt
    skill_eval.start_trial(project, good(project, ids[0], ids[1]))
    for _ in range(9):
        task(project)
    assert skill_eval.trial_status(project, "house", min_decided=10)["gate"]["decision"] == "insufficient"   # 9 decided: one short
    task(project)
    st = skill_eval.trial_status(project, "house", min_decided=10)
    assert st["gate"]["decision"] == "promote" and st["gate"]["baseline"]["first_pass"] == 4 and st["gate"]["candidate"]["first_pass"] == 10
    out = skill_eval.close_trial(project, "house", min_decided=10)
    assert out["decision"] == "promote" and not out["forced"] and skill_eval.open_trials(project.root) == {}
    assert "End every delivery" in skills.load_all(project_root=project.root)["house"].body
    row = next(r for r in skill_eval.overview(project) if r["skill"] == "house")
    assert row["trial"] is None and row["note_tasks"] == 6 and row["can_propose"] and row["evidence"]["decided"] == 20


def test_a_measurably_worse_trial_is_rejected_by_the_gate_itself(project):
    ids = [task(project) for _ in range(10)] + [task(project, redos=1), task(project, redos=1)]
    skill_eval.start_trial(project, good(project, ids[10], ids[11], kind="remove_rule", anchor="- Keep changes small."))
    for _ in range(10):
        task(project, redos=1)
    out = skill_eval.close_trial(project, "house", min_decided=10)
    assert out["decision"] == "reject" and not out["forced"] and "- Keep changes small." in skills.load_all(project_root=project.root)["house"].body


def test_rejecting_a_trial_on_a_packaged_skill_brings_the_packaged_text_back(project):
    b = project.board
    ids = []
    for _ in range(2):
        tid = b.add("fix it", queue="worker", skill="coder")
        assert b.assign(tid, "worker", Instant()).ok and b.deliver(tid, "x") and b.review(tid, "redo", "no evidence of the run at all")
        ids.append(tid)
    packaged = skills.load_packaged()["coder"]
    proposal = {"skill": "coder", "base_sha": skill_eval.fingerprint(packaged), "problem": "no evidence", "expected": "returns stop",
                "evidence": [{"task": i, "quote": "no evidence of the run"} for i in ids],
                "change": {"kind": "add_rule", "text": "Paste the last lines of the test run in the delivery."}}
    skill_eval.start_trial(project, proposal)
    assert skills.load_all(project_root=project.root)["coder"].local
    out = skill_eval.close_trial(project, "coder", force="reject")
    now = skills.load_all(project_root=project.root)["coder"]
    assert out["restored_sha"] == skill_eval.fingerprint(packaged) and not now.local and now.body == packaged.body


def test_the_dashboard_api_shows_the_evidence_and_runs_a_trial_end_to_end(project):
    from caos_harness.web.server import Api
    a, b = task(project, redos=1), task(project, redos=1)
    api = Api(project)
    row = next(r for r in api.skills_evidence()["skills"] if r["skill"] == "house")
    assert row["can_propose"] and row["note_tasks"] == 2 and row["evidence"]["decided"] == 2 and row["trial"] is None
    with pytest.raises(app.ConfigError, match="not valid"):
        api.skill_trial_start({"proposal": {**good(project, a, b), "base_sha": "stale"}})
    started = api.skill_trial_start({"proposal": good(project, a, b)})
    assert started["status"]["gate"]["decision"] == "insufficient"
    row = next(r for r in api.skills_evidence()["skills"] if r["skill"] == "house")
    assert row["trial"]["change"]["kind"] == "add_rule" and not row["can_propose"]
    assert api.skill_trial_close({"skill": "house", "force": "reject"})["decision"] == "reject"
    with pytest.raises(app.ConfigError, match="no open trial"):
        api.skill_trial_close({"skill": "house"})
