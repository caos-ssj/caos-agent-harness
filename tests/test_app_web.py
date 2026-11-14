import json
import subprocess
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
from caos_harness import app
from caos_harness.web.server import Api, make_handler


@pytest.fixture
def project(tmp_path):
    app.init(tmp_path)
    with open(tmp_path / "harness.toml", "a") as f:
        f.write('[agents.upper]\ncommand = ["tr", "a-z", "A-Z"]\nsystem = "llama3.2:3b+rules"\n[agents.broken]\ncommand = ["false"]\n[agents.slow]\ncommand = ["sleep", "5"]\ntimeout = 0.2\n')
    return app.load(tmp_path / "harness.toml")


def test_init_refuses_to_overwrite_and_config_errors_are_explained(tmp_path):
    app.init(tmp_path)
    with pytest.raises(app.ConfigError, match="already exists"):
        app.init(tmp_path)
    (tmp_path / "harness.toml").write_text('[agents.person]\ncommand = ["cat"]\n')
    with pytest.raises(app.ConfigError, match="human reviewer"):
        app.load(tmp_path / "harness.toml")
    (tmp_path / "harness.toml").write_text('[agents.a]\ncommand = "cat"\n')
    with pytest.raises(app.ConfigError, match="non-empty list"):
        app.load(tmp_path / "harness.toml")
    with pytest.raises(app.ConfigError, match="caos-harness init"):
        (tmp_path.parent / "empty").mkdir(exist_ok=True)
        app.find_config(tmp_path.parent / "empty")


def test_tier_routes_to_the_agent_that_runs_the_chosen_system_or_to_a_person(project):
    assert app.add_task(project, "classify", tier="medium")[1] == "upper"
    tid, queue, why = app.add_task(project, "approve the refund", tier="critical")
    assert queue == "person" and "0.95" in why
    tid2, queue2, why2 = app.add_task(project, "needs the big one", tier="high")
    assert queue2 == "person" and "no agent in harness.toml runs it" in why2
    kinds = [(e["source"], e["status"]) for e in project.board.trace.timeline(f"task:{tid}")]
    assert ("router", "human_review") in kinds
    for bad in ({"queue": "nobody"}, {"tier": "galactic"}, {"queue": "echo", "skill": "astrology"}, {}):
        with pytest.raises(app.ConfigError):
            app.add_task(project, "x task", **bad)


def test_run_delivers_requeues_failures_and_keeps_timeouts_visible(project):
    ok = app.add_task(project, "hello", queue="upper")[0]
    bad = app.add_task(project, "will fail", queue="broken")[0]
    slow = app.add_task(project, "too slow", queue="slow")[0]
    person = app.add_task(project, "for a human", queue="person")[0]
    res = {r["id"]: r for r in app.run_pending(project)}
    b = project.board
    assert res[ok]["ok"] and b.get(ok)["result"] == "HELLO" and b.get(ok)["status"] == "sent"
    assert res[bad]["reason"] == "dispatch_failed:RuntimeError" and b.get(bad)["status"] == "pending"
    assert res[slow]["reason"] == "dispatch_unconfirmed" and b.get(slow)["status"] == "sending"
    assert person not in res and b.get(person)["status"] == "pending"
    assert [r["id"] for r in app.run_pending(project, only="upper")] == []   # nothing is sent twice


def test_the_agent_receives_the_task_on_stdin(project):
    seen = {}

    def runner(cmd, input, **kw):
        seen["cmd"], seen["input"] = cmd, input
        return subprocess.CompletedProcess(cmd, 0, "done\n", "")

    t = app.add_task(project, "write it", queue="upper", skill="qa")[0]
    app.run_pending(project, dispatcher=app.CommandDispatcher(project, runner))
    assert seen["cmd"] == ["tr", "a-z", "A-Z"] and seen["input"] == "Load the skill 'qa' before starting. Task: write it"
    assert project.board.get(t)["result"] == "done"


