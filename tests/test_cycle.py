"""The autonomous cycle: author edits in a worktree → another agent reviews blind → verify command → landed, or back with findings.
Agents are stand-in commands: what is under test is what the harness does with their answers."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from caos_harness import app, cycle, landed, ledger, orchestrator, worktrees

PY = sys.executable
PASS = [PY, "-c", "import feature; assert feature.VALUE == 1"]
FAIL = [PY, "-c", "raise SystemExit(1)"]
APPROVE = json.dumps({"verdict": "approve", "checked": ["feature.py"], "findings": []})
REJECT = json.dumps({"verdict": "reject", "checked": ["feature.py"], "findings": [{"file": "feature.py", "problem": "VALUE should be 2, the task says so"}]})
TOML = '''
[agents.agy]
cost = "cheap"
command = ["agy", "--mode", "accept-edits", "-p", "{prompt}"]
[agents.gemini2]
cost = "free"
command = ["agy", "--mode", "plan", "-p", "{prompt}"]
[agents.opencode]
cost = "free"
command = ["opencode", "run", "-m", "opencode/some-free"]
[agents.claude]
cost = "paid"
command = ["claude", "-p", "--model", "sonnet"]
[agents.tool]
command = ["cat"]
'''


def git(root, *args):
    return subprocess.run(["git", "-c", "user.email=t@example.test", "-c", "user.name=t", *args], cwd=root, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def project(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    app.init(tmp_path)
    with open(tmp_path / "harness.toml", "a", encoding="utf-8") as f:
        f.write(TOML)
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".harness/\n__pycache__/\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "init")
    return app.load(tmp_path / "harness.toml")


class Agents:
    """Stands in for every CLI. The author writes feature.py in its working folder; the reviewer answers what it was told to."""
    def __init__(self, review=APPROVE, meddle=False, crash=False):
        self.review, self.meddle, self.crash, self.calls = review, meddle, crash, []

    def __call__(self, cmd, input="", **kw):
        prompt = input or next((c for c in cmd if len(c) > 40), "")
        self.calls.append({"bin": cmd[0], "cmd": list(cmd), "cwd": kw.get("cwd"), "prompt": prompt})
        if "You are reviewing a change" in prompt:
            if self.crash:
                return subprocess.CompletedProcess(cmd, 1, "", "boom")
            if getattr(self, "meddle_path", None):
                self.meddle_path.write_text("# rewritten by the reviewer\n", encoding="utf-8")
            if self.meddle:
                (Path(kw["cwd"]) / "feature.py").write_text("VALUE = 'the reviewer rewrote it'\n", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, f"Here is my review:\n{self.review}\n", "")
        if "write the final synthesis" in prompt:
            return subprocess.CompletedProcess(cmd, 0, "SYNTHESIS", "")
        if cmd[0] == "agy" and kw.get("cwd") and ".harness" in str(kw["cwd"]):
            (Path(kw["cwd"]) / "feature.py").write_text("VALUE = 1\n", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "delivered", "")

    def factory(self, project):
        return lambda cwd=None, override=None: app.CommandDispatcher(project, self, cwd=cwd, override=override)


def authored(project, key="job", with_task=True):
    """A worktree with the author's edit and, by default, its delivered board task."""
    wt = worktrees.ensure(project.root, key)
    (Path(wt["path"]) / "feature.py").write_text("VALUE = 1\n", encoding="utf-8")
    if not with_task:
        return None
    b = project.board
    tid = b.add("add feature.py with VALUE = 1", queue="agy", criteria="feature.VALUE == 1", worktree_key=key)

    class Instant:
        is_idle = lambda self, a: True
        send = lambda self, a, t: None
    assert b.assign(tid, "agy", Instant()).ok and b.deliver(tid, "done")
    return tid


