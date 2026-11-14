"""`harness/landed`: verified work accumulates on its own branch. The invariants under test are the ones that keep the system from
fooling itself: your branch and folder never move, the branch only ever points at a tree that passed, a conflict is never resolved
silently, and the history can be re-audited from git alone."""
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from caos_harness import app, landed, worktrees

PY = sys.executable
OK = [PY, "-c", "pass"]
FAIL = [PY, "-c", "raise SystemExit(3)"]


def git(root, *args):
    return subprocess.run(["git", "-c", "user.email=t@example.test", "-c", "user.name=t", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def root(tmp_path):
    git(tmp_path, "init", "-q", "-b", "main")
    app.init(tmp_path)
    (tmp_path / "notes.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    (tmp_path / ".gitignore").write_text(".harness/\n", encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def edit(root, key, files):
    wt = Path(worktrees.ensure(root, key)["path"])
    for name, text in files.items():
        (wt / name).write_text(text, encoding="utf-8")
    return wt


def frozen(root):
    """Everything that must not move: HEAD, the checked-out branch, the index and the files on disk."""
    return (git(root, "rev-parse", "HEAD"), git(root, "rev-parse", "main"), git(root, "status", "--porcelain"), worktrees.snapshot_tree(root))


def test_a_verified_change_lands_on_its_own_branch_and_nothing_of_yours_moves(root):
    (root / "wip.txt").write_text("my own uncommitted work\n", encoding="utf-8")
    edit(root, "a", {"feature.py": "VALUE = 1\n"})
    before = frozen(root)
    out = landed.integrate(root, "a", [PY, "-c", "import feature; assert feature.VALUE == 1"], reviewed_by="opencode")
    assert out["status"] == "landed" and out["files"] == ["feature.py"] and out["parent"] is None, out
    assert frozen(root) == before and not (root / "feature.py").exists()             # not in your folder, not on your branch
    assert git(root, "rev-parse", landed.BRANCH) == out["commit"] and git(root, "rev-parse", f"{landed.BRANCH}^{{tree}}") == out["tree"]
    assert git(root, "show", f"{landed.BRANCH}:feature.py") == "VALUE = 1" and "wip.txt" not in git(root, "ls-tree", "--name-only", landed.BRANCH)
    body = git(root, "log", "-1", "--format=%B", landed.BRANCH)
    assert "Harness-Reviewed-By: opencode" in body and "Harness-Verified:" in body and f"Harness-Tree: {out['tree']}" in body
    assert git(root, "rev-parse", f"{landed.BRANCH}^1") == before[0]                  # it grows from where your branch was
    assert not list((root / ".harness" / "landing").iterdir()) and landed.rebase_point(root) == out["commit"]


def test_a_second_worktree_cut_from_main_merges_onto_what_already_landed(root):
    edit(root, "a", {"feature.py": "VALUE = 1\n"})
    edit(root, "b", {"notes.txt": "alpha\nbeta\ngamma\ndelta\n"})                     # both started from main, neither knows the other
    first = landed.integrate(root, "a", OK, reviewed_by="opencode")
    # the verify command of the second sees BOTH changes: it verifies the merge, not the worktree
    both = [PY, "-c", "import feature, pathlib; assert 'delta' in pathlib.Path('notes.txt').read_text()"]
    second = landed.integrate(root, "b", both, reviewed_by="claude")
    assert second["status"] == "landed" and second["parent"] == first["commit"], second
    assert git(root, "ls-tree", "--name-only", landed.BRANCH).split() == [".gitignore", "feature.py", "harness.toml", "notes.txt"]
    log = landed.audit(root)
    assert [(e["worktree"], e["reviewed_by"], e["intact"], e["foreign"]) for e in log] == [("b", "claude", True, False), ("a", "opencode", True, False)]
    assert landed.integrate(root, "b", OK, reviewed_by="claude")["status"] == "empty"  # the same work does not land twice


def test_a_conflict_is_reported_with_its_files_and_never_resolved_here(root):
    edit(root, "a", {"notes.txt": "alpha\nbeta from A\ngamma\n"})
    edit(root, "b", {"notes.txt": "alpha\nbeta from B\ngamma\n", "extra.txt": "x\n"})
    first = landed.integrate(root, "a", OK, reviewed_by="opencode")
    ran = root / "verify-ran"
    out = landed.integrate(root, "b", [PY, "-c", f"open({str(ran)!r}, 'w')"], reviewed_by="opencode")
    assert out["status"] == "conflict" and out["conflicts"] == ["notes.txt"] and out["verify"] is None and not ran.exists()
    assert landed.tip(root) == first["commit"]
    # the way out: a fresh worktree from the branch tip, where the author writes the resolution as a normal change
    wt = Path(worktrees.ensure(root, "b2")["path"])
    git(wt, "reset", "-q", "--hard", landed.rebase_point(root))
    (wt / "notes.txt").write_text("alpha\nbeta from A and B\ngamma\n", encoding="utf-8")
    assert landed.integrate(root, "b2", OK, reviewed_by="opencode")["status"] == "landed"
    assert "from A and B" in git(root, "show", f"{landed.BRANCH}:notes.txt")


def test_a_failed_verification_a_dry_run_and_a_secret_leave_the_branch_where_it_was(root):
    edit(root, "a", {"feature.py": "VALUE = 1\n"})
    out = landed.integrate(root, "a", FAIL, reviewed_by="opencode")
    assert out["status"] == "verify_failed" and out["verify"]["exit"] == 3 and landed.tip(root) is None
    out = landed.integrate(root, "a", OK, reviewed_by="opencode", dry_run=True)
    assert out["status"] == "verified" and out["tree"] and out["commit"] is None and landed.tip(root) is None
    edit(root, "s", {".env": "TOKEN=abc\n"})
    assert landed.integrate(root, "s", OK, reviewed_by="opencode")["status"] == "refused" and landed.tip(root) is None


def test_what_the_verify_command_leaves_in_the_staging_copy_cannot_reach_the_branch(root):
    edit(root, "a", {"feature.py": "VALUE = 1\n"})
    cheat = [PY, "-c", "open('feature.py', 'w').write('VALUE = 999\\n'); open('junk.txt', 'w').write('x')"]
    out = landed.integrate(root, "a", cheat, reviewed_by="opencode")
    assert out["status"] == "landed"
    assert git(root, "show", f"{landed.BRANCH}:feature.py") == "VALUE = 1" and "junk.txt" not in git(root, "ls-tree", "--name-only", landed.BRANCH)


def test_nothing_lands_without_a_verify_command_or_without_a_named_reviewer(root):
    edit(root, "a", {"feature.py": "VALUE = 1\n"})
    for verify, who in (([], "opencode"), (OK, ""), (OK, "two words"), (OK, None)):
        with pytest.raises(app.ConfigError):
            landed.integrate(root, "a", verify, reviewed_by=who)
    assert landed.tip(root) is None


def test_if_the_branch_moves_during_verification_the_swap_fails_and_nothing_is_integrated(root):
    edit(root, "a", {"feature.py": "VALUE = 1\n"})
    edit(root, "b", {"other.py": "X = 2\n"})
    first = landed.integrate(root, "a", OK, reviewed_by="opencode")
    # while "b" is being verified, someone moves the branch back by hand
    mover = [PY, "-c", f"import subprocess; subprocess.run(['git', 'update-ref', '{landed.REF}', '{first['parent'] or git(root, 'rev-parse', 'main')}'], cwd={str(root)!r}, check=True)"]
    out = landed.integrate(root, "b", mover, reviewed_by="opencode")
    assert out["status"] == "drifted" and out["commit"] is None
    assert landed.tip(root) == git(root, "rev-parse", "main")                          # exactly where the other writer left it


def test_two_landings_at_once_both_end_on_the_branch_one_after_the_other(root):
    edit(root, "a", {"a.py": "A = 1\n"})
    edit(root, "b", {"b.py": "B = 1\n"})
    results = {}
    threads = [threading.Thread(target=lambda k=k: results.setdefault(k, landed.integrate(root, k, OK, reviewed_by="opencode"))) for k in ("a", "b")]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert {r["status"] for r in results.values()} == {"landed"}
    assert set(git(root, "ls-tree", "--name-only", landed.BRANCH).split()) >= {"a.py", "b.py"} and len(landed.audit(root)) == 2


def test_undo_takes_one_landing_off_and_the_audit_flags_what_the_harness_did_not_write(root):
    edit(root, "a", {"a.py": "A = 1\n"})
    edit(root, "b", {"b.py": "B = 1\n"})
    one = landed.integrate(root, "a", OK, reviewed_by="opencode")
    two = landed.integrate(root, "b", OK, reviewed_by="opencode")
    assert not landed.undo(root, expected=one["commit"])["ok"]                         # not the tip any more: refuse, do not guess
    assert landed.undo(root, expected=two["commit"]) == {"ok": True, "reason": "", "tip": one["commit"], "undone": two["commit"]}
    assert landed.undo(root)["ok"] and landed.tip(root) is None and landed.audit(root) == []   # back to before the first landing: no branch
    assert not landed.undo(root)["ok"]
    # a commit put on the branch by hand, above a landing, is visible as foreign
    one = landed.integrate(root, "a", OK, reviewed_by="opencode")
    manual = git(root, "commit-tree", f"{one['commit']}^{{tree}}", "-p", one["commit"], "-m", "sneaked in")
    git(root, "update-ref", landed.REF, manual)
    assert [(e["foreign"], e["intact"]) for e in landed.audit(root)] == [(True, False), (False, True)]


def test_a_branch_someone_has_checked_out_is_not_moved_under_them(root):
    edit(root, "a", {"a.py": "A = 1\n"})
    edit(root, "b", {"b.py": "B = 1\n"})
    landed.integrate(root, "a", OK, reviewed_by="opencode")
    git(root, "worktree", "add", "-q", str(root.parent / "elsewhere"), landed.BRANCH)
    out = landed.integrate(root, "b", OK, reviewed_by="opencode")
    assert out["status"] == "refused" and "checked out" in out["reason"] and not landed.undo(root)["ok"]
