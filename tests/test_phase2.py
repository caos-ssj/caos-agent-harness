"""Phase 2 backend: free-tier providers, the regress verdict, worktree tidying, the activity feed and the read-only global board."""
import json
import os
import subprocess
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from caos_harness import activity, app, metrics, providers, workspaces, worktrees
from caos_harness.validation import regress
from caos_harness.web.server import Api, make_handler


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv("CAOS_HARNESS_HOME", str(tmp_path / ".home"))
    for v in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY", "NVIDIA_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    root = tmp_path / "work"
    root.mkdir()
    app.init(root)
    return app.load(root / "harness.toml")


# ─ free tiers ─

def test_presets_carry_the_updated_defaults_and_the_new_nvidia_gateway():
    P = providers.PRESETS
    assert P["openrouter"]["default_model"] == "openrouter/free" and P["gemini"]["default_model"] == "gemini-3.8-flash" and P["groq"]["default_model"] == "openai/gpt-oss-120b"
    n = P["nvidia"]
    assert (n["name"], n["env"], n["kind"], n["base_url"]) == ("NVIDIA NIM", "NVIDIA_API_KEY", "openai", "https://integrate.api.nvidia.com/v1")
    assert n["default_model"] in n["free_models"] and n["url"].endswith("/chat/completions") and n["models"].endswith("/models")
    for pid in ("openrouter", "gemini", "groq", "nvidia"):
        assert P[pid]["free_models"] and P[pid]["tier_hint"] and P[pid]["default_model"] in P[pid]["free_models"]
    assert "nvidia" in providers.API and providers.ENV_VAR.fullmatch(n["env"])


def test_a_long_catalogue_never_cuts_the_free_models_off():
    ids = [f"a-vendor/model-{i:03d}" for i in range(460)] + ["zz/late-model:free", "openrouter/free", "google/gemma-4-31b-it:free"]
    out = providers.models("openrouter", "sk-or-0123456789abcdef", transport=lambda *a, **k: (200, {"data": [{"id": i} for i in ids]}))
    assert len(out) == 120 and out[:3] == ["google/gemma-4-31b-it:free", "openrouter/free", "zz/late-model:free"]
    assert out[3] == "a-vendor/model-000"