def test_the_verifier_is_never_the_author_and_prefers_another_family_then_the_cheapest(project):
    assert cycle.pick_verifier(project, "agy") == "opencode"          # gemini2 is free too, but it is the author's own tool family
    assert cycle.pick_verifier(project, "opencode") == "gemini2"      # another family, free before the cheap and the paid one
    assert cycle.pick_verifier(project, "agy", "claude") == "claude"
    for bad in ("agy", "tool", "ghost", app.PERSON):                  # itself, a command that is not an AI agent, unknown, the human queue
        with pytest.raises(app.ConfigError):
            cycle.pick_verifier(project, "agy", bad)
    del project.agents["opencode"], project.agents["claude"], project.agents["gemini2"]
    with pytest.raises(app.ConfigError, match="second AI agent"):
        cycle.pick_verifier(project, "agy")


def test_a_review_only_counts_for_what_code_can_check():
    files = ["feature.py", "tests/test_feature.py"]
    assert cycle.parse_review(APPROVE, files)["verdict"] == "approve"
    assert cycle.parse_review("LGTM, ship it", files)["verdict"] == "invalid"
    assert cycle.parse_review('{"verdict": "approve", "checked": [], "findings": []}', files)["verdict"] == "invalid"            # read nothing
    assert cycle.parse_review('{"verdict": "approve", "checked": ["other.py"], "findings": []}', files)["verdict"] == "invalid"   # not a changed file
    assert cycle.parse_review('{"verdict": "maybe"}', files)["verdict"] == "invalid"
    mixed = cycle.parse_review('{"verdict": "approve", "checked": ["feature.py"], "findings": [{"file": "feature.py", "problem": "breaks import"}]}', files)
    assert mixed["verdict"] == "reject" and mixed["findings"] == [{"file": "feature.py", "problem": "breaks import"}]
    r = cycle.parse_review('{"verdict": "reject", "findings": [{"file": "invented.py", "problem": "x"}, {"file": "feature.py", "problem": "y"}]}', files)
    assert r["verdict"] == "reject" and [f["file"] for f in r["findings"]] == ["feature.py"]                                      # the invented file is dropped
    assert cycle.parse_review('{"verdict": "reject", "findings": []}', files)["reason"]
    wrapped = '\x1b[?2026h{"verdict": "reject", "checked": ["feature.py"], "findings": [{"file": "feat\x1b[5D\x1b[K\n"feature.py", "problem": "off by 1"}]}'
    cleaned = cycle.parse_review(wrapped, files)
    assert cleaned["verdict"] == "reject" and cleaned["findings"] == [{"file": "feature.py", "problem": "off by 1"}]


def test_approved_and_verified_lands_when_the_cycle_may_apply(project):
    tid, agents = authored(project), Agents()
    out = cycle.run_cycle(project, "job", "agy", verify=PASS, apply=True, factory=agents.factory(project))
    assert out["status"] == "landed" and out["target"] == "branch" and out["review"]["verifier"] == "opencode" and out["tasks"] == [tid], out
    # verified work goes to harness/landed: the project folder and its branch do not change
    assert not (project.root / "feature.py").exists() and git(project.root, "status", "--porcelain") == ""
    assert git(project.root, "show", f"{landed.BRANCH}:feature.py").strip() == "VALUE = 1"
    assert "Harness-Reviewed-By: opencode" in git(project.root, "log", "-1", "--format=%B", landed.BRANCH)
    (rec,) = cycle.recent(project)
    assert rec["id"] == out["id"] and rec["landing"]["commit"] == out["landing"]["commit"] and rec["review"]["verdict"] == "approve"
    call = agents.calls[0]
    assert call["bin"] == "opencode" and Path(call["cwd"]) == project.root / ".harness" / "worktrees" / "job"   # it reads the worktree
    assert "+VALUE = 1" in call["prompt"] and "feature.VALUE == 1" in call["prompt"] and "add feature.py" in call["prompt"]
    assert project.board.get(tid)["review"] is None                     # landing does not close the task: the verdict stays human
    ev = [e for e in project.board.trace.timeline(f"task:{tid}") if e["kind"] == "cycle"]
    assert len(ev) == 1 and ev[0]["status"] == "landed" and ev[0]["name"] == "opencode"


