"""Read first, cheaply; act once: a free or cheap agent reads for the paid ones, and the paid ones go straight to the work."""
import subprocess
from pathlib import Path

import pytest

from caos_harness import app, orchestrator, scout
from tests.test_orchestrator import Fake, factory, plan_json, project, sub   # noqa: F401  (project is a fixture)


class ScoutFake(Fake):
    """Answers the scout's question with a brief that cites README.md (which exists in the test project) unless told to invent files."""
    def __init__(self, *a, brief="FILES: `README.md:1-2` the readme, why it matters", **kw):
        super().__init__(*a, **kw)
        self.brief = brief

    def __call__(self, cmd, input="", **kw):
        prompt = input or next((c for c in cmd if len(c) > 40), "")
        if "scout of a coding team" in prompt:
            super().__call__(cmd, input, **kw)
            return subprocess.CompletedProcess(cmd, 0, self.brief, "")
        return super().__call__(cmd, input, **kw)


@pytest.fixture(autouse=True)
def readme(project):
    (project.root / "README.md").write_text("# demo\nline two\n")
    scout._cache.clear()


def make_plan(project, subs, scout_name="auto", pool=None):
    raw = {"goal": "change the thing", "orchestrator": "claude", "subtasks": subs, "scout": orchestrator.resolve_scout(project, scout_name, pool or [s["agent"] for s in subs])}
    return orchestrator.normalize_plan(raw, project, pool)


def test_the_cost_of_an_agent_is_declared_or_inferred(project):
    tier = lambda n: scout.cost_tier(project.agents[n])
    assert (tier("claude"), tier("agy"), tier("opencode"), tier("qwen"), tier("cat")) == ("paid", "paid", "free", "free", "free")
    project.agents["opencode"] = app.Agent("opencode", ("opencode", "run", "-m", "opencode/big-model"))
    assert tier("opencode") == "cheap"
    project.agents["claude"] = app.Agent("claude", ("claude", "-p"), cost="cheap")
    assert tier("claude") == "cheap"


def test_the_map_ranks_by_the_task_and_carries_no_file_bodies(tmp_path):
    (tmp_path / "billing.py").write_text("SECRET_BODY = 1\n\ndef charge_invoice(a):\n    return a\n\nclass Ledger:\n    def post(self):\n        pass\n")
    (tmp_path / "other.py").write_text("def unrelated():\n    pass\n")
    m = scout.repo_map(tmp_path, "fix the invoice charge")
    lines = m.splitlines()
    assert lines[0].startswith("billing.py") and "charge_invoice:3-4" in lines[0] and "Ledger.post:7-8" in lines[0]
    assert "SECRET_BODY" not in m and len(scout.repo_map(tmp_path, "x", budget=40)) <= 40


def test_a_paid_executor_gets_a_scout_and_a_free_one_reads_for_itself(project):
    plan = make_plan(project, [sub(1, "agy"), sub(2, "qwen")])
    assert plan["scout"] == "opencode" and [s["scout"] for s in plan["subtasks"]] == [True, False]
    assert make_plan(project, [sub(1, "qwen")])["scout"] is None   # nobody costs money: nothing to save
    assert make_plan(project, [sub(1, "agy")], "off")["scout"] is None
    with pytest.raises(app.ConfigError):
        orchestrator.normalize_plan({"goal": "g", "orchestrator": "claude", "scout": "agy", "subtasks": [sub(1, "qwen")]}, project, None, strict=True)


def test_the_executor_receives_the_brief_after_its_task_and_the_scout_only_reads(project):
    fake = ScoutFake()
    run = orchestrator.OrchestrationRun(project, make_plan(project, [sub(1, "agy")]), factory=factory(project, fake))
    run.execute()
    scout_call = next(c for c in fake.calls if "scout of a coding team" in c["prompt"])
    work = [c for c in fake.calls if c["agent"] == "agy"][0]
    assert scout_call["agent"] == "opencode" and "Repository map" in scout_call["prompt"]
    assert "Prepared reading by opencode" in work["prompt"] and "README.md:1-2" in work["prompt"] and "do not search" in work["prompt"]
    s = run.snapshot()["orchestration"]["subtasks"][0]
    assert s["state"] == "delivered" and "README.md:1-2" in s["brief"] and s["scout_ms"] is not None and s["scout_cached"] is False