def test_the_router_knows_nvidia(proj, monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-0123456789abcdef")
    for intent in ("rapido", "codigo", "razonar"):
        assert providers.resolve_intent(intent, root=proj.root, local_models=[], profile="cloud-max")["provider"] == "nvidia"
    assert providers.resolve_intent("codigo", root=proj.root, local_models=[])["provider"] == "nvidia"


def test_opencode_is_a_known_cli_whose_model_is_checked(monkeypatch, proj):
    assert providers.CLIS["opencode"]["command"] == ["opencode", "run", "-m", "opencode/glm-5.3-flash-free"] and len(providers.CLIS["opencode"]["free_models"]) == 4
    assert providers.cli_command("opencode", "opencode/beam-free") == ["opencode", "run", "-m", "opencode/beam-free"]
    assert providers.cli_command("claude", "opus") == ["claude", "--model", "opus", "-p"]          # claude takes a validated model too
    assert providers.cli_command("claude") == ["claude", "-p"]
    with pytest.raises(ValueError):
        providers.cli_command("opencode", "bad model; rm -rf /")
    monkeypatch.setattr(providers.shutil, "which", lambda b: "/usr/bin/" + b if b == "opencode" else None)
    api = Api(proj)
    info = {c["id"]: c for c in api.providers_info()["clis"]}
    assert info["opencode"]["installed"] and not info["opencode"]["added"] and "/usr/bin" not in json.dumps(info)
    out = api.add_agent({"kind": "cli", "id": "opencode", "model": "opencode/beam-free", "name": "free"})
    assert out["name"] == "free" and proj.agents["free"].command == ("opencode", "run", "-m", "opencode/beam-free")
    assert {c["id"]: c for c in api.providers_info()["clis"]}["opencode"]["added"]       # another model of the same binary still counts
    with pytest.raises(app.ConfigError, match="model name"):
        api.add_agent({"kind": "cli", "id": "opencode", "model": "no good", "name": "other"})


def test_the_providers_payload_exposes_free_models_and_hints(proj):
    items = {p["id"]: p for p in Api(proj).providers_info()["providers"]}
    assert items["nvidia"]["free_models"][0] == "deepseek-ai/deepseek-v4-flash" and "NVIDIA_API_KEY" in items["nvidia"]["tier_hint"]
    assert "free" in items["openrouter"]["tier_hint"].lower() and items["anthropic"]["free_models"] == []


# ─ the regress verdict ─

def test_regress_writes_the_verdict_the_dashboard_reads(tmp_path, monkeypatch):
    monkeypatch.setattr(regress, "ROOT", tmp_path)
    monkeypatch.setattr("sys.argv", ["regress", "--write"])
    assert regress.main() == 0
    monkeypatch.setattr("sys.argv", ["regress"])
    assert regress.main() == 0
    verdict = json.loads((tmp_path / "reports" / "validation" / "regress.json").read_text())
    assert verdict["ok"] is True and verdict["regressions"] == [] and metrics._repo_gates(tmp_path / "reports")["regress_status"] == "pass"
    base = tmp_path / "reports" / "validation" / "baseline.json"
    base.write_text(json.dumps({"precision": 1.0, "coverage": 1.0, "n": 74}))
    assert regress.main() == 1
    assert metrics._repo_gates(tmp_path / "reports")["regress_status"] == "check"


# ─ worktrees ─

def git(cwd, *a):
    return subprocess.run(["git", "-c", "user.email=t@example.test", "-c", "user.name=t", *a], cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture
def repo(proj):
    git(proj.root, "init", "-q", "-b", "main")
    (proj.root / "a.txt").write_text("one\n")
    git(proj.root, "add", "-A")
    git(proj.root, "commit", "-q", "-m", "init")
    return proj


def test_a_worktree_is_inspected_exported_as_a_patch_and_tidied_when_integrated(repo):
    root = repo.root
    wt = worktrees.ensure(root, "s1")
    clean = worktrees.inspect(root, "s1")
    assert clean["integrated"] is True and clean["ahead"] == 0 and clean["dirty"] == 0 and clean["base"] == "main"
    (Path(wt["path"]) / "a.txt").write_text("one\ntwo\n")
    (Path(wt["path"]) / "new.py").write_text("print(1)\n")
    (Path(wt["path"]) / ".env").write_text("OPENAI_API_KEY=sk-0123456789abcdefghijklmn\n")
    info = worktrees.inspect(root, "s1")
    assert info["integrated"] is False and info["dirty"] == 3 and {f["path"] for f in info["files"]} >= {"a.txt", "new.py"}
    pat = worktrees.export_patch(root, "s1")
    text = (root / pat["relative_path"]).read_text()
    assert pat["filename"].endswith(".patch") and "+two" in text and "new.py" in text and "sk-0123456789" not in text
    assert subprocess.run(["git", "apply", "--check", str(root / pat["relative_path"])], cwd=root, capture_output=True).returncode == 0
    assert worktrees.integrated_worktrees(root) == []
    assert (root / "a.txt").read_text() == "one\n"                                  # your branch was never touched
    git(Path(wt["path"]), "checkout", "-q", "--", "a.txt")
    (Path(wt["path"]) / "new.py").unlink()
    (Path(wt["path"]) / ".env").unlink()
    api = Api(repo)
    assert api.worktree_cleanup({})["removed"] == ["s1"] and not worktrees.active_worktrees(root)
    with pytest.raises(app.ConfigError, match="nothing to export"):
        worktrees.export_patch(root, None)


def test_cleanup_leaves_a_busy_or_changed_worktree_alone(repo):
    worktrees.ensure(repo.root, "keep")
    wt = worktrees.get(repo.root, "keep")
    (Path(wt["path"]) / "x.txt").write_text("work in progress\n")
    api = Api(repo)
    assert api.worktree_cleanup({})["removed"] == [] and worktrees.get(repo.root, "keep")
    assert "keep" not in api.workspace_status()["integrated_worktrees"]


# ─ activity and the global board ─

def test_the_feed_tells_what_happened_newest_first_and_agrees_with_the_board(proj):
    app.add_task(proj, "first", queue="person")
    t2, *_ = app.add_task(proj, "second", queue="echo")
    app.run_pending(proj)
    proj.board.review(t2, "redo", "fix the title")
    feed = activity.feed(proj)
    kinds = [e["kind"] for e in feed["events"]]
    assert set(kinds) <= set(activity.KINDS) and {"blocked", "intent", "delegated", "returned"} <= set(kinds)
    assert [e["ts"] for e in feed["events"]] == sorted((e["ts"] for e in feed["events"]), reverse=True)
    redo = next(e for e in feed["events"] if e["kind"] == "returned")
    assert redo["task_id"] == t2 and "fix the title" in redo["note"]
    assert feed["summary"]["with_person"] == 1 and feed["summary"]["needs_you"] == app.summary(proj)["needs_you"]


def test_the_global_board_reads_other_workspaces_without_writing_to_them(proj, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    app.init(other)
    op = app.load(other / "harness.toml")
    app.add_task(op, "other repo task", queue="person")
    empty = tmp_path / "fresh"
    empty.mkdir()
    app.init(empty)
    workspaces.remember(str(other))
    workspaces.remember(str(empty))
    app.add_task(proj, "mine", queue="person")
    db = op.db
    before = (db.stat().st_mtime_ns, db.stat().st_size)
    g = activity.consolidated(proj)
    assert g["readonly"] is True and g["workspaces"][0]["current"] and g["workspaces"][0]["tasks"][0]["text"] == "mine"
    names = {w["name"]: w for w in g["workspaces"]}
    assert names["other"]["tasks"][0]["text"] == "other repo task" and names["other"]["counts"]["needs_you"] == 1
    assert names["fresh"]["error"] == "no board yet" and names["fresh"]["tasks"] == []
    assert (db.stat().st_mtime_ns, db.stat().st_size) == before


def test_recent_sessions_span_workspaces_and_carry_no_message_text(proj, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    app.init(other)
    (other / ".harness").mkdir(exist_ok=True)
    (other / ".harness" / "sessions.json").write_text(json.dumps([{"id": "abc123", "title": "Elsewhere", "mode": "act", "updated_at": 5, "messages_count": 2, "secret_body": "never"}]))
    workspaces.remember(str(other))
    api = Api(proj)
    mine = api.session_create({"title": "Here", "mode": "plan"}) if hasattr(api, "session_create") else None
    g = activity.recent_sessions(proj)
    assert g["readonly"] is True and any(x["workspace"] == "other" and x["title"] == "Elsewhere" and not x["current"] for x in g["sessions"])
    assert "never" not in json.dumps(g) and (mine is None or any(x["current"] for x in g["sessions"]))


def test_the_new_endpoints_answer_over_http(repo):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Api(repo)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        get = lambda p: json.loads(urllib.request.urlopen(base + p).read())
        assert "events" in get("/api/activity") and get("/api/board/global")["readonly"] is True
        worktrees.ensure(repo.root, "h1")
        assert get("/api/workspace/worktree?key=h1")["key"] == "h1" and "h1" in get("/api/workspace/status")["integrated_worktrees"]
        req = urllib.request.Request(base + "/api/workspace/worktree/cleanup", b"{}", {"Content-Type": "application/json", "X-Harness": "1"})
        assert json.loads(urllib.request.urlopen(req).read())["removed"] == ["h1"]
        try:
            urllib.request.urlopen(base + "/api/workspace/worktree?key=ghost")
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.shutdown()
        srv.server_close()
