"""Tests for 60s repository onboarding (`detect.py`), API routes and CLI init."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from caos_harness import app, detect, orchestrator, workspaces
from caos_harness.web.server import Api


def test_detect_stack_python_node_rust_go_and_make(tmp_path):
    py = tmp_path / "pyproj"
    py.mkdir()
    (py / "pyproject.toml").write_text('[project]\nname = "pyproj"\n', encoding="utf-8")
    (py / ".venv" / "bin").mkdir(parents=True)
    pytest_bin = py / ".venv" / "bin" / "pytest"
    pytest_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    s = detect.detect_stack(py)
    assert "python" in s["stacks"]
    assert s["verify"] == [".venv/bin/pytest", "-q"]

    js = tmp_path / "jsproj"
    js.mkdir()
    (js / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run", "build": "vite build"}}), encoding="utf-8")
    assert detect.detect_stack(js)["verify"] == ["npm", "test"]

    rs = tmp_path / "rsproj"
    rs.mkdir()
    (rs / "Cargo.toml").write_text('[package]\nname = "rsproj"\n', encoding="utf-8")
    assert detect.detect_stack(rs)["verify"] == ["cargo", "test", "--quiet"]

    go = tmp_path / "goproj"
    go.mkdir()
    (go / "go.mod").write_text("module example.com/app\n", encoding="utf-8")
    assert detect.detect_stack(go)["verify"] == ["go", "test", "./..."]

    mk = tmp_path / "mkproj"
    mk.mkdir()
    (mk / "Makefile").write_text("check:\n\techo ok\n", encoding="utf-8")
    assert detect.detect_stack(mk)["verify"] == ["make", "check"]


def test_scan_and_apply_init_generate_valid_harness_toml(tmp_path, monkeypatch):
    monkeypatch.setattr(detect.providers, "detect_clis", lambda: [{"id": "opencode", "installed": True}])
    monkeypatch.setattr(detect.providers, "probe_ollama", lambda timeout=0.5: {"models": ["nomic-embed-text:latest", "qwen2.5-coder:7b", "qwen2.5:7b"]})
    repo = tmp_path / "demo-service"
    repo.mkdir()
    (repo / "package.json").write_text(json.dumps({"scripts": {"build": "tsc"}}), encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

    plan = detect.scan(repo, probe_local_ollama=True)
    assert plan["has_git"] is True
    assert plan["stacks"] == ["node"]
    assert plan["verify"] == ["npm", "run", "build"]
    assert [e["name"] for e in plan["engines"]] == ["opencode", "local", "reviewer"]

    res = detect.apply_init(repo, probe_local_ollama=True)
    assert Path(res["created"]).is_file()
    loaded = app.load(repo / app.CONFIG)
    assert "opencode" in loaded.agents and "local" in loaded.agents and "reviewer" in loaded.agents
    cfg = orchestrator.landing_config(loaded)
    assert cfg["verify"] == ["npm", "run", "build"] and cfg["target"] == "branch"


def test_server_detect_and_workspace_register_smart_init(tmp_path, monkeypatch):
    monkeypatch.setenv("CAOS_HARNESS_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(detect.providers, "detect_clis", lambda: [])
    monkeypatch.setattr(detect.providers, "probe_ollama", lambda timeout=0.5: {"models": []})

    current = tmp_path / "main-ws"
    current.mkdir()
    app.init(current)
    api = Api(app.load(current / app.CONFIG))

    new_proj = tmp_path / "rust-ws"
    new_proj.mkdir()
    (new_proj / "Cargo.toml").write_text('[package]\nname = "rust-ws"\n', encoding="utf-8")

    preview = api.detect(str(new_proj))
    assert preview["stacks"] == ["rust"] and preview["verify"] == ["cargo", "test", "--quiet"]
    assert not (new_proj / app.CONFIG).exists()

    workspaces.register(str(new_proj), initialize=True)
    assert (new_proj / app.CONFIG).is_file()
    assert orchestrator.landing_config(app.load(new_proj / app.CONFIG))["verify"] == ["cargo", "test", "--quiet"]


def test_cli_detect_and_init_detect_flags(tmp_path):
    import sys
    proj = tmp_path / "cli-py"
    proj.mkdir()
    (proj / "pyproject.toml").write_text('[project]\nname = "cli-py"\n', encoding="utf-8")

    dry = subprocess.run([sys.executable, "-m", "caos_harness", "detect", "--no-ollama", "--json"], cwd=proj, capture_output=True, text=True, check=True)
    data = json.loads(dry.stdout)
    assert data["stacks"] == ["python"] and not (proj / app.CONFIG).exists()

    init = subprocess.run([sys.executable, "-m", "caos_harness", "init", "--detect", "--no-ollama", "--json"], cwd=proj, capture_output=True, text=True, check=True)
    created = json.loads(init.stdout)
    assert Path(created["created"]).is_file() and created["has_config"] is True


def test_windows_venv_and_shim_resolution(tmp_path, monkeypatch):
    win_py = tmp_path / "winproj"
    scripts = win_py / ".venv" / "Scripts"
    scripts.mkdir(parents=True)
    (win_py / "pyproject.toml").write_text('[project]\nname = "winproj"\n', encoding="utf-8")
    (scripts / "pytest.exe").write_text("exe", encoding="utf-8")
    (scripts / "python.exe").write_text("exe", encoding="utf-8")

    assert detect.detect_stack(win_py)["verify"] == [".venv/Scripts/pytest.exe", "-q"]

    monkeypatch.setattr(app.os, "name", "nt")
    monkeypatch.setattr(app.shutil, "which", lambda name: r"C:\Users\dev\AppData\Roaming\npm\claude.cmd" if name == "claude" else None)
    assert app.resolve_argv(["claude", "-p"]) == [r"C:\Users\dev\AppData\Roaming\npm\claude.cmd", "-p"]
    assert app.resolve_argv([str(win_py / ".venv" / "bin" / "python"), "-m", "pytest"]) == [str(scripts / "python.exe"), "-m", "pytest"]
