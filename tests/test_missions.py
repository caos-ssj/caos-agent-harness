"""Tests for zero-token deterministic mission detection."""
from __future__ import annotations

import subprocess
from pathlib import Path

from caos_harness import app, missions
from caos_harness.web.server import Api


def _init_project(tmp_path: Path) -> app.Project:
    cfg = tmp_path / "harness.toml"
    cfg.write_text('[agents.dev]\ncommand = ["cat"]\n', encoding="utf-8")
    return app.load(cfg)


def test_detect_missions_finds_todos_untested_and_dirty_git(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    mod = src / "billing.py"
    mod.write_text("# TODO: handle zero amount\ndef compute_tax(amount: float) -> float:\n    return amount * 0.21\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "src/billing.py"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "init"], check=True)
    # Create an uncommitted edit to trigger dirty-changes too
    mod.write_text("# TODO: handle zero amount\ndef compute_tax(amount: float) -> float:\n    return max(0.0, amount * 0.21)\n", encoding="utf-8")

    proj = _init_project(tmp_path)
    out = missions.detect_missions(proj)
    ids = [m["id"] for m in out["missions"]]
    assert "dirty-changes" in ids
    assert "todo-fixme" in ids
    assert "untested-module" in ids
    todo_m = next(m for m in out["missions"] if m["id"] == "todo-fixme")
    assert "src/billing.py:1" in todo_m["citations"]
    untested_m = next(m for m in out["missions"] if m["id"] == "untested-module")
    assert "src/billing.py:2" in untested_m["citations"]


def test_detect_missions_handles_clean_minimal_workspace(tmp_path: Path):
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    proj = _init_project(tmp_path)
    out = missions.detect_missions(proj)
    assert out["has_git"] is False
    assert len(out["missions"]) >= 1
    assert any(c.startswith("app.py:") for m in out["missions"] for c in m["citations"])
    api = Api(proj)
    assert api.missions()["missions"] == out["missions"]
