"""Accounts: API keys come from the environment or the keyring and go nowhere else; subscriptions go through the official CLIs.
No test here touches the network: the transport is a double."""
import json
import sys
import types

import pytest
from caos_harness import app, providers
from caos_harness.web.server import Api

KEY = "sk-test-0123456789abcdefghijklmnopqrstuv"


class Fake:
    """A transport that records what it was asked and answers like the real APIs."""
    def __init__(self, status=200): self.calls, self.status = [], status
    def __call__(self, url, headers, body, timeout):
        self.calls.append((url, headers, body))
        if self.status != 200:
            return self.status, {"error": {"message": "bad things"}}
        if url.endswith("/models"):
            return 200, {"data": [{"id": "claude-x"}, {"id": "gpt-4o"}, {"id": "text-embedding-3"}, {"id": "whisper-1"}]}
        if "anthropic" in url:
            return 200, {"content": [{"type": "text", "text": "hello from claude"}]}
        return 200, {"choices": [{"message": {"content": "hello from gpt"}}]}


@pytest.fixture
def project(tmp_path, monkeypatch):
    for v in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MY_KEY"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setitem(sys.modules, "keyring", None)           # no keyring unless a test installs a fake one
    app.init(tmp_path)
    return app.load(tmp_path / "harness.toml")


def test_the_key_comes_from_the_named_variable_then_the_keyring_and_is_never_returned(project, monkeypatch):
    assert providers.key_for("anthropic") == (None, "none")
    monkeypatch.setenv("MY_KEY", KEY)
    assert providers.key_for("anthropic", "MY_KEY") == (KEY, "environment variable MY_KEY")
    monkeypatch.delenv("MY_KEY")
    monkeypatch.setitem(sys.modules, "keyring", types.SimpleNamespace(get_password=lambda svc, user: KEY if (svc, user) == ("caos-agent-harness", "openai") else None))
    assert providers.key_for("openai") == (KEY, "system keyring") and providers.key_for("anthropic")[0] is None
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    info = Api(project).providers_info()
    assert KEY not in json.dumps(info) and {p["id"]: p["status"] for p in info["providers"]}["anthropic"] == "key_present"


def test_a_call_uses_each_providers_own_format_and_headers(project):
    t = Fake()
    assert providers.ask("anthropic", "claude-x", "hi", KEY, transport=t) == "hello from claude"
    assert t.calls[-1][1]["x-api-key"] == KEY and t.calls[-1][1]["anthropic-version"] and t.calls[-1][2]["messages"][0]["content"] == "hi"
    assert providers.ask("openai", "gpt-4o", "hi", KEY, transport=t) == "hello from gpt"
    assert t.calls[-1][1]["Authorization"] == f"Bearer {KEY}"
    assert providers.models("openai", KEY, transport=t) == ["gpt-4o"]       # embeddings and audio models are not offered as agents


