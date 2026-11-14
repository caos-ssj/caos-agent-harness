"""The landing gate: a worktree's changes reach the project folder only if they apply cleanly on the project as it is now and the
verify command passes on exactly that result. Every other outcome must leave the project folder byte for byte as it was."""
import os
import subprocess
import sys

import pytest

from caos_harness import app, orchestrator, worktrees

PY = sys.executable
OK = [PY, "-c", "pass"]
FAIL = [PY, "-c", "import sys; print('2 failed, 5 passed'); sys.exit(1)"]


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def project(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@caos.local")
    git(tmp_path, "config", "user.name", "CAOS Test")
    app.init(tmp_path)
    with open(tmp_path / "harness.toml", "a", encoding="utf-8") as f:
        f.write('[agents.upper]\ncommand = ["tr", "a-z", "A-Z"]\n')
    (tmp_path / "notes.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    (tmp_path / "other.txt").write_text("one\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".harness/\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "initial commit")
    return app.load(tmp_path / "harness.toml")


def edited_worktree(root, key="job"):
    wt = worktrees.ensure(root, key)
    path = root / ".harness" / "worktrees" / key
    (path / "notes.txt").write_text("alpha\nbeta changed by the agent\ngamma\n", encoding="utf-8")
    (path / "new_module.py").write_text("VALUE = 42\n", encoding="utf-8")
    return wt, path


def nothing_left_behind(root):
    landing = root / ".harness" / "landing"
    assert not landing.exists() or not list(landing.iterdir())
    assert "landing" not in git(root, "worktree", "list")


def test_a_verified_change_lands_as_uncommitted_work_and_keeps_what_the_operator_had(project):
    root = project.root
    head, _ = git(root, "rev-parse", "HEAD"), edited_worktree(root)
    (root / "other.txt").write_text("one\nmy own uncommitted line\n", encoding="utf-8")   # the operator's work in progress
    (root / "scratch.md").write_text("untracked\n", encoding="utf-8")
    # the verify command runs on project + patch: it must see the agent's change AND the operator's uncommitted work
    verify = [PY, "-c", "import new_module, pathlib; assert new_module.VALUE == 42; "
                        "assert 'my own' in pathlib.Path('other.txt').read_text(); assert pathlib.Path('scratch.md').exists(); "
                        "assert 'changed by the agent' in pathlib.Path('notes.txt').read_text()"]
    out = worktrees.land(root, "job", verify)
    assert out["status"] == "landed", out
    assert sorted(out["files"]) == ["new_module.py", "notes.txt"] and out["verify"]["exit"] == 0
    assert "changed by the agent" in (root / "notes.txt").read_text() and (root / "new_module.py").read_text() == "VALUE = 42\n"
    assert "my own uncommitted line" in (root / "other.txt").read_text() and (root / "scratch.md").exists()
    assert git(root, "rev-parse", "HEAD") == head                       # nothing was committed
    assert git(root, "diff", "--cached", "--name-only") == ""            # nothing was staged either
    assert worktrees.snapshot_tree(root) == out["tree"]                  # what is on disk is the tree that was verified
    assert worktrees.get(root, "job")["landed"]["tree"] == out["tree"]
    nothing_left_behind(root)
    assert worktrees.land(root, "job", OK)["status"] == "conflict"       # landing twice does not apply the change twice


def test_a_failing_verify_command_leaves_the_project_untouched(project):
    root = project.root
    edited_worktree(root)
    (root / "other.txt").write_text("one\nwip\n", encoding="utf-8")
    before = worktrees.snapshot_tree(root)
    out = worktrees.land(root, "job", FAIL)
    assert out["status"] == "verify_failed" and out["verify"]["exit"] == 1 and "2 failed" in out["verify"]["tail"]
    assert worktrees.snapshot_tree(root) == before and not (root / "new_module.py").exists()
    assert "landed" not in worktrees.get(root, "job")
    nothing_left_behind(root)


def test_the_verify_command_runs_in_the_staging_copy_and_can_reach_tools_of_the_project_folder(project):
    root = project.root
    edited_worktree(root)
    (root / ".gitignore").write_text(".harness/\ntools_ignored/\n", encoding="utf-8")
    git(root, "commit", "-q", "-am", "ignore the tools folder")
    (root / "tools_ignored").mkdir()
    (root / "tools_ignored" / "check.py").write_text(
        "import os, pathlib\nassert pathlib.Path.cwd() != pathlib.Path(os.environ['CAOS_PROJECT_ROOT'])\n"
        "assert not pathlib.Path('tools_ignored').exists() and pathlib.Path('new_module.py').exists()\n", encoding="utf-8")
    out = worktrees.land(root, "job", [PY, "{project}/tools_ignored/check.py"])
    assert out["status"] == "landed" and out["verify"]["command"][1] == "{project}/tools_ignored/check.py", out


def test_a_verify_command_that_hangs_is_killed_and_counts_as_failed(project):
    edited_worktree(project.root)
    out = worktrees.land(project.root, "job", [PY, "-c", "import time; time.sleep(30)"], timeout=0.5)
    assert out["status"] == "verify_failed" and out["verify"]["exit"] == 124
    assert not (project.root / "new_module.py").exists()


def test_a_change_that_collides_with_uncommitted_work_is_a_conflict_and_is_not_verified(project):
    root = project.root
    edited_worktree(root)
    (root / "notes.txt").write_text("alpha\nbeta changed by the operator\ngamma\n", encoding="utf-8")
    before = worktrees.snapshot_tree(root)
    out = worktrees.land(root, "job", OK)
    assert out["status"] == "conflict" and out["verify"] is None
    assert worktrees.snapshot_tree(root) == before and "by the operator" in (root / "notes.txt").read_text()
    nothing_left_behind(root)


def test_an_untracked_file_in_the_project_is_never_overwritten(project):
    root = project.root
    edited_worktree(root)
    (root / "new_module.py").write_text("VALUE = 'mine'\n", encoding="utf-8")
    out = worktrees.land(root, "job", OK)
    assert out["status"] == "conflict" and (root / "new_module.py").read_text() == "VALUE = 'mine'\n"


def test_secret_looking_files_and_content_are_refused(project):
    root = project.root
    _, path = edited_worktree(root, "a")
    (path / ".env").write_text("TOKEN=abc\n", encoding="utf-8")
    out = worktrees.land(root, "a", OK)
    assert out["status"] == "refused" and ".env" in out["reason"] and not (root / ".env").exists()
    _, path = edited_worktree(root, "b")
    (path / "config.py").write_text('API_KEY = "sk-ant-api03-' + "a" * 40 + '"\n', encoding="utf-8")
    out = worktrees.land(root, "b", OK)
    assert out["status"] == "refused" and "secret" in out["reason"] and not (root / "config.py").exists()


def test_an_untouched_worktree_is_empty_and_local_include_copies_are_not_part_of_the_change(project):
    root = project.root
    (root / ".worktreeinclude").write_text("local-settings.json\n", encoding="utf-8")
    (root / "local-settings.json").write_text("{}\n", encoding="utf-8")
    git(root, "add", ".worktreeinclude")
    git(root, "commit", "-q", "-m", "include list")
    wt = worktrees.ensure(root, "idle")
    assert wt["included_files"] == ["local-settings.json"]
    assert worktrees.land(root, "idle", OK)["status"] == "empty"


def test_a_binary_file_and_a_deletion_land_intact(project):
    root = project.root
    worktrees.ensure(root, "bin")
    path = root / ".harness" / "worktrees" / "bin"
    blob = bytes(range(256)) * 8
    (path / "logo.bin").write_bytes(blob)
    (path / "other.txt").unlink()
    out = worktrees.land(root, "bin", OK)
    assert out["status"] == "landed", out
    assert (root / "logo.bin").read_bytes() == blob and not (root / "other.txt").exists()


def test_if_the_project_changes_while_verifying_nothing_is_applied(project):
    root = project.root
    edited_worktree(root)
    meddle = [PY, "-c", f"import pathlib; pathlib.Path({str(root / 'other.txt')!r}).write_text('changed meanwhile\\n')"]
    out = worktrees.land(root, "job", meddle)
    assert out["status"] == "drifted" and not (root / "new_module.py").exists()
    assert (root / "notes.txt").read_text() == "alpha\nbeta\ngamma\n"


def test_a_result_that_differs_from_the_verified_tree_is_rolled_back(project, monkeypatch):
    root = project.root
    edited_worktree(root)
    before, real, calls = worktrees.snapshot_tree(root), worktrees.snapshot_tree, []

    def lying(path):   # the 4th snapshot is the one taken right after applying to the project
        calls.append(path)
        return "0" * 40 if len(calls) == 4 else real(path)

    monkeypatch.setattr(worktrees, "snapshot_tree", lying)
    out = worktrees.land(root, "job", OK)
    monkeypatch.undo()
    assert out["status"] == "rolled_back" and "back as it was" in out["reason"]
    assert worktrees.snapshot_tree(root) == before and not (root / "new_module.py").exists()


def test_landing_needs_a_verify_command_and_an_existing_worktree(project):
    edited_worktree(project.root)
    with pytest.raises(app.ConfigError, match="verify command"):
        worktrees.land(project.root, "job", [])
    with pytest.raises(app.ConfigError, match="no isolated worktree"):
        worktrees.land(project.root, "ghost", OK)
    with pytest.raises(app.ConfigError, match="no verify command"):
        orchestrator.land(project, "job")   # harness.toml has no [landing] and none was passed


class _Instant:
    def is_idle(self, agent):
        return True

    def send(self, agent, text):
        pass


def test_the_board_holds_the_gate_until_a_human_accepts_the_task_and_every_attempt_is_traced(project):
    root = project.root
    edited_worktree(root)
    with open(root / "harness.toml", "a", encoding="utf-8") as f:
        f.write(f'[landing]\nverify = [{PY!r}, "-c", "pass"]\ntimeout = 60\n'.replace("'", '"'))
    b = project.board
    tid = b.add("change beta", queue="upper", worktree_key="job")
    assert b.assign(tid, "upper", _Instant()).ok and b.deliver(tid, "done")

    out = orchestrator.land(project, "job")
    assert out["status"] == "refused" and f"#{tid}" in out["reason"] and not (root / "new_module.py").exists()

    b.review(tid, "ok", "read the diff")
    before_cfg = (root / "harness.toml").read_text()
    out = orchestrator.land(project, "job")
    assert out["status"] == "landed" and out["tasks"] == [tid], out
    assert (root / "harness.toml").read_text() == before_cfg
    gates = [e for e in b.trace.timeline(f"task:{tid}") if e["source"] == "landing"]
    assert [e["status"] for e in gates] == ["refused", "landed"]
    assert orchestrator.landing_config(project) == {"verify": [PY, "-c", "pass"], "timeout": 60.0, "autonomous": False, "verifier": None, "target": "branch"}


def test_a_malformed_landing_section_is_a_config_error(project):
    with open(project.root / "harness.toml", "a", encoding="utf-8") as f:
        f.write('[landing]\nverify = "make test"\n')
    with pytest.raises(app.ConfigError, match="list of strings"):
        orchestrator.landing_config(project)


def test_a_project_that_does_not_ignore_its_harness_folder_still_lands_without_it(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "test@caos.local")
    git(tmp_path, "config", "user.name", "CAOS Test")
    app.init(tmp_path)
    (tmp_path / "notes.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    git(tmp_path, "add", "harness.toml", "notes.txt")   # no .gitignore: .harness/ is plain untracked content here
    git(tmp_path, "commit", "-q", "-m", "initial commit")
    edited_worktree(tmp_path)
    out = worktrees.land(tmp_path, "job", OK)
    assert out["status"] == "landed" and out["files"] == ["new_module.py", "notes.txt"], out
    assert (tmp_path / "new_module.py").exists()


def test_reward_hacking_guardrail_blocks_config_tampering_test_skipping_and_assertion_weakening(project):
    from caos_harness import landed
    root = project.root
    (root / "tests").mkdir()
    (root / "tests" / "test_calc.py").write_text(
        "def test_add():\n    assert 1 + 1 == 2\n    assert 2 + 2 == 4\n",
        encoding="utf-8",
    )
    git(root, "add", "tests/test_calc.py")
    git(root, "commit", "-q", "-m", "add test_calc")

    # 1. Tampering with harness.toml
    _, wt_cfg = edited_worktree(root, "hack_cfg")
    (wt_cfg / "harness.toml").write_text("[landing]\nverify = [\"true\"]\n", encoding="utf-8")
    out_cfg = worktrees.land(root, "hack_cfg", OK)
    assert out_cfg["status"] == "refused"
    assert "WHAT:" in out_cfg["reason"] and "WHY:" in out_cfg["reason"] and "FIX:" in out_cfg["reason"]
    assert out_cfg["diagnostics"][0]["code"] == "harness_config_tampered"

    # 2. Injecting @pytest.mark.skip into a test file
    worktrees.ensure(root, "hack_skip")
    wt_skip = root / ".harness" / "worktrees" / "hack_skip"
    (wt_skip / "tests" / "test_calc.py").write_text(
        "import pytest\n@pytest.mark.skip(reason='skip failing test')\ndef test_add():\n    assert 1 + 1 == 2\n    assert 2 + 2 == 4\n",
        encoding="utf-8",
    )
    out_skip = worktrees.land(root, "hack_skip", OK)
    assert out_skip["status"] == "refused"
    assert out_skip["diagnostics"][0]["code"] == "test_skip_injected"
    assert "WHAT:" in out_skip["reason"] and "FIX:" in out_skip["reason"]

    # 3. Weakening assertions (deleting an assert statement)
    worktrees.ensure(root, "hack_assert")
    wt_assert = root / ".harness" / "worktrees" / "hack_assert"
    (wt_assert / "tests" / "test_calc.py").write_text(
        "def test_add():\n    assert 1 + 1 == 2\n",
        encoding="utf-8",
    )
    out_assert = worktrees.land(root, "hack_assert", OK)
    assert out_assert["status"] == "refused"
    assert out_assert["diagnostics"][0]["code"] == "assertions_weakened"
    assert out_assert[" verify" if " verify" in out_assert else "verify"] is None

    # 4. Also blocked on branch integration (`landed.integrate`)
    out_branch = landed.integrate(root, "hack_assert", OK, reviewed_by="opencode")
    assert out_branch["status"] == "refused"
    assert out_branch["diagnostics"][0]["code"] == "assertions_weakened"

    # 5. Adding new assertions is allowed by default, but blocked when protect_tests=True
    worktrees.ensure(root, "add_test")
    wt_add = root / ".harness" / "worktrees" / "add_test"
    (wt_add / "tests" / "test_calc.py").write_text(
        "def test_add():\n    assert 1 + 1 == 2\n    assert 2 + 2 == 4\n    assert 3 + 3 == 6\n",
        encoding="utf-8",
    )
    out_strict = worktrees.land(root, "add_test", OK, protect_tests=True)
    assert out_strict["status"] == "refused"
    assert out_strict["diagnostics"][0]["code"] == "protected_eval_modified"
    out_ok = worktrees.land(root, "add_test", OK, protect_tests=False)
    assert out_ok["status"] == "landed"


def test_lock_and_unlock_eval_paths_enforce_readonly_permissions_and_discard_cleans_up(project):
    root = project.root
    (root / "tests").mkdir()
    (root / "tests" / "test_core.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    git(root, "add", "tests/test_core.py")
    git(root, "commit", "-q", "-m", "add test_core")

    worktrees.ensure(root, "locked_wt")
    wt = root / ".harness" / "worktrees" / "locked_wt"
    locked = worktrees.lock_eval_paths(wt)
    assert "tests/test_core.py" in locked and "harness.toml" in locked
    assert not ((wt / "tests" / "test_core.py").stat().st_mode & 0o200)
    if getattr(os, "geteuid", lambda: 1)() != 0:   # root in CI containers bypasses POSIX 0444 write bits
        with pytest.raises(PermissionError):
            (wt / "tests" / "test_core.py").write_text("def test_ok():\n    pass\n", encoding="utf-8")

    # discard unlocks automatically before removing the git worktree
    res = worktrees.discard(root, "locked_wt")
    assert res["removed"] and not wt.exists()
