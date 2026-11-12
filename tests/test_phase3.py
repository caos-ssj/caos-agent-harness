"""Phase 3 backend: the metrics series, comparisons kept apart from real work, provider-aware demotion, skill cloning, the share preview."""
import json
import time

import pytest
from caos_harness import app, metrics, providers, skills
from caos_harness.web.server import Api


@pytest.fixture
def proj(tmp_path, monkeypatch):
    monkeypatch.setenv("CAOS_HARNESS_HOME", str(tmp_path / ".home"))
    for v in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY", "DEEPSEEK_API_KEY", "GROQ_API_KEY", "NVIDIA_API_KEY"):
        monkeypatch.delenv(v, raising=False)
    root = tmp_path / "work"
    root.mkdir()
    app.init(root)
    return app.load(root / "harness.toml")


def run(proj, n, **kw):
    for i in range(n):
        metrics.record_run(proj.root, kw.get("provider", "ollama"), kw.get("model", "qwen2.5:7b"), kw.get("latency", 100 + i), kw.get("ok", True), kind=kw.get("kind", "chat"))


# ─ series ─

def test_the_series_is_honest_below_five_runs_and_real_above(proj):
    api = Api(proj)
    run(proj, 4)
    s = api.metrics_series("project", "day")
    assert s["enough"] is False and s["points"] == [] and s["total_runs"] == 4 and s["min_runs"] == 5
    run(proj, 3, ok=False)
    s = api.metrics_series("project", "hour")
    assert s["enough"] is True and sum(p["runs"] for p in s["points"]) == 7
    assert s["points"][-1]["success_rate"] == round(4 / 7, 4) and s["points"][-1]["p50_ms"] is not None
    with pytest.raises(app.ConfigError, match="hour or day"):
        api.metrics_series("project", "week")


def test_hours_and_days_group_by_their_own_size(proj):
    run(proj, 6)
    day, hour = metrics.series(proj, "project", "day"), metrics.series(proj, "project", "hour")
    assert len(day["points"]) >= 1 and all(p["t"] % 86400 == 0 for p in day["points"]) and all(p["t"] % 3600 == 0 for p in hour["points"])
    assert metrics.series(proj, "global", "day")["scope"] == "global"


def test_comparisons_never_count_as_work(proj):
    run(proj, 5)
    run(proj, 6, kind="compare", model="gemma4:e2b", ok=False)
    snap = metrics.snapshot(proj)
    assert snap["kpis"]["runs_total"] == 5 and snap["kpis"]["run_success_rate"] == 1.0
    assert [m["model"] for m in snap["models"]] == ["qwen2.5:7b"]
    assert snap["compare"]["runs"] == 6 and snap["compare"]["models"][0]["model"] == "gemma4:e2b" and snap["compare"]["models"][0]["ok_rate"] == 0.0
    assert metrics.series(proj)["total_runs"] == 5


# ─ demotion carries the provider ─

def test_a_cloud_model_sharing_a_local_name_is_a_different_system(proj):
    run(proj, 2, provider="openrouter", model="qwen2.5:7b")
    run(proj, 2, provider="ollama", model="qwen2.5:7b")
    api = Api(proj)
    assert api.metrics_demote({"provider": "openrouter", "model": "qwen2.5:7b", "demoted": True})["key"] == "openrouter:qwen2.5:7b"
    rows = {m["provider"]: m for m in api.metrics_snapshot("project")["models"]}
    assert rows["openrouter"]["demoted"] is True and rows["ollama"]["demoted"] is False
    out = api.metrics_demote({"provider": "ollama", "model": "qwen2.5:7b"})
    assert out["key"] == "qwen2.5:7b"                                                            # the router's own name for a local model
    assert {m["provider"]: m["demoted"] for m in api.metrics_snapshot("project")["models"]} == {"openrouter": True, "ollama": True}
    api.metrics_demote({"provider": "openrouter", "model": "qwen2.5:7b", "demoted": False})
    assert {m["provider"]: m["demoted"] for m in api.metrics_snapshot("project")["models"]}["openrouter"] is False


# ─ comparing ─

class FakeChat:
    calls = []

    def __init__(self, provider, model, **kw):
        self.provider, self.model = provider, model
        FakeChat.calls.append((provider, model))

    def chat(self, messages, tools):
        if self.model == "bad":
            raise RuntimeError("boom")
        return {"content": '{"ok": true}' if self.provider == "ollama" else "plain words", "usage": {"prompt_tokens": 7, "completion_tokens": 3}}