def test_without_permission_to_apply_an_approved_change_waits_as_ready(project):
    authored(project)
    out = cycle.run_cycle(project, "job", "agy", verify=PASS, factory=Agents().factory(project))   # no [landing] autonomous, no apply
    assert out["status"] == "ready" and out["landing"]["status"] == "verified" and not (project.root / "feature.py").exists()
    with open(project.root / "harness.toml", "a", encoding="utf-8") as f:
        f.write("[landing]\nautonomous = true\nverifier = \"claude\"\n")
    out = cycle.run_cycle(project, "job", "agy", verify=PASS, factory=Agents().factory(project))
    assert out["status"] == "landed" and out["review"]["verifier"] == "claude"


def test_a_rejected_change_never_lands_and_can_go_back_to_its_agent_with_the_findings(project):
    tid = authored(project)
    out = cycle.run_cycle(project, "job", "agy", verify=PASS, apply=True, auto_redo=True, factory=Agents(REJECT).factory(project))
    assert out["status"] == "rejected" and out["returned"] and not (project.root / "feature.py").exists()
    assert out["landing"]["status"] == "verified"                       # the tests still ran, as a dry run: that is the measurement
    row = project.board.get(tid)
    assert row["status"] == "pending" and row["review"] == "redo" and "VALUE should be 2" in row["review_note"] and "opencode" in row["review_note"]


def test_an_approved_change_that_fails_the_verify_command_does_not_land(project):
    authored(project)
    out = cycle.run_cycle(project, "job", "agy", verify=FAIL, apply=True, factory=Agents().factory(project))
    assert out["status"] == "verify_failed" and not (project.root / "feature.py").exists() and not out["returned"]


def test_a_reviewer_that_edits_the_change_or_crashes_voids_its_review(project):
    authored(project, "a")
    out = cycle.run_cycle(project, "a", "agy", verify=PASS, apply=True, factory=Agents(meddle=True).factory(project))
    assert out["review"]["verdict"] == "tampered" and out["status"] == "rejected" and not (project.root / "feature.py").exists()
    authored(project, "c")
    outside = Agents()
    outside.meddle_path = project.root / "README.md"                    # it writes in the project folder instead of the worktree
    out = cycle.run_cycle(project, "c", "agy", verify=PASS, apply=True, factory=outside.factory(project))
    assert out["review"]["verdict"] == "tampered" and "project folder" in out["review"]["reason"] and not (project.root / "feature.py").exists()
    git(project.root, "checkout", "--", "README.md")
    authored(project, "b")
    out = cycle.run_cycle(project, "b", "agy", verify=PASS, apply=True, factory=Agents(crash=True).factory(project))
    assert out["review"]["verdict"] == "invalid" and out["status"] == "rejected" and not (project.root / "feature.py").exists()


def test_an_untouched_worktree_is_empty_and_a_cycle_needs_a_verify_command(project):
    worktrees.ensure(project.root, "idle")
    agents = Agents()
    assert cycle.run_cycle(project, "idle", "agy", verify=PASS, apply=True, factory=agents.factory(project))["status"] == "empty"
    assert agents.calls == []                                           # nothing to review: no model was called
    with pytest.raises(app.ConfigError, match="no verify command"):
        cycle.run_cycle(project, "idle", "agy", factory=agents.factory(project))


def test_the_reviewer_is_measured_against_the_verify_command_it_could_not_see(project):
    runs = [(APPROVE, PASS), (APPROVE, FAIL), (REJECT, FAIL), (REJECT, FAIL), (REJECT, PASS)]
    for i, (answer, verify) in enumerate(runs):
        authored(project, f"k{i}")
        cycle.run_cycle(project, f"k{i}", "agy", verify=verify, factory=Agents(answer).factory(project))
    (s,) = cycle.verifier_stats(project)
    assert (s["verifier"], s["cycles"], s["failed"], s["caught"], s["approved"], s["approved_passed"]) == ("opencode", 5, 3, 2, 2, 1)
    lo, hi = s["catch_rate_ci95"]
    assert lo < 2 / 3 < hi and s["approval_precision_ci95"][0] < 0.5 < s["approval_precision_ci95"][1]


