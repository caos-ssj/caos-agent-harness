import json
import stat
import subprocess
import threading
import zipfile
from pathlib import Path

from caos_harness import app, mcp_tools, metrics, providers, share, skills
from caos_harness.engines import llm, workstation
from caos_harness.web.server import Api


def test_save_key_env_local_and_masking(tmp_path):
    res = providers.save_key("openrouter", "sk-or-secret-example-value", storage="env_local", root=tmp_path)
    assert res["ok"] and ".harness/.env.local" in res["storage"]
    env_file = tmp_path / ".harness" / ".env.local"
    assert env_file.is_file()
    mode = stat.S_IMODE(env_file.stat().st_mode)
    assert mode == 0o600
    val, src = providers.key_for("openrouter", root=tmp_path)
    assert val == "sk-or-secret-example-value" and ".harness/.env.local" in src
    assert "example-value" not in res["masked"]


def test_ollama_hosts_and_intent_resolution_and_smoke(tmp_path, monkeypatch):
    hosts = providers.save_ollama_host("http://192.168.1.50:11434", label="Server LAN", root=tmp_path)
    assert any(h["url"] == "http://192.168.1.50:11434" for h in hosts)

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key-123456")

    def fake_transport(url, headers=None, data=None, timeout=15):
        if "/chat/completions" in url:
            return 200, {"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {"prompt_tokens": 9, "completion_tokens": 4}}
        return 200, {"data": [{"id": "anthropic/claude-sonnet-4"}]}

    smoke = providers.smoke_test("openrouter", "anthropic/claude-sonnet-4", root=tmp_path, transport=fake_transport)
    assert smoke["ok"] and smoke["json_ok"] and smoke["usage"]["prompt_tokens"] == 9

    resolved = providers.resolve_intent("codigo", root=tmp_path, local_models=["qwen2.5:7b"])
    assert resolved["intent"] == "codigo" and resolved["provider"] == "openrouter"
    providers.save_intent_map("codigo", "openrouter", "anthropic/claude-sonnet-4")
    pinned = providers.resolve_intent("codigo", root=tmp_path, local_models=["qwen2.5:7b"])
    assert pinned["pinned"] and pinned["provider"] == "openrouter" and pinned["model"] == "anthropic/claude-sonnet-4"


def test_provider_chat_failover_chain(monkeypatch):
    calls = []
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test-key-123456")

    def transport(url, headers=None, data=None, timeout=120):
        calls.append(url)
        if "anthropic" in url:
            raise providers.ProviderError("rate limited 429")
        return 200, {
            "choices": [{"message": {"content": "Recovered on fallback"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 5},
        }

    chat = llm.ProviderChat(
        provider="anthropic",
        model="claude-sonnet-4-20250514",
        key="sk-ant-test",
        failover_targets=[("openrouter", "openai/gpt-4o-mini")],
        transport=transport,
    )
    out = chat.chat([{"role": "user", "content": "hola"}], [])
    assert out["content"] == "Recovered on fallback"
    assert out["failover_used"] == "openrouter · openai/gpt-4o-mini"
    assert out["usage"]["completion_tokens"] == 5


def test_run_read_tools_plan_questions_and_act_trust(tmp_path):
    (tmp_path / "app.py").write_text("def greet():\n    return 'ok'\n", encoding="utf-8")

    class ScriptedPlanLLM:
        def chat(self, msgs, tools=None):
            return {
                "role": "assistant",
                "content": "Para planificar mejor:\n1. ¿Incluimos tests unitarios? [Sí / Solo smoke]\n2. ¿Usamos branch aislado?",
            }

    r_plan = workstation.Run(tmp_path, "Planifica cambios", "m", "plan", "coder", llm=ScriptedPlanLLM())
    r_plan.execute()
    assert r_plan.status in ("finishing", "completed")
    assert len(r_plan.questions) == 2 and r_plan.questions[0]["chips"] == ["Sí", "Solo smoke"]

    class ScriptedActLLM:
        def __init__(self):
            self.turn = 0

        def chat(self, msgs, tools=None):
            self.turn += 1
            if self.turn == 1:
                return {"role": "assistant", "tool_calls": [{"id": "c1", "function": {"name": "read_file", "arguments": {"path": "app.py"}}}]}
            if self.turn == 2:
                return {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "c2",
                            "function": {
                                "name": "write_file",
                                "arguments": {
                                    "path": "notes.txt",
                                    "content": "done",
                                    "summary_what": "Crear notes.txt",
                                    "summary_why": "Guardar bitácora del run",
                                    "summary_goal": "Verificar trust_session en Act",
                                },
                            },
                        }
                    ],
                }
            return {"role": "assistant", "content": "Archivo escrito."}

    r_act = workstation.Run(tmp_path, "Lee y crea notes.txt", "m", "act", "coder", llm=ScriptedActLLM())
    t = threading.Thread(target=r_act.execute, daemon=True)
    t.start()
    while r_act.status in ("running", "queued"):
        threading.Event().wait(0.01)
    snap = r_act.snapshot()
    assert snap["status"] == "awaiting_approval"
    assert snap["steps"][0]["kind"] == "read" and snap["steps"][0]["status"] == "completed"
    assert snap["steps"][1]["summary_what"] == "Crear notes.txt"
    r_act.decide(1, True, trust_session=True)
    t.join(timeout=3)
    assert r_act.status in ("finishing", "completed") and (tmp_path / "notes.txt").read_text() == "done"
    assert r_act.trusted


def test_metrics_demotion_tools_and_share_pack_and_gdrive(tmp_path):
    (tmp_path / "harness.toml").write_text("[agent.coder]\ncommand = ['echo']\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Team App\n", encoding="utf-8")
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-secret-dont-pack-1234567890\n", encoding="utf-8")
    (tmp_path / ".mcp.json").write_text(json.dumps({"mcpServers": {"memory": {"command": "python3", "args": ["-m", "caos_harness.memory.server"]}}}), encoding="utf-8")

    proj = app.load(tmp_path / "harness.toml")
    api = Api(proj)
    sk = api.skill_save({"name": "fleet-dispatch", "description": "Reglas operativas de ruteo para despachadores de flota", "body": "# Checklist\n- Validar ventana horaria", "category": "Logistica"})
    assert sk["local"] and sk["category"] == "Logistica"

    tools = api.tools_info()["tools"]
    assert any(t["id"] == "mcp:memory" for t in tools)

    metrics.record_run(tmp_path, "ollama", "qwen2.5:7b", 120, True, prompt_tokens=30, completion_tokens=15, kind="chat")
    snap = api.metrics_snapshot("project")
    assert snap["kpis"]["runs_total"] == 1 and snap["kpis"]["tokens"]["total"] == 45
    assert "##" not in metrics.export_markdown(snap) and "CAOS Operational Metrics" in metrics.export_markdown(snap)

    api.metrics_demote({"system": "qwen2.5:7b", "demoted": True})
    assert metrics.load_demotions(tmp_path)["qwen2.5:7b"]["demoted"] is True

    doc = share.doctor(tmp_path)
    assert not doc["clean"] and any(i["path"] == ".env" for i in doc["issues"])

    pack = share.build_share_pack(tmp_path, fmt="zip")
    assert pack["ok"] and Path(pack["path"]).is_file()
    with zipfile.ZipFile(pack["path"]) as zf:
        names = set(zf.namelist())
        assert ".env" not in names
        assert ".env.example" in names
        assert "TEAM_SETUP.md" in names
        assert "team_skills/ui-design/SKILL.md" in names
        assert "team_skills/proposals/SKILL.md" not in names

    def fake_runner(cmd, **kw):
        if cmd[1] == "mutate":
            return subprocess.CompletedProcess(cmd, 0, stdout='{"id":"gd-file-1"}', stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout='{"url":"https://drive.google.com/file/d/gd-file-1/view"}', stderr="")

    monkeypatch_gdrive = "/usr/bin/gdrive"
    orig_which = share.shutil.which
    try:
        share.shutil.which = lambda n: monkeypatch_gdrive if n == "gdrive" else orig_which(n)
        up = share.upload_gdrive(Path(pack["path"]), parent_id="folder123", runner=fake_runner)
    finally:
        share.shutil.which = orig_which
    assert up["ok"] and up["file_id"] == "gd-file-1" and "drive.google.com" in up["url"]
