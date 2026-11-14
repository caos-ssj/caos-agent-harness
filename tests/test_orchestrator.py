"""Multi-agent orchestration, parallel dispatch, the agy CLI, the board's new columns and the live event streams."""
import json
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from caos_harness import app, orchestrator, providers
from caos_harness.board.core import Board
from caos_harness.web import server
from caos_harness.web.events import EventBus
from caos_harness.web.server import Api, make_handler

AGENTS = '''
[agents.claude]
command = ["claude", "-p"]
[agents.opencode]
command = ["opencode", "run", "-m", "opencode/glm-5.3-flash-free"]
[agents.agy]
command = ["agy", "--mode", "accept-edits", "--output-format", "text", "-p", "{prompt}"]
[agents.qwen]
command = ["ollama", "run", "qwen2.5:7b"]
[agents.cat]
command = ["cat"]
'''


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("CAOS_HARNESS_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(providers.shutil, "which", lambda b: "/usr/bin/" + b)
    app.init(tmp_path)
    with open(tmp_path / "harness.toml", "a") as f:
        f.write(AGENTS)
    return app.load(tmp_path / "harness.toml")


class Fake:
    """A runner that stands in for every agent: records each call, can sleep, and answers by agent."""
    def __init__(self, plan=None, delay=0.0, fail=()):
        self.calls, self.plan, self.delay, self.fail = [], plan, delay, set(fail)
        self.active, self.peak, self.by_agent, self.lock = 0, 0, {}, threading.Lock()

    def agent_of(self, cmd):
        return "agy" if cmd[0] == "agy" else cmd[0] if cmd[0] != "ollama" else "qwen"

    def __call__(self, cmd, input="", **kw):
        who = self.agent_of(cmd)
        prompt = input or next((c for c in cmd if len(c) > 40), "")
        with self.lock:
            self.calls.append({"agent": who, "cmd": list(cmd), "input": input, "cwd": kw.get("cwd"), "prompt": prompt})
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.by_agent[who] = self.by_agent.get(who, 0) + 1
            n = self.by_agent[who]
        try:
            time.sleep(self.delay)
            if who in self.fail:
                return subprocess.CompletedProcess(cmd, 1, "", "boom")
            if "Plan only" in prompt:
                return subprocess.CompletedProcess(cmd, 0, self.plan if self.plan is not None else "not json at all", "")
            if "write the final synthesis" in prompt:
                return subprocess.CompletedProcess(cmd, 0, "SYNTHESIS: all criteria checked", "")
            return subprocess.CompletedProcess(cmd, 0, f"{who} delivered #{n}", "")
        finally:
            with self.lock:
                self.active -= 1


def plan_json(subs, summary="split it"):
    return json.dumps({"summary": summary, "recommended_orchestrator": "", "subtasks": subs})


def sub(i, agent, mode="readonly", **kw):
    return {"id": f"s{i}", "title": f"part {i}", "agent": agent, "mode": mode, "skill": None, "task": f"do part {i} of the work in a precise way",
            "criteria": f"criterion {i}", **kw}


def factory(project, fake):
    return lambda cwd=None, override=None: app.CommandDispatcher(project, fake, cwd=cwd, override=override)


def git_repo(root: Path):
    g = lambda *a: subprocess.run(["git", "-c", "user.email=t@example.test", "-c", "user.name=t", *a], cwd=root, capture_output=True, check=True)
    g("init", "-q", "-b", "main")
    (root / "README.md").write_text("# demo\n")
    (root / ".gitignore").write_text(".harness/\n")
    g("add", "-A")
    g("commit", "-q", "-m", "init")


# ── the agy CLI and the models of a CLI ──

def test_agy_is_a_known_cli_that_takes_the_prompt_as_an_argument(project):
    c = providers.CLIS["agy"]
    assert c["command"] == ["agy", "--mode", "accept-edits", "--output-format", "text", "-p", "{prompt}"] and "gemini-4-argon-high" in c["models"]
    info = {x["id"]: x for x in providers.detect_clis()}
    assert info["agy"]["installed"] and info["agy"]["orchestrator_capable"] and "claude-opus-5-5-high" in info["agy"]["models"]
    assert info["opencode"]["orchestrator_capable"] and info["opencode"]["models"] == providers.CLIS["opencode"]["free_models"]


def test_cli_command_validates_the_model_for_every_cli_that_takes_one():
    assert providers.cli_command("agy", "gemini-4-argon-high") == ["agy", "--mode", "accept-edits", "--output-format", "text", "--model", "gemini-4-argon-high", "-p", "{prompt}"]
    assert providers.cli_command("claude", "opus") == ["claude", "--model", "opus", "-p"]
    assert providers.cli_command("codex", "gpt-x") == ["codex", "exec", "-m", "gpt-x", "-"]
    assert providers.cli_command("opencode", "opencode/beam-free") == ["opencode", "run", "-m", "opencode/beam-free"]
    assert providers.cli_command("agy") == providers.CLIS["agy"]["command"]
    for cid in ("agy", "claude", "codex", "opencode"):
        with pytest.raises(ValueError):
            providers.cli_command(cid, "bad model; rm -rf /")


def test_the_prompt_placeholder_is_one_argument_and_never_goes_through_a_shell(project):
    seen = {}

    def runner(cmd, input, **kw):
        seen.update(cmd=cmd, input=input, shell=kw.get("shell"))
        return subprocess.CompletedProcess(cmd, 0, "ok\n", "")

    tid = app.add_task(project, "list files; rm -rf / && echo $HOME `id`", queue="agy")[0]
    app.run_pending(project, dispatcher=app.CommandDispatcher(project, runner))
    prompt = "list files; rm -rf / && echo $HOME `id`"
    assert seen["cmd"][-2:] == ["-p", prompt] and seen["cmd"].count(prompt) == 1 and seen["input"] == "" and not seen["shell"]
    assert project.board.get(tid)["result"] == "ok"
    seen.clear()                                                        # a CLI that reads stdin keeps getting the task there
    app.run_task(project, app.add_task(project, "read me", queue="claude")[0], app.CommandDispatcher(project, runner))
    assert seen["cmd"] == ["claude", "-p"] and seen["input"] == "read me"


def test_a_task_too_long_for_one_argument_is_refused_not_truncated(project):
    ran = []
    t = app.add_task(project, "x" * 120_000, queue="agy")[0]
    res = app.run_pending(project, dispatcher=app.CommandDispatcher(project, lambda *a, **k: ran.append(1)))
    assert not ran and not res[0]["ok"] and "too long" in res[0]["reason"] and project.board.get(t)["status"] == "pending"


def test_agy_and_opencode_are_agents_of_this_repositorys_own_harness_toml():
    p = app.load(Path(__file__).resolve().parent.parent / "harness.toml")
    assert p.agents["agy"].command[-2:] == ("-p", "{prompt}") and p.agents["opencode"].command[:3] == ("opencode", "run", "-m")
    # the team this repository is worked with: every CLI names its model, so none falls back to an account default
    assert p.agents["opencode"].command[-1] == "opencode/deepseek-v4.1-flash-free" and p.agents["pickle"].command[-1] == "opencode/big-pickle"
    assert "--model" in p.agents["agy"].command
    for name in ("claude", "haiku"):
        cmd = p.agents[name].command
        assert cmd[0] == "claude" and cmd[cmd.index("--model") + 1] in ("sonnet", "haiku")
    assert orchestrator.landing_config(p)["verify"][0] == "{project}/.venv/bin/python"


# ── parallel run_pending ──

def test_distinct_agents_work_at_the_same_time_and_one_agent_never_overlaps_itself(project):
    fake = Fake(delay=0.3)
    for a, n in (("claude", 2), ("opencode", 2), ("agy", 1), ("qwen", 1)):
        for i in range(n):
            app.add_task(project, f"{a} task number {i} with a long enough text", queue=a)
    t0 = time.monotonic()
    res = app.run_pending(project, dispatcher=app.CommandDispatcher(project, fake))
    took = time.monotonic() - t0
    assert len(res) == 6 and all(r["ok"] for r in res)
    assert took < 6 * 0.3 * 0.7 and fake.peak >= 3                        # 6 sleeps of 0.3 s in far less than 1.8 s: they overlapped
    assert [r["id"] for r in res] == sorted(r["id"] for r in res)         # reported in task order
    per_agent_overlap = Fake(delay=0.1)
    d = app.CommandDispatcher(project, per_agent_overlap)
    ts = [threading.Thread(target=d.send, args=("claude", "x")) for _ in range(3)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert per_agent_overlap.peak == 1                                    # three callers, one agent: strictly one after another


def test_is_idle_is_false_only_while_that_agent_runs(project):
    d = app.CommandDispatcher(project, Fake(delay=0.3))
    th = threading.Thread(target=d.send, args=("claude", "hello"))
    th.start(); time.sleep(0.1)
    assert d.is_idle("claude") is False and d.is_idle("opencode") is True and d.is_idle("agy") is True
    th.join()
    assert d.is_idle("claude") is True and d.is_idle("nobody") is False


def test_max_workers_one_and_foreign_dispatchers_stay_sequential(project):
    fake = Fake(delay=0.05)
    for a in ("claude", "opencode", "agy"):
        app.add_task(project, f"{a} task with a long enough text", queue=a)
    app.run_pending(project, dispatcher=app.CommandDispatcher(project, fake), max_workers=1)
    assert fake.peak == 1


# ── the board ──

def test_an_old_board_gains_the_new_columns_once_and_keeps_its_tasks(tmp_path):
    db = tmp_path / "old.db"
    c = sqlite3.connect(db)
    c.executescript("CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, created REAL NOT NULL, status TEXT NOT NULL DEFAULT 'pending', "
                    "queue TEXT, skill TEXT, agent TEXT, sent_at REAL, result TEXT, review TEXT, review_note TEXT, reviewed_at REAL);"
                    "INSERT INTO tasks (text, created, queue) VALUES ('an old task', 1.0, 'echo');")
    c.commit(); c.close()
    for _ in range(2):                                                    # opening twice must not fail on a duplicate column
        b = Board(db)
        cols = {r[1] for r in b.conn.execute("PRAGMA table_info(tasks)")}
        assert {"parent_id", "criteria", "worktree_key"} <= cols
        assert b.get(1)["text"] == "an old task" and b.get(1)["parent_id"] is None
        b.close()


def test_children_criteria_and_the_prompt_the_agent_receives():
    b = Board()
    sent = []

    class D:
        def is_idle(self, a): return True
        def send(self, a, t): sent.append(t)

    parent = b.add("goal", queue="x")
    c1 = b.add("write it", queue="x", skill="qa", parent_id=parent, criteria="tests pass", worktree_key="k1")
    c2 = b.add("plain", queue="x", skill="qa", parent_id=parent)
    c3 = b.add("only criteria", queue="x", criteria="it is checked")
    c4 = b.add("bare", queue="x")
    for t in (c1, c2, c3, c4):
        b.assign(t, "x", D())
    assert sent == ["Load the skill 'qa' before starting. Acceptance criteria: tests pass. Task: write it",
                    "Load the skill 'qa' before starting. Task: plain",                # identical to what it always was
                    "Acceptance criteria: it is checked. Task: only criteria",
                    "bare"]
    assert [r["id"] for r in b.children(parent)] == [c1, c2] and b.get(c1)["worktree_key"] == "k1" and b.get(parent)["parent_id"] is None


# ── who orchestrates ──

def test_orchestrator_candidates_are_the_ai_agents_and_the_suggestion_follows_the_goal(project):
    cands = orchestrator.available_orchestrators(project)
    assert [c["name"] for c in cands] == ["claude", "agy", "opencode", "qwen"] and all(c["capable"] for c in cands)   # `cat` is not an AI agent
    pick = lambda goal: orchestrator.suggest_orchestrator(goal, cands)
    assert pick("refactor the architecture of the auth module and the billing module")["name"] == "claude"
    assert pick("fix a quick typo, free and fast")["name"] == "opencode"
    assert pick("analyse these private files, fully offline")["name"] == "qwen"
    assert pick("do the thing") == {"name": "claude", "reason": "default", "alternatives": ["agy", "opencode", "qwen"]}
    only_local = [c for c in cands if c["name"] == "qwen"]
    assert orchestrator.suggest_orchestrator("refactor the architecture", only_local)["name"] == "qwen"   # never suggests what is not there
    assert orchestrator.suggest_orchestrator("x", [])["name"] is None
    opts = orchestrator.options(project, "x")
    assert opts["default_orchestrator"] == "claude" and "cat" in [w["name"] for w in opts["pool"]] and [i["id"] for i in opts["installable"]] == ["codex"]   # installed here, capable, not yet in harness.toml


def test_the_read_only_form_of_an_agent(project):
    ro = orchestrator.readonly_agent(project.agents["agy"])
    assert ro.command[ro.command.index("--mode") + 1] == "plan" and project.agents["agy"].command[2] == "accept-edits"   # the original is untouched
    assert orchestrator.readonly_agent(project.agents["claude"]).command == ("claude", "--permission-mode", "plan", "-p")
    assert orchestrator.readonly_agent(project.agents["opencode"]).command == project.agents["opencode"].command


# ── step 1: the plan ──

@pytest.mark.parametrize("wrap", [lambda j: j, lambda j: f"```json\n{j}\n```", lambda j: f"Here is the plan:\n{j}\nGood luck!", lambda j: f"```\n{j}\n```"])
def test_the_plan_is_parsed_from_bare_json_a_fence_or_prose(project, wrap):
    raw = plan_json([sub(1, "opencode"), sub(2, "agy", "isolated"), sub(3, "qwen")])
    fake = Fake(plan=wrap(raw))
    plan = orchestrator.plan_orchestration(project, "build the feature", "claude", ["opencode", "agy", "qwen"], factory(project, fake))
    assert plan["source"] == "orchestrator" and [s["agent"] for s in plan["subtasks"]] == ["opencode", "agy", "qwen"]
    assert [s["mode"] for s in plan["subtasks"]] == ["readonly", "isolated", "readonly"] and plan["subtasks"][0]["criteria"] == "criterion 1"
    call = fake.calls[0]
    assert call["agent"] == "claude" and call["cmd"] == ["claude", "--permission-mode", "plan", "-p"] and "opencode" in call["input"]   # asked read-only


def test_a_plan_that_cannot_be_read_or_an_orchestrator_that_fails_still_gives_an_editable_proposal(project):
    for fake in (Fake(plan="I think you should just start coding."), Fake(fail={"claude"}), Fake(plan="")):
        plan = orchestrator.plan_orchestration(project, "ship the release notes", "claude", ["opencode", "agy", "qwen"], factory(project, fake))
        assert plan["source"] == "fallback" and plan["note"] and len(plan["subtasks"]) == 3
        assert {s["agent"] for s in plan["subtasks"]} == {"opencode", "agy", "qwen"} and all(s["criteria"] and s["task"] for s in plan["subtasks"])
    one = orchestrator.plan_orchestration(project, "tiny", "claude", ["qwen"], factory(project, Fake(plan="no")))
    assert len(one["subtasks"]) == 1 and one["subtasks"][0]["agent"] == "qwen"


def test_a_model_plan_is_repaired_and_a_persons_plan_is_refused_with_a_reason(project):
    raw = {"orchestrator": "claude", "goal": "g", "subtasks": [sub(1, "ghost"), sub(1, "opencode", "weird"), {"id": "s3", "task": ""}, "junk"]}
    plan = orchestrator.normalize_plan(raw, project, ["opencode", "agy"], strict=False)
    assert [s["agent"] for s in plan["subtasks"]] == ["opencode", "opencode"] and {s["mode"] for s in plan["subtasks"]} == {"readonly"}
    assert len({s["id"] for s in plan["subtasks"]}) == 2                                     # the repeated id was replaced
    good = {"orchestrator": "claude", "goal": "g", "subtasks": [sub(1, "opencode")]}
    for bad, msg in (({"subtasks": [sub(1, "ghost")]}, "unknown agent"), ({"subtasks": [sub(1, "opencode", "weird")]}, "mode"),
                     ({"subtasks": [sub(1, "opencode", task="")]}, "needs a task"), ({"subtasks": [sub(1, "opencode", skill="astrology")]}, "unknown skill"),
                     ({"subtasks": []}, "at least one subtask"), ({"orchestrator": "nobody"}, "unknown orchestrator"), ({"goal": ""}, "needs a goal"),
                     ({"subtasks": [sub(i, "opencode") for i in range(9)]}, "at most")):
        with pytest.raises(app.ConfigError, match=msg):
            orchestrator.normalize_plan({**good, **bad}, project, strict=True)
    with pytest.raises(app.ConfigError, match="unknown agent"):
        orchestrator.normalize_plan({**good, "subtasks": [sub(1, "qwen")]}, project, ["opencode"], strict=True)   # outside the chosen pool


# ── step 3: execution ──

def run_plan(project, subs, fake, **kw):
    plan = orchestrator.normalize_plan({"orchestrator": kw.pop("orchestrator", "claude"), "goal": "build the feature end to end", "summary": "split", "subtasks": subs}, project, strict=True)
    run = orchestrator.OrchestrationRun(project, plan, factory=factory(project, fake), **kw)
    run.execute()
    return run


def test_subagents_run_in_parallel_in_their_modes_and_the_chosen_orchestrator_writes_the_synthesis(project):
    git_repo(project.root)
    fake = Fake(delay=0.3)
    run = run_plan(project, [sub(1, "opencode"), sub(2, "agy", "isolated"), sub(3, "qwen", "isolated"), sub(4, "claude")], fake)
    snap = run.snapshot()
    assert snap["status"] == "finishing" and snap["answer"] == "SYNTHESIS: all criteria checked" and not snap["error"]
    work = [c for c in fake.calls if "write the final synthesis" not in c["prompt"]]
    assert len(work) == 4 and fake.peak >= 3                                                  # the four sleeps of 0.3 s overlapped
    subs = {s["id"]: s for s in snap["orchestration"]["subtasks"]}
    assert all(s["state"] == "delivered" and s["duration_ms"] is not None for s in subs.values())
    root = project.root.resolve()
    by = {c["agent"]: c for c in work}
    assert Path(by["opencode"]["cwd"]).resolve() == root and Path(by["claude"]["cwd"]).resolve() == root       # read-only: in the project
    assert by["claude"]["cmd"][:3] == ["claude", "--permission-mode", "plan"]                                     # ...and in the agent's read-only form
    iso = {s: Path(subs[s]["worktree"]["path"]).resolve() for s in ("s2", "s3")}
    assert iso["s2"] != iso["s3"] and all(p.is_dir() and root in p.parents for p in iso.values())              # one worktree each
    assert Path(by["agy"]["cwd"]).resolve() == iso["s2"] and Path(by["qwen"]["cwd"]).resolve() == iso["s3"]
    assert by["agy"]["cmd"][2] == "accept-edits" and by["agy"]["input"] == ""                                      # an isolated agent keeps its edit mode
    b = project.board
    parent = snap["task_id"]
    kids = b.children(parent)
    assert [k["queue"] for k in kids] == ["opencode", "agy", "qwen", "claude"] and all(k["parent_id"] == parent for k in kids)
    assert [k["criteria"] for k in kids] == ["criterion 1", "criterion 2", "criterion 3", "criterion 4"]
    assert kids[1]["worktree_key"] == subs["s2"]["worktree"]["key"] and kids[0]["worktree_key"] is None
    assert all(k["status"] == "sent" and k["result"] for k in kids)
    assert b.get(parent)["result"] == "SYNTHESIS: all criteria checked" and b.get(parent)["status"] == "sent"
    synth = [c for c in fake.calls if "write the final synthesis" in c["prompt"]]
    assert len(synth) == 1 and synth[0]["agent"] == "claude"                                                   # the chosen orchestrator, once, at the end
    for s in subs.values():
        assert s["criteria"] in synth[0]["prompt"] and s["result"] in synth[0]["prompt"]                      # every criterion and every real delivery
    assert not project._reserved                                                                              # `run` may pick them up again after a redo


def test_the_orchestrator_can_be_any_agent_and_an_edited_plan_is_what_runs(project):
    fake = Fake()
    run = run_plan(project, [sub(1, "claude"), sub(2, "opencode", criteria="the edited criterion", task="the edited task, written by the person")], fake, orchestrator="agy")
    synth = [c for c in fake.calls if "write the final synthesis" in c["prompt"]][0]
    assert synth["agent"] == "agy" and synth["cmd"][2] == "plan" and "the edited criterion" in synth["cmd"][-1]
    assert any("the edited task, written by the person" in c["prompt"] for c in fake.calls if c["agent"] == "opencode")
    assert run.snapshot()["answer"].startswith("SYNTHESIS")


def test_an_isolated_subtask_without_a_git_repository_degrades_to_read_only_and_says_so(project):
    fake = Fake()
    run = run_plan(project, [sub(1, "agy", "isolated")], fake)
    s = run.snapshot()["orchestration"]["subtasks"][0]
    assert s["mode"] == "readonly" and "no isolated worktree" in s["note"] and s["worktree"] is None and s["state"] == "delivered"
    call = [c for c in fake.calls if c["agent"] == "agy" and "Read-only: inspect" in c["prompt"]][0]
    assert call["cmd"][2] == "plan"                                                                            # it could not edit: it was asked in plan mode


def test_a_failed_subagent_is_reported_and_the_rest_still_get_a_synthesis(project):
    run = run_plan(project, [sub(1, "opencode"), sub(2, "qwen")], Fake(fail={"qwen"}))
    snap = run.snapshot()
    states = {s["agent"]: s for s in snap["orchestration"]["subtasks"]}
    assert states["qwen"]["state"] == "failed" and "dispatch_failed" in states["qwen"]["error"] and states["opencode"]["state"] == "delivered"
    assert snap["answer"] == "SYNTHESIS: all criteria checked" and not snap["error"]
    allfail = run_plan(project, [sub(1, "qwen")], Fake(fail={"qwen"}))
    assert allfail.snapshot()["error"] == "no subagent delivered" and "0/1" in allfail.snapshot()["answer"]


def test_when_the_orchestrator_cannot_synthesise_the_harness_writes_one_from_the_deliveries(project):
    class Mute(Fake):
        def __call__(self, cmd, input="", **kw):
            if "write the final synthesis" in (input or ""):
                return subprocess.CompletedProcess(cmd, 1, "", "down")
            return super().__call__(cmd, input, **kw)
    run = run_plan(project, [sub(1, "opencode")], Mute())
    ans = run.snapshot()["answer"]
    assert "written by the harness" in ans and "opencode delivered" in ans and "criterion 1" in ans


def test_cancelling_stops_what_has_not_started_and_skips_the_synthesis(project):
    fake = Fake(delay=0.3)
    plan = orchestrator.normalize_plan({"orchestrator": "claude", "goal": "a long job split in parts", "subtasks": [sub(1, "opencode"), sub(2, "opencode"), sub(3, "agy")]}, project, strict=True)
    run = orchestrator.OrchestrationRun(project, plan, factory=factory(project, fake))
    th = threading.Thread(target=run.execute)
    th.start(); time.sleep(0.15)
    run.cancel()
    th.join(timeout=10)
    snap = run.snapshot()
    assert snap["status"] == "stopped" and snap["cancelled"]
    states = [s["state"] for s in snap["orchestration"]["subtasks"]]
    assert states[1] == "cancelled" and not [c for c in fake.calls if "write the final synthesis" in c["prompt"]]


# ── the server ──

@pytest.fixture
def api(project):
    a = Api(project)
    a.orch_factory = None
    return a


def wait_for(cond, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_the_api_plans_then_launches_the_plan_the_person_edited(api, project):
    fake = Fake(plan=plan_json([sub(1, "opencode"), sub(2, "qwen")]))
    api.orch_factory = factory(project, fake)
    opts = api.orchestrate_options("refactor the architecture")
    assert opts["suggested"]["name"] == "claude" and "claude" in [o["name"] for o in opts["orchestrators"]]
    plan = api.orchestrate_plan({"goal": "build the feature end to end", "orchestrator": "agy", "pool": ["opencode", "qwen"]})
    assert plan["orchestrator"] == "agy" and [s["agent"] for s in plan["subtasks"]] == ["opencode", "qwen"]
    plan["orchestrator"] = "opencode"                                                    # the person changes the orchestrator...
    plan["subtasks"][1]["agent"] = "opencode"                                            # ...a subtask's agent...
    plan["subtasks"][0]["criteria"] = "must show the failing test first"                 # ...a criterion...
    plan["subtasks"][0]["mode"] = "readonly"
    plan["subtasks"].append(sub(3, "agy", task="a third subtask the person added to the plan"))
    plan["subtasks"] = [s for s in plan["subtasks"] if s["id"] != "s2"]                  # ...and removes one
    sid = api.session_create({})["id"]
    out = api.orchestrate_launch({"session_id": sid, "plan": plan})
    run = api.runs[out["run_id"]]
    assert wait_for(lambda: run.snapshot()["status"] in server.TERMINAL_RUN)
    snap = api.run_detail(out["run_id"])
    assert snap["status"] == "completed" and snap["target_kind"] == "orchestrate" and snap["target"] == "opencode"
    assert [s["agent"] for s in snap["orchestration"]["subtasks"]] == ["opencode", "agy"]
    assert "must show the failing test first" in [c for c in fake.calls if c["agent"] == "opencode"][0]["prompt"]
    assert [c["agent"] for c in fake.calls if "write the final synthesis" in c["prompt"]] == ["opencode"]
    s = api.session_get(sid)
    assert [m["role"] for m in s["messages"]] == ["user", "assistant"] and s["messages"][1]["orchestration"]["subtasks"][0]["state"] == "delivered"
    assert s["messages"][1]["task_id"] == snap["task_id"] and s["active_run"] is None
    t = api.task(snap["task_id"])
    assert t["parent_id"] is None and api.task(snap["orchestration"]["subtasks"][0]["task_id"])["parent_id"] == snap["task_id"]
    assert api.task(snap["orchestration"]["subtasks"][0]["task_id"])["criteria"] == "must show the failing test first"


def test_the_api_refuses_a_bad_plan_with_a_reason_and_can_plan_and_launch_in_one_step(api, project):
    sid = api.session_create({})["id"]
    for body in ({"session_id": sid}, {"session_id": sid, "plan": {"orchestrator": "claude", "goal": "g", "subtasks": [sub(1, "ghost")]}},
                 {"session_id": "nope", "plan": {"orchestrator": "claude", "goal": "g", "subtasks": [sub(1, "opencode")]}}):
        with pytest.raises(app.ConfigError):
            api.orchestrate_launch(body)
    with pytest.raises(app.ConfigError):
        api.orchestrate_plan({"goal": "  "})
    with pytest.raises(app.ConfigError, match="pool"):
        api.orchestrate_plan({"goal": "x y z", "orchestrator": "claude", "pool": "opencode"})
    api.orch_factory = factory(project, Fake(plan=plan_json([sub(1, "opencode")])))
    out = api.orchestrate_plan({"goal": "do it all at once please", "orchestrator": "claude", "pool": ["opencode"], "session_id": sid, "auto_execute": True})
    assert wait_for(lambda: api.runs[out["run_id"]].snapshot()["status"] in server.TERMINAL_RUN)
    with pytest.raises(app.ConfigError, match="decision"):
        api.run_decision(out["run_id"], {"approve": True, "step": 0})


def test_orchestrated_tasks_are_not_picked_up_by_a_run_while_the_orchestration_owns_them(api, project):
    fake = Fake(delay=0.4, plan=plan_json([sub(1, "opencode"), sub(2, "opencode")]))
    api.orch_factory = factory(project, fake)
    plan = api.orchestrate_plan({"goal": "something to split in two", "orchestrator": "claude", "pool": ["opencode"]})
    sid = api.session_create({})["id"]
    out = api.orchestrate_launch({"session_id": sid, "plan": plan})
    assert wait_for(lambda: len(project.board.rows()) == 3)
    leaked = app.run_pending(project, dispatcher=app.CommandDispatcher(project, Fake()))
    assert project.board.pending("opencode") and leaked == []                            # the second one waits for its agent, and `run` did not steal it
    assert wait_for(lambda: api.runs[out["run_id"]].snapshot()["status"] in server.TERMINAL_RUN)


# ── event streams ──

def test_the_event_bus_wakes_a_waiter_at_once_and_times_out_quietly():
    bus = EventBus()
    v = bus.version("board")
    got = []
    th = threading.Thread(target=lambda: got.append((time.monotonic(), bus.wait("board", v, 5))))
    th.start(); time.sleep(0.1)
    t0 = time.monotonic(); bus.publish("board"); th.join(2)
    assert got and got[0][1] == v + 1 and got[0][0] - t0 < 0.2                          # woken by the publish, not by the timeout
    assert bus.wait("board", v + 1, 0.05) == v + 1 and bus.wait_any(bus.total(), 0.05) == bus.total()
    assert bus.versions("board", "runs") == {"board": 1, "runs": 0}


@pytest.fixture
def live(project, monkeypatch):
    monkeypatch.setattr(server, "HEARTBEAT", 0.3)
    api = Api(project)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(api))
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield api, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown(); srv.server_close()


def read_events(url, until, timeout=8):
    """Reads an event stream until `until(events)` is true; returns (headers, events, raw lines)."""
    req = urllib.request.Request(url)
    r = urllib.request.urlopen(req, timeout=timeout)
    events, raw, cur = [], [], {}
    end = time.time() + timeout
    while time.time() < end:
        line = r.readline().decode()
        if not line:
            break
        raw.append(line.rstrip("\n"))
        if line.startswith(":"):
            continue
        if line.strip() == "":
            if cur:
                events.append(cur); cur = {}
            if until(events):
                break
            continue
        k, _, v = line.rstrip("\n").partition(": ")
        cur[k] = json.loads(v) if k == "data" else v
    r.close()
    return r.headers, events, raw


def test_the_global_stream_announces_a_board_change_the_moment_it_happens(live):
    api, url = live
    seen = {}

    def reader():
        seen["res"] = read_events(url + "/api/events", lambda ev: len(ev) >= 2)
    th = threading.Thread(target=reader); th.start()
    time.sleep(0.3)
    t0 = time.monotonic()
    api.add({"text": "a new task from the page", "queue": "claude"})
    th.join(6)
    headers, events, _ = seen["res"]
    assert headers["Content-Type"].startswith("text/event-stream") and headers["Cache-Control"] == "no-cache" and "connect-src 'self'" in headers["Content-Security-Policy"]
    assert events[0]["event"] == "change" and events[1]["data"]["board"] > events[0]["data"]["board"]
    assert time.monotonic() - t0 < 3


def test_the_run_stream_follows_every_subagent_until_the_run_ends(live, project):
    api, url = live
    api.orch_factory = factory(project, Fake(delay=0.2, plan=plan_json([sub(1, "opencode"), sub(2, "agy")])))
    plan = api.orchestrate_plan({"goal": "something to split in two parts", "orchestrator": "claude", "pool": ["opencode", "agy"]})
    sid = api.session_create({})["id"]
    rid = api.orchestrate_launch({"session_id": sid, "plan": plan})["run_id"]
    _, events, _ = read_events(f"{url}/api/runs/{rid}/events", lambda ev: ev[-1]["data"]["status"] in server.TERMINAL_RUN)
    assert all(e["event"] == "run" for e in events) and events[-1]["data"]["status"] == "completed"
    phases = [e["data"]["orchestration"]["phase"] for e in events]
    assert "delegating" in phases and "synthesizing" in phases and phases[-1] == "done"
    running = [[s["state"] for s in e["data"]["orchestration"]["subtasks"]] for e in events]
    assert ["running", "running"] in running                                             # both subagents were seen working at the same time
    assert events[-1]["data"]["answer"].startswith("SYNTHESIS")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(f"{url}/api/runs/{'0' * 32}/events", timeout=3)
    assert e.value.code == 404


def test_a_stream_sends_a_heartbeat_when_nothing_changes_and_survives_a_client_that_leaves(live):
    api, url = live
    _, _, raw = read_events(url + "/api/events", lambda ev: False, timeout=1.2)
    assert any(l.startswith(": heartbeat") for l in raw)
    r = urllib.request.urlopen(url + "/api/events", timeout=3)
    r.close()                                                                            # leaves at once: the server must not log or crash
    api.add({"text": "still works afterwards", "queue": "claude"})
    assert json.loads(urllib.request.urlopen(url + "/api/state", timeout=3).read())["summary"]["tasks"] == 1


def test_options_and_plan_endpoints_over_http(live, project):
    api, url = live
    api.orch_factory = factory(project, Fake(plan=plan_json([sub(1, "opencode")])))
    opts = json.loads(urllib.request.urlopen(url + "/api/orchestrate/options?goal=quick%20typo", timeout=3).read())
    assert opts["suggested"]["name"] == "opencode" and opts["default_orchestrator"] == "claude"
    req = urllib.request.Request(url + "/api/orchestrate/plan", data=json.dumps({"goal": "plan it for me please", "orchestrator": "claude", "pool": ["opencode"]}).encode(),
                                 headers={"X-Harness": "1", "Content-Type": "application/json"})
    plan = json.loads(urllib.request.urlopen(req, timeout=5).read())
    assert plan["subtasks"][0]["agent"] == "opencode" and plan["source"] == "orchestrator"
    bad = urllib.request.Request(url + "/api/orchestrate/plan", data=b'{"goal":"x"}', headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(bad, timeout=3)
    assert e.value.code == 403                                                           # writes still need the header


def test_the_orchestrate_command_plans_and_runs_from_the_terminal(project, monkeypatch, capsys):
    import os
    from caos_harness import __main__ as cli
    fake = Fake(plan=plan_json([sub(1, "opencode"), sub(2, "qwen")]))
    monkeypatch.setattr(orchestrator, "_factory", lambda project, factory=None: (lambda cwd=None, override=None: app.CommandDispatcher(project, fake, cwd=cwd, override=override)))
    monkeypatch.setenv("NO_COLOR", "1")
    old = Path.cwd(); os.chdir(project.root)
    try:
        assert cli.main(["orchestrate", "--help"]) == 0 and "--plan-only" in capsys.readouterr().out
        assert cli.main(["orchestrate", "split this job", "--orchestrator", "claude", "--agents", "opencode,qwen", "--plan-only", "--json"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["plan"]["orchestrator"] == "claude" and [s["agent"] for s in out["plan"]["subtasks"]] == ["opencode", "qwen"] and project.board.rows() == []
        assert cli.main(["orchestrate", "split this job", "--orchestrator", "claude", "--agents", "opencode,qwen", "--json"]) == 0
        run = json.loads(capsys.readouterr().out)["run"]
        assert run["answer"].startswith("SYNTHESIS") and [s["state"] for s in run["orchestration"]["subtasks"]] == ["delivered", "delivered"]
        assert cli.main(["orchestrate", "x", "--orchestrator", "ghost"]) == 2
        assert cli.main(["orchestrate"]) == 2
    finally:
        os.chdir(old)


# ── what the server produces against what api.ts declares ──

API_TS = (Path(__file__).resolve().parent.parent / "web" / "src" / "api.ts").read_text(encoding="utf-8")


def ts_fields(name):
    import re
    m = re.search(rf"export interface {name}(?: extends (\w+))? \{{\n(.*?)\n\}}", API_TS, re.S)
    assert m, f"interface {name} not found in api.ts"
    return set(re.findall(r"^\s{2}(\w+)\??:", m.group(2), re.M)) | (ts_fields(m.group(1)) if m.group(1) else set())


def test_orchestration_payloads_have_no_field_the_page_does_not_declare(project):
    git_repo(project.root)
    run = run_plan(project, [sub(1, "opencode"), sub(2, "agy", "isolated")], Fake())
    snap = run.snapshot()
    assert set(snap) <= ts_fields("ExecutionRun"), set(snap) - ts_fields("ExecutionRun")
    assert set(snap["orchestration"]) == ts_fields("OrchestrationState")
    for s in snap["orchestration"]["subtasks"]:
        assert set(s) <= ts_fields("SubtaskRun") and set(ts_fields("SubtaskRun")) <= set(s), set(s) ^ ts_fields("SubtaskRun")
    assert snap["orchestration"]["phase"] in {"queued", "delegating", "synthesizing", "done", "stopped"}
    assert {s["state"] for s in snap["orchestration"]["subtasks"]} <= {"queued", "running", "delivered", "failed", "cancelled"}
    plan = orchestrator.plan_orchestration(project, "a goal to plan out", "claude", ["opencode"], factory(project, Fake(plan=plan_json([sub(1, "opencode")]))))
    plan["suggested"] = orchestrator.suggest_orchestrator("x", orchestrator.available_orchestrators(project))
    assert set(plan) <= ts_fields("OrchestrationPlan") and set(plan["subtasks"][0]) == ts_fields("OrchestrationSubtask")
    opts = orchestrator.options(project, "x")
    assert set(opts) == ts_fields("OrchestrateOptions")
    assert all(set(o) == ts_fields("OrchestratorInfo") for o in opts["pool"]) and set(opts["suggested"]) == ts_fields("OrchestratorSuggestion")
    assert set(providers.detect_clis()[0]) <= ts_fields("CliAgent")
    a = Api(project)
    sid = a.session_create({})["id"]
    assert set(a.session_get(sid)) <= ts_fields("SessionDetail")


def test_orchestrator_and_subtask_models_can_be_chosen_per_plan_and_override_cli_commands(project, api):
    assert providers.model_of(command=["opencode", "run", "-m", "opencode/glm-5.3-flash-free"]) == "opencode/glm-5.3-flash-free"
    assert providers.model_of(command=["ollama", "run", "qwen2.5:7b"]) == "qwen2.5:7b"
    assert providers.model_of(command=["claude", "--model", "opus", "-p"]) == "opus"

    fake = Fake(plan=plan_json([sub(1, "opencode"), sub(2, "qwen")]))
    api.orch_factory = factory(project, fake)
    plan = api.orchestrate_plan({
        "goal": "split endpoint work across models",
        "orchestrator": "claude",
        "orchestrator_model": "opus",
        "pool": ["opencode", "qwen"],
        "agent_models": {"opencode": "opencode/big-pickle", "qwen": "qwen3:8b"},
    })
    assert plan["orchestrator_model"] == "opus"
    assert [s["model"] for s in plan["subtasks"]] == ["opencode/big-pickle", "qwen3:8b"]

    plan["subtasks"][0]["model"] = "opencode/deepseek-v4.1-flash-free"
    sid = api.session_create({})["id"]
    out = api.orchestrate_launch({"session_id": sid, "plan": plan})
    run = api.runs[out["run_id"]]
    assert wait_for(lambda: run.snapshot()["status"] in server.TERMINAL_RUN)
    snap = api.run_detail(out["run_id"])
    assert snap["orchestration"]["orchestrator_model"] == "opus"
    assert snap["orchestration"]["subtasks"][0]["model"] == "opencode/deepseek-v4.1-flash-free"

    plan_call = next(c for c in fake.calls if "Plan only" in c["prompt"])
    synth_call = next(c for c in fake.calls if "write the final synthesis" in c["prompt"])
    open_call = next(c for c in fake.calls if c["agent"] == "opencode")
    qwen_call = next(c for c in fake.calls if c["agent"] == "qwen")
    assert providers.model_of(command=plan_call["cmd"]) == "opus" and "--permission-mode" in plan_call["cmd"]
    assert providers.model_of(command=synth_call["cmd"]) == "opus" and "--permission-mode" in synth_call["cmd"]
    assert open_call["cmd"] == ["opencode", "run", "-m", "opencode/deepseek-v4.1-flash-free"]
    assert qwen_call["cmd"] == ["ollama", "run", "qwen3:8b"]


def test_scratch_workspace_starts_with_no_orchestrators_and_accepts_local_ollama_agent(tmp_path, monkeypatch):
    monkeypatch.setenv("CAOS_HARNESS_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(providers.shutil, "which", lambda b: "/usr/bin/" + b)
    app.init(tmp_path)
    proj = app.load(tmp_path / "harness.toml")
    a = Api(proj)
    assert orchestrator.options(a.p, "")["orchestrators"] == []
    out = a.add_agent({"kind": "local", "model": "qwen2.5:7b"})
    assert out["name"] == "qwen2-5"
    opts = orchestrator.options(a.p, "")
    assert [o["name"] for o in opts["orchestrators"]] == ["qwen2-5"]
    assert opts["orchestrators"][0]["model"] == "qwen2.5:7b"