def test_api_state_review_rules_and_router_table(project):
    api = Api(project)
    t = api.add({"text": "classify this", "tier": "medium"})["id"]
    p = api.add({"text": "approve the refund", "tier": "critical"})["id"]
    api.run(wait=True)
    s = api.state()
    by_id = {x["id"]: x for x in s["tasks"]}
    assert by_id[t]["state"] == "to_review" and {k: by_id[t]["router"][k] for k in ("tier", "system", "action")} == {"tier": "medium", "system": "llama3.2:3b+rules", "action": "route"} and "lower bound" in by_id[t]["router"]["reason"]
    assert by_id[p]["state"] == "person" and by_id[p]["router"]["action"] == "human_review"
    assert not s["running"] and {a["name"] for a in s["agents"]} == {"echo", "upper", "broken", "slow"}
    with pytest.raises(app.ConfigError, match="needs a note"):
        api.review(t, {"verdict": "redo"})
    with pytest.raises(app.ConfigError, match="verdict must be"):
        api.review(t, {"verdict": "great"})
    with pytest.raises(app.ConfigError, match="not in a state"):
        api.review(p, {"verdict": "ok"})
    assert api.review(t, {"verdict": "ok", "note": "checked"}) == {"id": t, "verdict": "ok"}
    detail = api.task(t)
    assert detail["result"] == "CLASSIFY THIS" and [e["source"] for e in detail["timeline"]][-1] == "review" and api.task(999) is None
    assert api.discard(p) == {"id": p}
    table = api.router_table()
    assert [r["tier"] for r in table["tiers"]] == ["low", "medium", "high", "critical"] and table["tiers"][1]["agent"] == "upper" and table["tiers"][3]["action"] == "human_review"