def test_errors_are_clear_and_never_contain_the_key(project, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    for status, words in ((401, "refused"), (429, "rate limit"), (404, "no such model")):
        out = providers.test("anthropic", transport=Fake(status))
        assert out["ok"] is False and words in out["message"] and KEY not in json.dumps(out)
    assert providers.test("openai")["message"].startswith("no key: set OPENAI_API_KEY")
    ok = providers.test("anthropic", transport=Fake())
    assert ok["ok"] and "claude-x" in ok["models"] and KEY not in json.dumps(ok)


def test_an_api_agent_runs_like_any_agent_and_the_key_stays_out_of_the_board_and_trace(project, monkeypatch):
    monkeypatch.setenv("MY_KEY", KEY)
    api = Api(project); api.transport = Fake()
    api.add_agent({"kind": "api", "provider": "anthropic", "model": "claude-x", "name": "claude-api"})
    (project.root / "harness.toml").write_text((project.root / "harness.toml").read_text().replace('provider = "anthropic"', 'provider = "anthropic"\nkey_env = "MY_KEY"'))
    project = app.load(project.root / "harness.toml")
    tid, queue, _ = app.add_task(project, "say hello", queue="claude-api")
    res = app.run_task(project, tid, app.CommandDispatcher(project, transport=Fake()))
    assert res["ok"] and res["result"] == "hello from claude"
    dump = json.dumps([dict(r) for r in project.board.conn.execute("select * from tasks")]) + json.dumps(project.board.trace.timeline(f"task:{tid}"))
    assert KEY not in dump
    failed = app.run_task(project, app.add_task(project, "again", queue="claude-api")[0], app.CommandDispatcher(project, transport=Fake(401)))
    assert not failed["ok"] and "refused" in failed["reason"] and KEY not in failed["reason"]


def test_without_a_key_the_agent_fails_with_what_to_set(project):
    Api(project).add_agent({"kind": "api", "provider": "openai", "model": "gpt-4o", "name": "gpt"})
    project = app.load(project.root / "harness.toml")
    res = app.run_task(project, app.add_task(project, "x", queue="gpt")[0], app.CommandDispatcher(project, transport=Fake()))
    assert not res["ok"] and "OPENAI_API_KEY" in res["reason"]


def test_harness_toml_refuses_a_key_and_a_bad_variable_name(tmp_path):
    for bad, msg in (('provider = "openai"\nmodel = "gpt-4o"\napi_key = "' + KEY + '"', "keys are not stored"),
                     ('provider = "openai"\nmodel = "gpt-4o"\nkey_env = "' + KEY + '"', "environment variable name"),
                     ('provider = "other"\nmodel = "m"', "must be one of")):
        (tmp_path / "harness.toml").write_text("[agents.x]\n" + bad + "\n")
        with pytest.raises(app.ConfigError, match=msg):
            app.load(tmp_path / "harness.toml")


def test_the_dashboard_adds_agents_from_fixed_templates_and_restores_the_file_on_failure(project, monkeypatch):
    api = Api(project)
    monkeypatch.setattr(providers.shutil, "which", lambda b: "/usr/bin/" + b if b == "claude" else None)
    clis = {c["id"]: c for c in api.providers_info()["clis"]}
    assert clis["claude"]["installed"] and not clis["codex"]["installed"] and "/usr/bin" not in json.dumps(clis)      # only names, never executable paths
    out = api.add_agent({"kind": "cli", "id": "claude"})
    assert out["name"] == "claude" and project.agents["claude"].command == ("claude", "-p") and {c["id"]: c for c in api.providers_info()["clis"]}["claude"]["added"]
    with pytest.raises(app.ConfigError, match="not installed"):
        api.add_agent({"kind": "cli", "id": "codex"})
    with pytest.raises(app.ConfigError, match="taken"):
        api.add_agent({"kind": "cli", "id": "claude"})
    before = (project.root / "harness.toml").read_text()
    for bad in ({"kind": "api", "provider": "anthropic", "model": "bad model!"}, {"kind": "api", "provider": "nope", "model": "m"}, {"kind": "x"}, {"kind": "api", "provider": "openai", "model": "m", "name": "person"}):
        with pytest.raises(app.ConfigError):
            api.add_agent(bad)
    assert (project.root / "harness.toml").read_text() == before


def test_providers_info_surfaces_invalid_key_errors_and_state_exposes_api_model(project, monkeypatch):
    api = Api(project)
    api.add_agent({"kind": "api", "provider": "anthropic", "model": "claude-x", "name": "claude-api"})
    api = Api(app.load(project.root / "harness.toml"))
    ag = next(a for a in api.state()["agents"] if a["name"] == "claude-api")
    assert ag["provider"] == "anthropic" and ag["model"] == "claude-x"

    def bad_key(pid):
        if pid == "anthropic":
            raise providers.ProviderError("keyring locked")
        return None, "missing"

    monkeypatch.setattr(providers, "key_for", bad_key)
    by_id = {p["id"]: p for p in api.providers_info()["providers"]}
    assert by_id["anthropic"]["status"] == "invalid_key"
    assert by_id["anthropic"]["key_error"] == "keyring locked"