def test_an_orchestration_with_the_cycle_on_takes_each_edit_through_review_and_the_gate(project):
    with open(project.root / "harness.toml", "a", encoding="utf-8") as f:
        f.write(f'[landing]\nautonomous = true\nverify = [{json.dumps(PY)}, "-c", "import feature; assert feature.VALUE == 1"]\n')
    agents = Agents()
    plan = orchestrator.normalize_plan({"orchestrator": "claude", "goal": "add the feature module end to end", "summary": "one edit", "scout": "opencode", "subtasks": [
        {"id": "s1", "title": "write it", "agent": "agy", "mode": "isolated", "skill": None, "task": "add feature.py with VALUE = 1 in the project", "criteria": "feature.VALUE == 1"}]}, project, strict=True)
    run = orchestrator.OrchestrationRun(project, plan, factory=agents.factory(project), cycle=True)
    run.execute()
    s = run.snapshot()["orchestration"]["subtasks"][0]
    assert s["state"] == "delivered" and s["cycle"]["status"] == "landed" and s["cycle"]["review"]["verifier"] == "opencode", s
    assert git(project.root, "show", f"{landed.BRANCH}:feature.py").strip() == "VALUE = 1" and not (project.root / "feature.py").exists()
    # the whole cycle, in order: the free scout reads ahead, the author edits, another agent reviews, the orchestrator writes the synthesis
    assert [c["bin"] for c in agents.calls] == ["opencode", "agy", "opencode", "claude"]
    assert "You are reviewing a change" not in agents.calls[0]["prompt"] and "You are reviewing a change" in agents.calls[2]["prompt"]

    off = orchestrator.OrchestrationRun(project, plan, factory=Agents().factory(project))
    off.execute()
    assert "cycle" not in off.snapshot()["orchestration"]["subtasks"][0]          # opt-in: a plain run behaves as before


def test_the_folder_target_still_applies_to_the_project_folder_when_asked_for(project):
    authored(project)
    out = cycle.run_cycle(project, "job", "agy", verify=PASS, apply=True, target="folder", factory=Agents().factory(project))
    assert out["status"] == "landed" and (project.root / "feature.py").read_text() == "VALUE = 1\n" and landed.tip(project.root) is None
    with pytest.raises(app.ConfigError):
        cycle.run_cycle(project, "job", "agy", verify=PASS, target="main", factory=Agents().factory(project))


