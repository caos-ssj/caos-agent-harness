"""Integration into `harness/landed`: verified work accumulates on a branch of its own, never on yours.

    worktree ──3-way merge in memory──▶ merged tree ──verify command in a staging copy──▶ commit ──compare-and-swap──▶ harness/landed

Nothing here writes to the project folder, its index, the checked-out branch or `HEAD`. The merge is computed by git without a
working tree (`git merge-tree --write-tree`), the result is verified in a throwaway checkout, and the branch moves with one
`git update-ref <new> <old>`: either the ref now points at a commit whose tree is exactly the tree that passed, or it did not move.
There is no partial state to roll back from. Taking the work is then an ordinary, human `git merge harness/landed`.

A conflict is never resolved here, by code or by a model: `integrate` reports the files and stops. The caller gives the author a
fresh worktree cut from the branch tip (`rebase_point`) and the task again, so the resolution is written, reviewed and verified
like any other change.

Every landed commit has two parents (the previous tip and a snapshot of the worktree) and carries what let it in as trailers:
`Harness-Worktree`, `Harness-Reviewed-By`, `Harness-Verified` and `Harness-Tree`. `audit` re-reads the branch and checks them.
"""
from __future__ import annotations

import os
import re
import shutil
import threading
import time
from pathlib import Path

from . import app, chat, worktrees

BRANCH = "harness/landed"
REF = f"refs/heads/{BRANCH}"
STATUSES = ("landed", "verified", "empty", "refused", "conflict", "verify_failed", "drifted")
ZERO = "0" * 40
_IDENT = {"GIT_AUTHOR_NAME": "caos-harness", "GIT_AUTHOR_EMAIL": "harness@localhost",
          "GIT_COMMITTER_NAME": "caos-harness", "GIT_COMMITTER_EMAIL": "harness@localhost"}
_LOCK = threading.Lock()
_TRAILER = re.compile(r"^(Harness-[A-Za-z-]+): (.*)$", re.M)


def _git(root: Path, *args: str, timeout: float = 60, env: dict | None = None) -> tuple[int, str]:
    return worktrees._run(["git", *args], root, timeout=timeout, env={**os.environ, **_IDENT, **(env or {})})


def _rev(root: Path, name: str) -> str | None:
    rc, out = _git(root, "rev-parse", "--verify", "--quiet", name)
    return out.strip() if rc == 0 and out.strip() else None


def tip(repo_root: Path) -> str | None:
    """The commit `harness/landed` points at, or None while nothing has landed."""
    return _rev(repo_root.resolve(), REF)


def rebase_point(repo_root: Path) -> str:
    """Where a new worktree should start so that its change merges onto what already landed: the branch tip, or HEAD before the first landing."""
    root = repo_root.resolve()
    return tip(root) or _rev(root, "HEAD") or ""


def _checked_out(root: Path) -> bool:
    _, out = _git(root, "worktree", "list", "--porcelain")
    return f"branch {REF}" in out.splitlines()


def integrate(repo_root: Path, key: str, verify: list[str], reviewed_by: str, timeout: float = 900, dry_run: bool = False, protect_tests: bool = False) -> dict:
    """Merges worktree `key` onto `harness/landed`, verifies the merged tree, and moves the branch only if everything held.

    Returns {"status", "reason", "files", "conflicts", "verify", "commit", "tree", "parent"}. `reviewed_by` names who approved the
    change (an agent or a person) and is required: this function is the last step of a cycle, not a way around it. With `dry_run`
    it stops after verification (`verified`). Any status but `landed` leaves every ref exactly where it was.
    """
    with _LOCK:
        return _integrate(repo_root.resolve(), key, verify, reviewed_by, timeout, dry_run, protect_tests)