def test_local_against_local_runs_directly_and_is_logged_as_a_comparison(proj, monkeypatch):
    monkeypatch.setattr("caos_harness.engines.llm.ProviderChat", FakeChat)
    FakeChat.calls = []
    api = Api(proj)
    out = api.providers_compare({"prompt": "say hi", "sides": [{"provider": "ollama", "model": "a:1b"}, {"provider": "ollama", "model": "bad"}]})
    left, right = out["results"]
    assert out["cloud"] is False and left["ok"] and left["json_ok"] and left["answer"] == '{"ok": true}' and left["prompt_tokens"] == 7
    assert right["ok"] is False and "boom" in right["error"] and len(FakeChat.calls) == 2
    assert api.metrics_snapshot("project")["kpis"]["runs_total"] == 0 and api.metrics_snapshot("project")["compare"]["runs"] == 2


def test_a_cloud_side_needs_an_explicit_confirmation_the_server_checks(proj, monkeypatch):
    monkeypatch.setattr("caos_harness.engines.llm.ProviderChat", FakeChat)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-0123456789abcdefghij")
    FakeChat.calls = []
    api = Api(proj)
    body = {"prompt": "hi", "sides": [{"provider": "ollama", "model": "a:1b"}, {"provider": "openai", "model": "gpt-4.1-mini"}]}
    with pytest.raises(app.ConfigError, match="cloud quota"):
        api.providers_compare(body)
    assert FakeChat.calls == []                                                                 # nothing was sent before the confirmation
    with pytest.raises(app.ConfigError, match="cloud quota"):
        api.providers_compare({**body, "confirm_cloud": "true"})                                # only a real true counts
    out = api.providers_compare({**body, "confirm_cloud": True})
    assert out["cloud"] is True and len(out["results"]) == 2 and len(FakeChat.calls) == 2


def test_a_comparison_is_validated(proj):
    api = Api(proj)
    for bad in ({"sides": []}, {"prompt": "x", "sides": [{"provider": "ollama", "model": "a"}]}, {"prompt": "", "sides": [{"provider": "ollama", "model": "a"}] * 2},
                {"prompt": "x" * 4001, "sides": [{"provider": "ollama", "model": "a"}] * 2}, {"prompt": "x", "sides": [{"provider": "ollama", "model": "bad model!"}, {"provider": "ollama", "model": "a"}]},
                {"prompt": "x", "sides": [{"provider": "nope", "model": "a", }, {"provider": "ollama", "model": "a"}], "confirm_cloud": True}):
        with pytest.raises(app.ConfigError):
            api.providers_compare(bad)


# ─ skills ─

def test_a_packaged_skill_is_cloned_into_the_project_and_then_edited(proj):
    api = Api(proj)
    packaged = skills.load_packaged()["coder"]
    out = api.skill_clone({"name": "coder"})
    assert out["local"] is True and out["name"] == "coder" and out["body"].strip() == packaged.body.strip() and out["category"] == packaged.category
    assert (proj.root / ".harness" / "skills" / "coder" / "SKILL.md").is_file()
    with pytest.raises(app.ConfigError, match="already has its own"):
        api.skill_clone({"name": "coder"})
    with pytest.raises(app.ConfigError, match="not a packaged skill"):
        api.skill_clone({"name": "no-such-skill"})
    saved = api.skill_save({"name": "coder", "description": "Reglas del proyecto para cambios de código", "body": "# Mine\n- paso 1", "category": "Código & Infra"})
    assert saved["local"] and "# Mine" in saved["body"]
    assert next(s for s in api.state()["skills"] if s["name"] == "coder")["local"] is True


# ─ the share preview, as the dashboard asks for it ─

@pytest.mark.parametrize("fmt", ["zip", "tar.gz", "dir"])
def test_the_share_preview_answers_for_each_format_and_option(proj, fmt):
    (proj.root / "a.py").write_text("x = 1\n")
    (proj.root / "notes.md").write_text("# n\n")
    api = Api(proj)
    full = api.share_preview({"format": fmt})
    assert full["format"] == fmt and {"a.py", "notes.md"} <= {i["path"] for i in full["included"]}
    no_docs = api.share_preview({"format": fmt, "include_docs": False})
    assert "notes.md" not in {i["path"] for i in no_docs["included"]} and "a.py" in {i["path"] for i in no_docs["included"]}
    assert api.share_preview({"format": fmt, "include_skills": False})["skills_included"] == []
    assert {c["id"] for c in full["sanitization"]} >= {"secret_files", "credentials", "private_paths", "harness_toml"}
    assert not (proj.root / ".harness" / "exports").exists()