def test_two_changes_to_the_same_line_the_second_is_a_conflict_and_goes_back_with_the_reason(project):
    (project.root / "notes.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    git(project.root, "add", "-A")
    git(project.root, "commit", "-q", "-m", "notes")
    for key, text in (("a", "alpha\nbeta from A\n"), ("b", "alpha\nbeta from B\n")):
        wt = worktrees.ensure(project.root, key)
        (Path(wt["path"]) / "notes.txt").write_text(text, encoding="utf-8")
    ok = json.dumps({"verdict": "approve", "checked": ["notes.txt"], "findings": []})
    first = cycle.run_cycle(project, "a", "agy", verify=[PY, "-c", "pass"], apply=True, factory=Agents(ok).factory(project))
    second = cycle.run_cycle(project, "b", "agy", verify=[PY, "-c", "pass"], apply=True, factory=Agents(ok).factory(project))
    assert first["status"] == "landed" and second["status"] == "conflict" and second["landing"]["conflicts"] == ["notes.txt"]
    assert landed.tip(project.root) == first["landing"]["commit"]
    # a worktree for the retry starts from what already landed
    retry = worktrees.ensure(project.root, "b2", landed.rebase_point(project.root))
    assert "beta from A" in (Path(retry["path"]) / "notes.txt").read_text()


def test_every_call_is_in_the_ledger_with_what_was_measured_and_no_tokens_it_was_not_told(project):
    authored(project)
    cycle.run_cycle(project, "job", "agy", verify=PASS, factory=Agents().factory(project))      # one call: the reviewer (free)
    tid = project.board.add("summarise", queue="claude")
    app.run_pending(project, dispatcher=app.CommandDispatcher(project, Agents()))             # one call: a paid agent
    project.board.review(tid, "ok", "fine")
    led = ledger.summary(project)
    by = {r["agent"]: r for r in led["agents"]}
    assert by["opencode"]["tier"] == "free" and by["opencode"]["calls"] == 1 and by["opencode"]["chars_in"] > 100 and by["opencode"]["chars_out"] > 10
    assert by["claude"]["tier"] == "paid" and by["claude"]["tokens_in"] is None and by["claude"]["calls_with_tokens"] == 0
    assert (led["calls"], led["paid_calls"], led["accepted"], led["accepted_first_attempt"]) == (2, 1, 1, 1)
    boom = lambda cmd, input="", **kw: subprocess.CompletedProcess(cmd, 1, "", "boom")
    project.board.add("again", queue="claude")
    app.run_pending(project, dispatcher=app.CommandDispatcher(project, boom))
    assert {r["agent"]: r for r in ledger.summary(project)["agents"]}["claude"]["failed"] == 1


def test_the_run_overview_api_puts_cycles_branch_reviewers_and_ledger_on_one_screen(project):
    from caos_harness.web.server import Api
    api = Api(project)
    empty = api.run_overview()
    assert empty["git_repo"] and empty["cycles"] == [] and empty["landed"]["tip"] is None and empty["config"]["target"] == "branch"
    assert "tool" not in empty["agents"] and {"agy", "opencode", "claude"} <= set(empty["agents"])
    authored(project)
    worktrees.ensure(project.root, "idle")
    assert [(w["key"], w["last"]) for w in api.run_overview()["waiting"]] == [("job", None), ("idle", None)]
    out = cycle.run_cycle(project, "job", "agy", verify=PASS, apply=True, factory=Agents().factory(project))
    o = api.run_overview()
    assert o["cycles"][0]["id"] == out["id"] and o["landed"]["tip"] == out["landing"]["commit"] and o["landed"]["base"] == "main"
    assert o["landed"]["entries"][0]["reviewed_by"] == "opencode" and o["landed"]["entries"][0]["intact"] and o["landed"]["entries"][0]["at"] > 0
    assert o["landed"]["files"] == [{"path": "feature.py", "added": 1, "removed": 0}] and [w["key"] for w in o["waiting"]] == ["idle"]
    assert o["verifiers"][0]["verifier"] == "opencode" and o["ledger"]["calls"] == 1 and "+VALUE = 1" in api.landed_diff()["diff"]
    assert not api.landed_undo({"expected": "0" * 40})["ok"] and api.landed_undo({"expected": out["landing"]["commit"]})["ok"]
    assert api.run_overview()["landed"]["tip"] is None
    with pytest.raises(app.ConfigError):
        api.cycle_run({"key": "idle", "author": "nobody"})


def test_the_stations_show_each_agents_role_from_what_it_did_and_the_shift_since_a_moment(project):
    from caos_harness.web.server import Api
    api = Api(project)
    before = api.run_overview()
    names = [s["name"] for s in before["stations"]]
    assert "tool" not in names and {"agy", "opencode", "claude", "gemini2"} == set(names)
    assert all(s["roles"] in ([], ["scout"]) and not s["running"] and s["last"] is None for s in before["stations"])
    assert len(before["activity"]) == 24 and sum(b["calls"] for b in before["activity"]) == 0 and before["tiers"] == {}
    import time
    mark = time.time()
    authored(project)
    out = cycle.run_cycle(project, "job", "agy", verify=FAIL, factory=Agents().factory(project))
    assert out["status"] == "verify_failed"
    o = api.run_overview(mark)
    st = {s["name"]: s for s in o["stations"]}
    assert "author" in st["agy"]["roles"] and "reviewer" in st["opencode"]["roles"] and st["opencode"]["family"] == "opencode"
    assert st["opencode"]["calls"] == 1 and st["opencode"]["last"]["status"] == "ok" and (st["opencode"]["caught"], st["opencode"]["reviewed_failing"]) == (0, 1)
    assert o["activity"][-1]["calls"] == 1 and o["tiers"] == {"free": 1}
    assert (o["shift"]["failed"], o["shift"]["landed"], o["shift"]["calls"], o["shift"]["paid_calls"], o["shift"]["needs_you"]) == (1, 0, 1, 0, 1)
    assert api.run_overview(time.time() + 60)["shift"]["calls"] == 0