def _integrate(root: Path, key: str, verify: list[str], reviewed_by: str, timeout: float, dry_run: bool, protect_tests: bool = False) -> dict:
    clean = worktrees._safe_key(key)
    entry = worktrees.get(root, clean)
    if not entry:
        raise app.ConfigError(f"no isolated worktree '{clean}'")
    if not (isinstance(verify, (list, tuple)) and verify and all(isinstance(x, str) and x for x in verify)):
        raise app.ConfigError("integration needs a verify command (a non-empty list of strings): without one it is not a gate")
    if not (isinstance(reviewed_by, str) and re.fullmatch(r"[\w.@:+-]{1,64}", reviewed_by)):
        raise app.ConfigError("integration needs the name of who reviewed the change")
    res: dict = {"key": clean, "status": "refused", "reason": "", "files": [], "conflicts": [], "verify": None, "commit": None, "tree": None, "parent": None}

    def done(status: str, reason: str = "") -> dict:
        res["status"], res["reason"] = status, reason[:600]
        return res

    if _checked_out(root):
        return done("refused", f"{BRANCH} is checked out in a working tree: moving it would leave that tree stale. Check out another branch there")
    wt = Path(entry["path"])
    wt_head, head = _rev(wt, "HEAD"), _rev(root, "HEAD")
    if not wt_head or not head:
        return done("refused", "the worktree or the project has no commit")
    parent = tip(root)
    onto = parent or head
    res["parent"] = parent

    # 1 · the worktree as it stands (committed or not, minus local include copies) becomes one unreferenced commit
    skip = entry.get("included_files") or []
    wt_tree = worktrees.snapshot_tree(wt)
    if skip:   # drop the copies of local files from the snapshot: they are not the author's work
        (root / ".harness").mkdir(exist_ok=True)
        fd_env = {"GIT_INDEX_FILE": str(root / ".harness" / f"landed-{os.getpid()}.idx")}
        try:
            _git(root, "read-tree", wt_tree, env=fd_env)
            _git(root, "rm", "-q", "--cached", "--ignore-unmatch", "--", *skip, env=fd_env)
            rc, out = _git(root, "write-tree", env=fd_env)
            wt_tree = out.strip() if rc == 0 and out.strip() else wt_tree
        finally:
            Path(fd_env["GIT_INDEX_FILE"]).unlink(missing_ok=True)
    rc, out = _git(root, "commit-tree", wt_tree, "-p", wt_head, "-m", f"worktree {clean}")
    if rc != 0:
        return done("refused", f"could not snapshot the worktree: {out.strip()[-200:]}")
    theirs = out.strip()

    # 2 · three-way merge in memory, onto what already landed
    rc, out = _git(root, "merge-tree", "--write-tree", "--name-only", "--no-messages", onto, theirs)
    lines = out.strip().splitlines()
    if rc == 1:
        res["conflicts"] = sorted(set(lines[1:]))[:100]
        return done("conflict", f"{len(res['conflicts'])} file(s) conflict with what already landed: the author needs a fresh worktree from {onto[:12]}")
    if rc != 0 or not lines:
        return done("refused", f"git could not merge (git 2.38 or later is needed): {out.strip()[-200:]}")
    merged = lines[0]
    _, names = _git(root, "diff", "--name-only", "-z", onto, merged)
    files = [n for n in names.split("\0") if n]
    if not files:
        return done("empty", "the worktree adds nothing to what already landed")
    res["files"] = files[:200]
    secret = [f for f in files if chat.SECRET_NAMES.search(f)]
    if secret:
        return done("refused", f"the change touches secret-looking files: {', '.join(secret[:5])}")
    _, patch = _git(root, "diff", "--no-color", onto, merged)
    if chat.SECRET_TEXT.search("\n".join(ln[1:] for ln in patch.splitlines() if ln.startswith("+") and not ln.startswith("+++"))):
        return done("refused", "the change adds secret-looking content")
    violations = worktrees.audit_reward_hacking(files, patch, protect_tests=protect_tests or bool(entry.get("protect_tests")))
    if violations:
        res["diagnostics"] = violations
        return done("refused", violations[0]["message"])

    # 3 · verify exactly the merged tree, in a checkout nobody else uses
    stage = root / ".harness" / "landing" / f"{clean}-{os.getpid()}-{int(time.time() * 1000) % 10_000_000}"
    stage.parent.mkdir(parents=True, exist_ok=True)
    try:
        rc, out = _git(root, "worktree", "add", "--detach", str(stage), onto)
        if rc == 0:
            rc, out = _git(stage, "read-tree", "--reset", "-u", merged)
        if rc != 0:
            return done("refused", f"could not create the staging copy: {out.strip()[-240:]}")
        worktrees._copy_worktreeinclude(root, stage)
        t0 = time.monotonic()
        code, out = worktrees._run([a.replace(worktrees.PROJECT_SLOT, str(root)) for a in verify], stage, timeout=timeout,
                                   env={**os.environ, "CAOS_PROJECT_ROOT": str(root), "CAOS_LANDING": "1"})
        res["verify"] = {"command": list(verify), "exit": code, "seconds": round(time.monotonic() - t0, 1),
                         "tail": "(redacted: secret-like output)" if chat.SECRET_TEXT.search(out) else out[-2000:]}
        if code != 0:
            return done("verify_failed", f"`{' '.join(verify)}` exited {code}")
    finally:
        if stage.exists():
            _git(root, "worktree", "remove", "--force", str(stage))
            shutil.rmtree(stage, ignore_errors=True)
        _git(root, "worktree", "prune")
    res["tree"] = merged
    if dry_run:
        return done("verified", f"{len(files)} file(s) merge cleanly and pass the verify command; the branch was not moved (dry run)")

    # 4 · one commit, then one compare-and-swap: the branch points at the verified tree, or it did not move. The commit is written
    #     from the tree id that was checked out for verification, not from the staging folder: whatever the verify command left
    #     behind there (caches, build output, even edits) cannot reach the branch.
    msg = (f"Land {clean}: {len(files)} file(s)\n\nHarness-Worktree: {clean}\nHarness-Reviewed-By: {reviewed_by}\n"
           f"Harness-Verified: {' '.join(verify)[:200]} (exit 0, {res['verify']['seconds']} s)\nHarness-Tree: {merged}\n")
    rc, out = _git(root, "commit-tree", merged, "-p", onto, "-p", theirs, "-m", msg)
    if rc != 0:
        return done("refused", f"could not write the commit: {out.strip()[-200:]}")
    commit = out.strip()
    rc, out = _git(root, "update-ref", "-m", f"harness: land {clean}", REF, commit, parent or ZERO)
    if rc != 0:
        return done("drifted", f"{BRANCH} moved while the change was being verified: nothing was integrated, run it again")
    res["commit"] = commit
    return done("landed", f"{len(files)} file(s) on {BRANCH} at {commit[:12]}; your branch and folder are untouched")


