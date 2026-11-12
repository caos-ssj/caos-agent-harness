import json
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from caos_harness import app, worktrees
from caos_harness.web.server import Api, make_handler


@pytest.fixture
def git_project(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@caos.local"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "CAOS Test"], cwd=tmp_path, check=True)
    app.init(tmp_path)
    with open(tmp_path / "harness.toml", "a", encoding="utf-8") as f:
        f.write('[agents.upper]\ncommand = ["tr", "a-z", "A-Z"]\nsystem = "llama3.2:3b+rules"\n')
    (tmp_path / "notes.txt").write_text("alpha line\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".harness/\n.env.local\n", encoding="utf-8")
    subprocess.run(["git", "add", "harness.toml", "notes.txt", ".gitignore"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial commit"], cwd=tmp_path, check=True)
    return app.load(tmp_path / "harness.toml")


def test_worktree_isolation_include_incremental_reuse_and_branch_protection(git_project):
    root = git_project.root
    (root / ".worktreeinclude").write_text("local-settings.json\n", encoding="utf-8")
    (root / "local-settings.json").write_text('{"flag": "demo"}\n', encoding="utf-8")

    wt = worktrees.ensure(root, "sess-alpha")
    wt_path = root / ".harness" / "worktrees" / "sess-alpha"
    assert wt["branch"] == "caos/sess-alpha"
    assert wt["was_branch_pre_existing"] is False
    assert (wt_path / "local-settings.json").read_text(encoding="utf-8") == '{"flag": "demo"}\n'

    # Incremental Redo reuses existing worktree without clobbering uncommitted edits inside it.
    (wt_path / "notes.txt").write_text("alpha line\nbeta line\n", encoding="utf-8")
    (wt_path / "preview.html").write_text("<html><body><h1>Preview OK</h1></body></html>", encoding="utf-8")
    assert worktrees.ensure(root, "sess-alpha")["path"] == wt["path"]

    diff = worktrees.workspace_diff(wt_path)
    assert diff["git_repo"] is True
    assert diff["preview"]["path"] == "preview.html"
    assert any(f["path"] == "notes.txt" and f["additions"] >= 1 for f in diff["files"])
    assert "+beta line" in diff["diff"]

    # Discard deletes the newly created caos/ branch when not pre-existing.
    out = worktrees.discard(root, "sess-alpha")
    assert out["removed"] is True and out["branch_deleted"] is True and out["preserved_preexisting_branch"] is False

    # Pre-existing branch MUST be preserved when its temporary worktree is discarded (decision 5A).
    subprocess.run(["git", "branch", "caos/preexisting"], cwd=root, check=True)
    wt2 = worktrees.ensure(root, "preexisting")
    assert wt2["was_branch_pre_existing"] is True
    out2 = worktrees.discard(root, "preexisting")
    assert out2["removed"] is True and out2["branch_deleted"] is False and out2["preserved_preexisting_branch"] is True
    still_exists = subprocess.run(["git", "show-ref", "--verify", "--quiet", "refs/heads/caos/preexisting"], cwd=root).returncode == 0
    assert still_exists is True


def test_workspace_diff_never_leaks_secret_files(git_project):
    root = git_project.root
    (root / ".env").write_text("OPENAI_API_KEY=sk-1234567890abcdefghijklmnop\n", encoding="utf-8")
    files = worktrees.safe_workspace_files(root)
    assert ".env" not in files
    assert "notes.txt" in files
    diff = worktrees.workspace_diff(root)
    assert "sk-1234567890" not in diff["diff"]


def test_console_unified_targets_board_traceability_rename_and_cancel(git_project, monkeypatch):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Api(git_project)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(path, body=None, headers=None):
        req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None, {"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    try:
        code, sess = call("/api/sessions", {"title": "Initial", "mode": "plan"}, {"X-Harness": "1"})
        assert code == 201
        sid = sess["id"]

        # Rename session
        code, renamed = call(f"/api/sessions/{sid}/rename", {"title": "Renamed Session"}, {"X-Harness": "1"})
        assert code == 200 and renamed["title"] == "Renamed Session"

        # Agent target routes cleanly through a real Board task and expands @file safely.
        code, started = call(
            f"/api/sessions/{sid}/messages",
            {"content": "Process @notes.txt please", "target_kind": "agent", "target": "upper"},
            {"X-Harness": "1"},
        )
        assert code == 201 and "task_id" in started and "notes.txt" in started["attached"]
        for _ in range(100):
            _, run = call(f"/api/runs/{started['run_id']}")
            if run["status"] in ("completed", "failed", "stopped"):
                break
            time.sleep(0.02)
        assert run["status"] == "completed" and run["task_id"] == started["task_id"]
        assert "ALPHA LINE" in run["answer"]

        _, detail = call(f"/api/sessions/{sid}")
        assert detail["messages"][-1]["task_id"] == started["task_id"]
        _, btask = call(f"/api/task/{started['task_id']}")
        assert "ALPHA LINE" in btask["result"]

        # Tier critical escalates to person cleanly
        code, crit = call(
            f"/api/sessions/{sid}/messages",
            {"content": "Approve deploy", "target_kind": "tier", "target": "critical"},
            {"X-Harness": "1"},
        )
        assert code == 201 and "task_id" in crit
        for _ in range(80):
            _, crun = call(f"/api/runs/{crit['run_id']}")
            if crun["status"] in ("completed", "failed", "stopped"):
                break
            time.sleep(0.02)
        assert crun["status"] == "completed" and crun["queue"] == "person"

        # Workspace files + diff endpoints
        assert call("/api/workspace/files")[0] == 200
        assert "notes.txt" in call("/api/workspace/files")[1]["files"]
        assert call("/api/workspace/diff")[0] == 200

        # Active run cancellation endpoint
        gate = threading.Event()

        class SlowModel:
            def __init__(self, model): pass
            def chat(self, messages, tools):
                gate.wait(2.0)
                return {"role": "assistant", "content": "late"}

        monkeypatch.setattr("caos_harness.engines.workstation.OllamaChat", SlowModel)
        code, slow = call(
            f"/api/sessions/{sid}/messages",
            {"content": "Slow query", "mode": "plan", "target_kind": "model", "target": "slow"},
            {"X-Harness": "1"},
        )
        assert code == 201
        code, stopped = call(f"/api/runs/{slow['run_id']}/cancel", {}, {"X-Harness": "1"})
        gate.set()
        assert code == 200 and stopped["cancelled"] is True
        for _ in range(60):
            _, done_run = call(f"/api/runs/{slow['run_id']}")
            if done_run["status"] in ("completed", "failed", "stopped"):
                break
            time.sleep(0.02)
    finally:
        srv.shutdown()
        srv.server_close()


def test_worktreeinclude_refuses_secrets_hidden_paths_and_symlinks(git_project, tmp_path_factory):
    root = git_project.root
    outside = tmp_path_factory.mktemp("outside")
    (outside / "leak.txt").write_text("outside the project\n", encoding="utf-8")
    (root / ".env.local").write_text("TOKEN=abc\n", encoding="utf-8")
    (root / "credentials.json").write_text("{}\n", encoding="utf-8")
    (root / "server.pem").write_text("pem\n", encoding="utf-8")
    (root / ".hidden").mkdir()
    (root / ".hidden" / "a.txt").write_text("hidden\n", encoding="utf-8")
    (root / "ok.cfg").write_text("fine\n", encoding="utf-8")
    (root / "link.cfg").symlink_to(outside / "leak.txt")
    (root / "linked").symlink_to(outside, target_is_directory=True)
    (root / ".worktreeinclude").write_text("*\n**/*\n.env*\n", encoding="utf-8")

    wt = worktrees.ensure(root, "sess-include")
    from pathlib import Path
    wt_path = Path(wt["path"])
    assert (wt_path / "ok.cfg").read_text(encoding="utf-8") == "fine\n"
    for banned in (".env.local", "credentials.json", "server.pem", ".hidden/a.txt", "link.cfg", "linked/leak.txt"):
        assert not (wt_path / banned).exists(), banned
    assert not any(n in wt["included_files"] for n in (".env.local", "credentials.json", "server.pem", ".hidden/a.txt"))


def test_tracked_diff_redacts_secret_files_and_text_but_keeps_counts_and_other_files(git_project):
    root = git_project.root
    (root / "creds.txt").write_text("token = none\n", encoding="utf-8")
    (root / "server.key").write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "add", "creds.txt", "server.key"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "more"], cwd=root, check=True)
    (root / "creds.txt").write_text("token = sk-abcdefghijklmnopqrstuvwxyz0123\nline2\n", encoding="utf-8")
    (root / "server.key").write_text("new private\n", encoding="utf-8")
    (root / "notes.txt").write_text("alpha line\nsafe addition\n", encoding="utf-8")

    d = worktrees.workspace_diff(root)
    assert "sk-abcdefghijkl" not in d["diff"] and "new private" not in d["diff"] and "old" not in d["diff"].replace("redacted", "")
    assert "diff --git a/creds.txt b/creds.txt" in d["diff"] and "redacted: secret-like content" in d["diff"]
    assert "diff --git a/server.key b/server.key" in d["diff"] and "redacted: secret-like file name" in d["diff"]
    assert "+safe addition" in d["diff"]                                  # the harmless file keeps its hunk intact
    by = {f["path"]: f for f in d["files"]}
    assert by["creds.txt"]["additions"] == 2 and by["notes.txt"]["additions"] == 1


def test_save_meta_is_atomic_and_leaves_no_temp_file_on_failure(git_project, monkeypatch):
    root = git_project.root.resolve()
    worktrees._save_meta(root, {"a": {"path": "x"}})
    meta = worktrees._meta_file(root)
    assert oct(meta.stat().st_mode & 0o777) == "0o600"

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(worktrees.os, "replace", boom)
    with pytest.raises(OSError):
        worktrees._save_meta(root, {"b": {"path": "y"}})
    monkeypatch.undo()
    assert json.loads(meta.read_text(encoding="utf-8")) == {"a": {"path": "x"}}   # the old file is untouched
    assert [p.name for p in meta.parent.iterdir() if p.name.endswith(".tmp")] == []