def test_a_scout_that_fails_never_blocks_the_work(project):
    fake = Fake(fail=("opencode",))
    run = orchestrator.OrchestrationRun(project, make_plan(project, [sub(1, "agy")]), factory=factory(project, fake))
    run.execute()
    s = run.snapshot()["orchestration"]["subtasks"][0]
    assert s["state"] == "delivered" and s["brief"] == "" and "ran without a brief" in s["note"]
    assert "Prepared reading" not in [c for c in fake.calls if c["agent"] == "agy"][0]["prompt"]


def test_the_same_reading_is_reused_and_off_means_no_extra_call(project):
    fake = ScoutFake()
    for _ in range(2):
        orchestrator.OrchestrationRun(project, make_plan(project, [sub(1, "agy")]), factory=factory(project, fake)).execute()
    assert sum("scout of a coding team" in c["prompt"] for c in fake.calls) == 1
    fake2 = Fake()
    orchestrator.OrchestrationRun(project, make_plan(project, [sub(1, "agy")], "off"), factory=factory(project, fake2)).execute()
    assert [c["agent"] for c in fake2.calls] == ["agy", "claude"]   # the work, then the synthesis: no reading


def test_the_planner_is_given_the_map_so_it_does_not_explore(project):
    (project.root / "billing.py").write_text("def charge_invoice(a):\n    return a\n")
    fake = Fake(plan=plan_json([sub(1, "agy")]))
    plan = orchestrator.plan_orchestration(project, "fix the invoice charge", "claude", ["agy", "qwen"], factory(project, fake))
    prompt = next(c["prompt"] for c in fake.calls if "Plan only" in c["prompt"])
    assert "billing.py" in prompt and "charge_invoice:1-2" in prompt and plan["scout"] == "opencode"


def test_a_brief_that_invents_files_is_discarded_and_the_work_goes_ahead(project):
    fake = ScoutFake(brief="FILES: `src/ghost.py:1-9` it handles everything, `src/phantom.py:3-4` too")
    run = orchestrator.OrchestrationRun(project, make_plan(project, [sub(1, "agy")]), factory=factory(project, fake))
    run.execute()
    s = run.snapshot()["orchestration"]["subtasks"][0]
    assert s["state"] == "delivered" and s["brief"] == "" and "do not exist" in s["note"]
    assert "Prepared reading" not in [c for c in fake.calls if c["agent"] == "agy"][0]["prompt"]


def test_citations_are_checked_by_code_and_the_lines_with_invented_files_are_dropped(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    brief, real, bad = scout.verify_citations("- `a.py:1-1` ok\n- `nope/ghost.py:1-2` invented\nplain note", tmp_path)
    assert (real, bad) == (1, 1) and "ghost" not in brief and "plain note" in brief


def test_a_model_without_file_tools_is_given_the_real_text_of_the_best_matches(project, tmp_path):
    (tmp_path / "jobs.py").write_text("class Runner:\n    def cancel(self):\n        self.proc.kill()\n\ndef unrelated():\n    return 1\n")
    ex = scout.excerpts(tmp_path, "make Runner.cancel stop the subprocess")
    assert ex.startswith("### jobs.py:2-3 Runner.cancel") and "self.proc.kill()" in ex and "unrelated" not in ex
    assert scout.has_file_tools(project.agents["opencode"]) and not scout.has_file_tools(project.agents["qwen"])
    fake = ScoutFake(brief="FILES: `README.md:1-2` ok")
    (project.root / "jobs.py").write_text("class Runner:\n    def cancel(self):\n        self.proc.kill()\n")
    scout.scout(project, "qwen", "make Runner.cancel stop the subprocess", "", factory(project, fake))
    asked = next(c["prompt"] for c in fake.calls if "scout of a coding team" in c["prompt"])
    assert "You cannot open files" in asked and "self.proc.kill()" in asked


def test_a_local_scout_runs_without_word_wrap_and_terminal_codes_are_cleaned(project):
    fake = ScoutFake(brief="FILES: `README.md:1-2` ok\x1b[K\x1b[?25l")
    r = scout.scout(project, "qwen", "read the readme", "", factory(project, fake))
    assert "\x1b" not in r["brief"] and r["brief"].endswith("ok")


def test_skills_from_a_share_pack_load_as_the_projects_own(project):
    from caos_harness import skills
    d = project.root / "team_skills" / "review-notes"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: review-notes\ndescription: Use when reviewing a change for a teammate, before the verdict\n---\nRead the diff first.\n")
    assert "review-notes" in skills.load_all(project_root=project.root)


def test_a_plain_command_is_marked_as_a_test_engine(project):
    from caos_harness.web.server import Api
    state = Api(project).state()
    flags = {a["name"]: a["test"] for a in state["agents"]}
    assert flags["cat"] is True and flags["claude"] is False and flags["qwen"] is False