def undo(repo_root: Path, expected: str | None = None) -> dict:
    """Takes the last landing off the branch: the ref goes back to its first parent, by compare-and-swap. The commit stays in the
    object store (and in the reflog), so an undo can itself be undone. Before the first landing's parent there is nothing to go to:
    the branch is deleted."""
    root = repo_root.resolve()
    with _LOCK:
        cur = tip(root)
        if not cur or (expected and cur != expected):
            return {"ok": False, "reason": "nothing landed" if not cur else f"{BRANCH} is not at {expected[:12]} any more", "tip": cur}
        if _checked_out(root):
            return {"ok": False, "reason": f"{BRANCH} is checked out in a working tree", "tip": cur}
        prev = _rev(root, f"{cur}^1")
        first = _TRAILER.search(_git(root, "log", "-1", "--format=%B", prev)[1]) is None if prev else True   # the parent is not a landing: it is where the branch started
        rc, _ = _git(root, "update-ref", "-d", REF, cur) if first else _git(root, "update-ref", "-m", "harness: undo", REF, prev, cur)
        return {"ok": rc == 0, "reason": "" if rc == 0 else "the branch moved meanwhile", "tip": tip(root), "undone": cur if rc == 0 else None}


def audit(repo_root: Path, limit: int = 200) -> list[dict]:
    """Every landing on the branch, newest first, re-read from git: who reviewed it, what verified it, and whether the commit's tree
    is the tree its trailer says was verified (`intact`). A commit someone put on the branch by hand, above a landing, shows as
    `foreign`: from there up, the branch is no longer only verified work."""
    root = repo_root.resolve()
    if not tip(root):
        return []
    out, last = [], -1
    for i, cur in enumerate(_git(root, "rev-list", "--first-parent", f"--max-count={int(limit)}", REF)[1].split()):
        t = dict(_TRAILER.findall(_git(root, "log", "-1", "--format=%B", cur)[1]))
        parents = _git(root, "log", "-1", "--format=%P", cur)[1].split()
        mine = "Harness-Tree" in t
        if mine:
            last = i
        out.append({"commit": cur, "worktree": t.get("Harness-Worktree"), "reviewed_by": t.get("Harness-Reviewed-By"), "verified": t.get("Harness-Verified"),
                    "intact": mine and _rev(root, f"{cur}^{{tree}}") == t["Harness-Tree"] and len(parents) == 2 and bool(t.get("Harness-Reviewed-By")),
                    "foreign": not mine})
    return out[:last + 1]   # below the oldest landing is the history the branch started from: not ours to judge


def overview(repo_root: Path, limit: int = 50) -> dict:
    """What the branch holds, for a screen: its landings and how far it is from the checked-out branch."""
    root = repo_root.resolve()
    cur = tip(root)
    files: list[dict] = []
    if cur:
        _, num = _git(root, "diff", "--numstat", "HEAD", cur)
        for ln in num.splitlines():
            parts = ln.split("\t")
            if len(parts) == 3:
                files.append({"path": parts[2], "added": int(parts[0]) if parts[0].isdigit() else 0, "removed": int(parts[1]) if parts[1].isdigit() else 0})
    entries = audit(root, limit)
    for e in entries:
        e["at"] = int(_git(root, "log", "-1", "--format=%ct", e["commit"])[1].strip() or 0)
    return {"branch": BRANCH, "tip": cur, "base": worktrees.current_branch(root), "entries": entries, "files": files[:200],
            "checked_out": _checked_out(root) if cur else False}


def diff(repo_root: Path, max_bytes: int = 96_000) -> str:
    """Everything on the branch that the checked-out branch does not have, as one unified diff with secret-looking hunks left out."""
    root = repo_root.resolve()
    cur = tip(root)
    if not cur:
        return ""
    _, out = _git(root, "diff", "--no-color", "HEAD", cur)
    out = worktrees._redact_tracked_diff(out)
    return out if len(out.encode("utf-8", errors="ignore")) <= max_bytes else out[:max_bytes] + "\n... [diff truncated]"