@pytest.fixture
def http(project):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Api(project)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(path, body=None, headers=None):
        req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None, {"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    yield call
    srv.shutdown()
    srv.server_close()


def test_http_writes_need_the_header_and_a_loopback_host(http):
    assert http("/api/state")[0] == 200
    assert http("/api/task", {"text": "x task", "queue": "echo"})[0] == 403                       # no X-Harness: a foreign page cannot post
    assert http("/api/task", {"text": "x task", "queue": "echo"}, {"X-Harness": "1", "Host": "evil.example"})[0] == 403
    code, out = http("/api/task", {"text": "x task", "queue": "echo"}, {"X-Harness": "1"})
    assert code == 201 and out["queue"] == "echo"
    assert http("/api/task", {"text": "", "queue": "echo"}, {"X-Harness": "1"}) == (409, {"error": "the task needs a text"})
    assert http(f"/api/task/{out['id']}/review", {"verdict": "ok"}, {"X-Harness": "1"})[0] == 409  # not delivered yet
    assert http("/api/task/999")[0] == 404 and http("/api/nope")[0] == 404
    assert http("/api/task", [1], {"X-Harness": "1"})[0] == 400


def test_dashboard_serves_static_app(project):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Api(project)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        with urllib.request.urlopen(base + "/") as r:
            assert r.status == 200
            assert "text/html" in r.headers.get("Content-Type", "")
            body = r.read().decode()
            assert "caos-agent-harness" in body
    finally:
        srv.shutdown()
        srv.server_close()


def test_sessions_and_providers_endpoints(http, monkeypatch):
    class Model:
        def __init__(self, model): pass
        def chat(self, messages, tools):
            return {"role": "assistant", "content": "Respuesta real de prueba"}
    monkeypatch.setattr("caos_harness.engines.workstation.OllamaChat", Model)
    # Providers GET
    code, pdata = http("/api/providers")
    assert code == 200
    assert "providers" in pdata and "active_failover" in pdata

    # Providers POST (custom provider)
    code, cprov = http(
        "/api/providers",
        {"name": "Local vLLM", "base_url": "http://127.0.0.1:8000/v1", "models": ["qwen2.5-coder:14b"]},
        {"X-Harness": "1"}
    )
    assert code == 200
    assert cprov["name"] == "Local vLLM"

    # Failover POST
    code, fover = http(
        "/api/providers/failover",
        {"fallback_model": "llama3.2:3b", "fallback_target": "ollama"},
        {"X-Harness": "1"}
    )
    assert code == 200
    assert fover["fallback_model"] == "llama3.2:3b"

    # Repositories GET
    code, repos = http("/api/repositories")
    assert code == 200
    assert isinstance(repos, list)

    # Sessions GET & POST
    code, slist = http("/api/sessions")
    assert code == 200
    assert isinstance(slist, list)

    code, newsess = http(
        "/api/sessions",
        {"title": "Test Sesion", "mode": "plan"},
        {"X-Harness": "1"}
    )
    assert code == 201
    sid = newsess["id"]

    # Sessions detail GET
    code, sdetail = http(f"/api/sessions/{sid}")
    assert code == 200
    assert sdetail["id"] == sid

    # Real execution endpoint returns a run id and saves the model response.
    import time
    code, started = http(
        f"/api/sessions/{sid}/messages",
        {"content": "Revisar arquitectura", "mode": "plan", "provider": "ollama", "model": "test"},
        {"X-Harness": "1"}
    )
    assert code == 201
    for _ in range(100):
        _, run = http(f"/api/runs/{started['run_id']}")
        if run["status"] in ("completed", "failed"):
            break
        time.sleep(.01)
    assert run["status"] == "completed"
    _, session = http(f"/api/sessions/{sid}")
    assert session["messages"][-1]["content"] == "Respuesta real de prueba"
    code, result = http(f"/api/sessions/{sid}/messages", {"content": "x", "provider": "anthropic"}, {"X-Harness": "1"})
    assert code == 409

    # Workspace status & convert task
    code, wstat = http("/api/workspace/status")
    assert code == 200
    assert "branch" in wstat and "dirty_files" in wstat

    code, ctask = http(
        "/api/workspace/convert_task",
        {"text": "Aprobar compuerta de seguridad", "tier": "medium"},
        {"X-Harness": "1"}
    )
    assert code == 201
    assert "id" in ctask

    # Delete session
    code, dres = http(f"/api/sessions/{sid}/delete", {}, {"X-Harness": "1"})
    assert code == 200
    assert dres["deleted"] is True



def test_shell_commands_are_off_until_switched_on_for_that_session(project):
    api = Api(project)
    a, b = api.session_create({"title": "one"})["id"], None
    msg = {"content": "list the files", "mode": "act", "model": "m", "provider": "ollama"}
    with pytest.raises(app.ConfigError, match="Commands are off for this session"):
        api.session_add_message(a, msg)
    assert api.session_get(a)["commands_enabled"] is False and api.session_get(a)["messages"] == []   # nothing was queued
    with pytest.raises(app.ConfigError, match="true or false"):
        api.session_commands(a, {"enabled": "yes"})
    assert api.session_commands(a, {"enabled": True}) == {"id": a, "commands_enabled": True}
    import time
    time.sleep(0.002)
    b = api.session_create({"title": "two"})["id"]
    assert api.session_get(b)["commands_enabled"] is False            # the switch belongs to one session
    with pytest.raises(app.ConfigError, match="Commands are off"):
        api.session_add_message(b, msg)
    assert api.session_commands(a, {"enabled": False})["commands_enabled"] is False
    assert Api(project).session_get(a)["commands_enabled"] is False   # and it does not survive a restart


def test_state_says_when_the_project_holds_sample_data(project):
    api = Api(project)
    assert api.state()["sample"] is False
    (project.root / ".harness" / "sample").write_text("sample")
    assert api.state()["sample"] is True


def test_the_dashboard_moves_a_pending_task_to_a_known_queue_only(project):
    api = Api(project)
    tid = api.add({"text": "x", "queue": "upper"})["id"]
    assert api.move(tid, {"queue": "person"}) == {"id": tid, "queue": "person"} and api.task(tid)["state"] == "person"
    with pytest.raises(app.ConfigError, match="unknown queue"):
        api.move(tid, {"queue": "nope"})
    with pytest.raises(app.ConfigError, match="only a pending task"):
        api.move(tid, {"queue": "person"})


def test_a_moved_task_no_longer_claims_the_router_chose_its_queue(project):
    api = Api(project)
    tid = api.add({"text": "x", "tier": "low"})["id"]
    first = next(t for t in api.state()["tasks"] if t["id"] == tid)
    if "router" not in first:
        pytest.skip("no measured system for this tier in this project")
    api.move(tid, {"queue": "upper" if first["queue"] == "person" else "person"})
    assert "router" not in next(t for t in api.state()["tasks"] if t["id"] == tid)
    assert any(e["source"] == "router" for e in api.task(tid)["timeline"])      # the original decision stays in the trace
    for bad in (["upper"], {"a": 1}, None, 5):
        with pytest.raises(app.ConfigError, match="unknown queue"):
            api.move(tid, {"queue": bad})


def test_workspace_status_marks_non_git_folder_explicitly(project, monkeypatch):
    import types
    from caos_harness.web import server as srv

    monkeypatch.setattr(srv.subprocess, "run", lambda *a, **kw: types.SimpleNamespace(returncode=128, stdout="", stderr="not a git repo"))
    st = Api(project).workspace_status()
    assert st["git_repo"] is False and st["branch"] is None and st["dirty_files"] == []
    assert all("provider" in a and "model" in a for a in Api(project).state()["agents"])


def test_a_return_carries_several_inline_notes_within_the_limits(project, http):
    from caos_harness.web import server
    api = Api(project)
    t = api.add({"text": "summarise", "queue": "upper"})["id"]
    api.run(wait=True)
    with pytest.raises(app.ConfigError, match="too long"):
        api.review(t, {"verdict": "redo", "note": "x" * (server.MAX_NOTE + 1)})
    with pytest.raises(app.ConfigError, match="too many notes"):
        api.review(t, {"verdict": "redo", "note": "\n".join(f"note {i}" for i in range(server.MAX_NOTE_LINES + 1))})
    with pytest.raises(app.ConfigError, match="must be text"):
        api.review(t, {"verdict": "redo", "note": ["a"]})
    with pytest.raises(app.ConfigError, match="needs a note"):
        api.review(t, {"verdict": "redo", "note": " \n\t\n "})
    assert api.task(t)["state"] == "to_review"                          # a refused note changes nothing
    note = "  general remark \r\n“SUMMARISE” →  not\x07 a summary\n\n“x”"
    assert api.review(t, {"verdict": "redo", "note": note}) == {"id": t, "verdict": "redo"}
    row = api.task(t)
    assert row["review_note"] == "general remark\n“SUMMARISE” → not a summary\n“x”" and row["status"] == "pending" and row["review"] == "redo"
    # the same contract over HTTP: 409 with the reason for a note over the limit
    t2 = api.add({"text": "again", "queue": "upper"})["id"]
    app.run_task(project, t2)
    code, out = http(f"/api/task/{t2}/review", {"verdict": "redo", "note": "y" * (server.MAX_NOTE + 1)}, {"X-Harness": "1"})
    assert code == 409 and "too long" in out["error"]
    assert http(f"/api/task/{t2}/review", {"verdict": "redo", "note": "“AGAIN” → lower case\n“x” → y"}, {"X-Harness": "1"})[0] == 200


def test_run_now_sends_one_task_and_leaves_the_rest_pending(project, http):
    api = Api(project)
    a, b = api.add({"text": "first", "queue": "upper"})["id"], api.add({"text": "second", "queue": "upper"})["id"]
    who = api.add({"text": "for a person", "queue": "person"})["id"]
    assert api.run_task(b, wait=True) == {"started": True, "id": b}
    assert api.task(b)["state"] == "to_review" and api.task(b)["result"] == "SECOND"
    assert api.task(a)["state"] == "pending" and api.state()["running_tasks"] == [] and api.last_run[0]["id"] == b
    with pytest.raises(app.ConfigError, match="already sent"):
        api.run_task(b)
    with pytest.raises(app.ConfigError, match="waits for a person"):
        api.run_task(who)
    h = {"X-Harness": "1"}
    assert http("/api/task/999/run", {}, h)[0] == 404
    assert http(f"/api/task/{b}/run", {}, h)[0] == 409 and http(f"/api/task/{who}/run", {}, h)[0] == 409
    assert http(f"/api/task/{a}/run", {})[0] == 403                     # the same guard as every write
    project._busy.add("upper")                                          # the agent is in the middle of something else
    code, out = http(f"/api/task/{a}/run", {}, h)
    assert code == 409 and "busy" in out["error"] and api.task(a)["state"] == "pending"
    project._busy.clear()
    assert http(f"/api/task/{a}/run", {}, h) == (202, {"started": True, "id": a})


def test_reorder_endpoint_keeps_a_task_inside_its_queue(project, http):
    api = Api(project)
    a, b, c = (api.add({"text": f"t{i}", "queue": "upper"})["id"] for i in range(3))
    other = api.add({"text": "elsewhere", "queue": "echo"})["id"]
    h = {"X-Harness": "1"}
    order = lambda: [t["id"] for t in sorted((t for t in api.state()["tasks"] if t["queue"] == "upper" and t["status"] == "pending"), key=lambda t: t["position"])]
    assert order() == [a, b, c]
    assert http(f"/api/task/{c}/reorder", {"before": a}, h) == (200, {"id": c, "before": a, "moved": True}) and order() == [c, a, b]
    assert http(f"/api/task/{c}/reorder", {"before": None}, h)[1]["moved"] is True and order() == [a, b, c]
    assert http(f"/api/task/{c}/reorder", {"before": None}, h)[1]["moved"] is False
    assert http("/api/task/999/reorder", {"before": a}, h)[0] == 404
    assert http(f"/api/task/{a}/reorder", {"before": other}, h)[0] == 409       # another queue
    assert http(f"/api/task/{a}/reorder", {"before": "2"}, h)[0] == 409 and http(f"/api/task/{a}/reorder", {"before": True}, h)[0] == 409
    app.run_task(project, a)
    assert http(f"/api/task/{a}/reorder", {"before": b}, h)[0] == 409 and http(f"/api/task/{b}/reorder", {"before": a}, h)[0] == 409   # sent: fixed
    assert [r["agent"] for r in app.run_pending(project, only="upper")] == ["upper", "upper"] and order() == []
    api.add({"text": "x1", "queue": "upper"}), api.add({"text": "x2", "queue": "upper"})
    x1, x2 = order()
    api.reorder(x2, {"before": x1})
    assert [r["id"] for r in app.run_pending(project, only="upper")] == [x2, x1]   # the run follows the new order


def test_effort_is_translated_only_where_the_tool_documents_it(tmp_path):
    from caos_harness import providers
    assert providers.with_effort(["claude", "-p"], "high") == ["claude", "--effort", "high", "-p"]
    assert providers.with_effort(["claude", "--model", "sonnet", "-p"], "low") == ["claude", "--effort", "low", "--model", "sonnet", "-p"]
    assert providers.with_effort(["codex", "exec", "-m", "gpt-5", "-"], "medium") == ["codex", "exec", "-c", "model_reasoning_effort=medium", "-m", "gpt-5", "-"]
    for cmd in (["opencode", "run", "-m", "opencode/x"], ["ollama", "run", "qwen2.5:7b"], ["cat"], ["agy", "-p", "{prompt}"], ["claude", "--effort", "max", "-p"]):
        assert providers.with_effort(cmd, "high") == cmd and providers.effort_support(cmd)[0] is False and providers.effort_support(cmd)[1]
    assert providers.with_effort(["claude", "-p"], None) == ["claude", "-p"] and providers.with_effort(["claude", "-p"], "extreme") == ["claude", "-p"]
    assert providers.effort_support((), "anthropic")[0] is False
    by_id = {c["id"]: c["effort"]["supported"] for c in providers.detect_clis()}
    assert by_id == {"claude": True, "codex": True, "opencode": False, "agy": False}

    app.init(tmp_path)
    cfg = tmp_path / "harness.toml"
    base = cfg.read_text()
    cfg.write_text(base + '[agents.think]\ncommand = ["claude", "-p"]\neffort = "high"\n')
    assert app.load(cfg).agents["think"].effort == "high" and app.load(cfg).agents["echo"].effort is None
    cfg.write_text(base + '[agents.think]\ncommand = ["claude", "-p"]\neffort = "max"\n')
    with pytest.raises(app.ConfigError, match="effort must be one of low, medium, high"):
        app.load(cfg)
    cfg.write_text(base + '[agents.local]\ncommand = ["ollama", "run", "x"]\neffort = "high"\n')
    with pytest.raises(app.ConfigError, match="effort cannot be set: Ollama"):
        app.load(cfg)


def test_effort_per_agent_and_per_task_reaches_the_command_that_runs(tmp_path):
    app.init(tmp_path)
    cfg = tmp_path / "harness.toml"
    cfg.write_text(cfg.read_text() + '[agents.think]\ncommand = ["claude", "-p"]\n# kept comment\n\n[agents.cx]\ncommand = ["codex", "exec", "-"]\n')
    p = app.load(cfg)
    api = Api(p)
    seen = []

    def runner(cmd, **kw):
        seen.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "done", "")

    api.task_dispatcher = app.CommandDispatcher(p, runner=runner)
    s = {a["name"]: a for a in api.state()["agents"]}
    assert s["think"]["effort"] is None and s["think"]["effort_support"]["supported"] and not s["echo"]["effort_support"]["supported"]
    # per agent: written into harness.toml, and nothing else in the file moves
    assert api.set_agent_effort({"name": "think", "effort": "high"}) == {"name": "think", "effort": "high"}
    text = cfg.read_text()
    assert 'command = ["claude", "-p"]\neffort = "high"\n# kept comment' in text and app.load(cfg).agents["think"].effort == "high"
    plain = api.add({"text": "plain", "queue": "think"})["id"]
    api.run_task(plain, wait=True)
    assert seen[-1] == ["claude", "--effort", "high", "-p"]
    # per task: wins over the agent's for that task only
    one = api.add({"text": "quick one", "queue": "think", "effort": "low"})["id"]
    assert api.task(one)["effort"] == "low"
    api.run_task(one, wait=True)
    assert seen[-1] == ["claude", "--effort", "low", "-p"] and p.agents["think"].effort == "high"
    cx = api.add({"text": "codex one", "queue": "cx", "effort": "medium"})["id"]
    app.run_pending(p, dispatcher=api.task_dispatcher)
    assert seen[-1] == ["codex", "exec", "-c", "model_reasoning_effort=medium", "-"] and api.task(cx)["state"] == "to_review"
    # cleared again: the line leaves the file
    assert api.set_agent_effort({"name": "think", "effort": ""}) == {"name": "think", "effort": None} and "effort" not in cfg.read_text()
    # refused, with the reason, where the tool takes none: never stored as a setting that does nothing
    with pytest.raises(app.ConfigError, match="echo cannot take an effort level"):
        api.set_agent_effort({"name": "echo", "effort": "high"})
    with pytest.raises(app.ConfigError, match="effort must be one of"):
        api.set_agent_effort({"name": "think", "effort": "max"})
    with pytest.raises(app.ConfigError, match="cannot take an effort level"):
        api.add({"text": "x", "queue": "echo", "effort": "high"})
    with pytest.raises(app.ConfigError, match="a person takes no effort"):
        api.add({"text": "x", "queue": "person", "effort": "high"})
    with pytest.raises(app.ConfigError, match="effort must be one of"):
        api.add({"text": "x", "queue": "think", "effort": "max"})
    assert cfg.read_text() == text.replace('effort = "high"\n', "")   # every refusal left the file as it was
