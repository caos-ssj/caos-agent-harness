"""Isolated git worktrees, `.worktreeinclude` copy, safe file listing, and bounded diff inspection."""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from . import app, chat

MAX_PREVIEW_BYTES = 160_000
_META_LOCK = threading.RLock()   # serializes read-modify-write of `.harness/worktrees.json` between server threads
SKIP_DIRS = {".git", ".harness", "node_modules", "__pycache__", ".venv", "venv", "dist", ".pytest_cache"}


def _safe_key(raw: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(raw or "")).strip("-")[:48]
    if not clean:
        raise app.ConfigError("invalid worktree key")
    return clean


def is_git_repo(root: Path) -> bool:
    try:
        r = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=root, capture_output=True, text=True, timeout=2)
        return r.returncode == 0 and r.stdout.strip() == "true"
    except Exception:
        return False


def has_head(root: Path) -> bool:
    try:
        r = subprocess.run(["git", "rev-parse", "--verify", "HEAD"], cwd=root, capture_output=True, text=True, timeout=2)
        return r.returncode == 0
    except Exception:
        return False


def current_branch(root: Path) -> str | None:
    if not is_git_repo(root):
        return None
    try:
        r = subprocess.run(["git", "branch", "--show-current"], cwd=root, capture_output=True, text=True, timeout=2)
        return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "detached"
    except Exception:
        return None


def safe_workspace_files(root: Path, limit: int = 240) -> list[str]:
    """Lists regular, non-hidden, non-secret project files for `@file` attachment and the inspector."""
    root = root.resolve()
    out: list[str] = []
    for p in sorted(root.rglob("*")):
        if len(out) >= limit:
            break
        if p.is_symlink() or not p.is_file():
            continue
        rel_parts = p.relative_to(root).parts
        if any(part.startswith(".") or part in SKIP_DIRS for part in rel_parts):
            continue
        rel = Path(*rel_parts).as_posix()
        if chat.SECRET_NAMES.search(rel):
            continue
        out.append(rel)
    return out


def _untracked_diff_and_counts(root: Path, rel: str) -> tuple[str, int]:
    """Synthesizes a minimal unified diff block for a new untracked text file inside `root`."""
    if chat.SECRET_NAMES.search(rel) or any(part.startswith(".") for part in Path(rel).parts):
        return "", 0
    p = (root / rel).resolve()
    if not p.is_file() or p.is_symlink() or root.resolve() not in p.parents:
        return "", 0
    try:
        raw = p.read_bytes()[:24_000]
        text = raw.decode("utf-8", errors="strict")
    except (OSError, UnicodeDecodeError):
        return f"diff --git a/{rel} b/{rel}\nnew file (binary or unreadable)\n", 0
    if chat.SECRET_TEXT.search(text):
        return f"diff --git a/{rel} b/{rel}\nnew file (redacted: secret-like content)\n", 0
    lines = text.splitlines()
    body = "\n".join("+" + line for line in lines[:200])
    extra = "\n+... [truncated]" if len(lines) > 200 else ""
    hdr = f"diff --git a/{rel} b/{rel}\nnew file mode 100644\n--- /dev/null\n+++ b/{rel}\n@@ -0,0 +1,{len(lines)} @@\n{body}{extra}\n"
    return hdr, len(lines)


_DIFF_HEAD = re.compile(r"^diff --git a/(.+?) b/(.+)$")


def _redact_tracked_diff(text: str) -> str:
    """Keeps the unified-diff shape of `git diff` but replaces any file block that names a secret file or carries secret-like text.

    The block header stays, so the file still shows up with its path; its hunks are dropped, never partially masked.
    """
    if not text:
        return text
    blocks = re.split(r"(?m)^(?=diff --git )", text)
    out: list[str] = []
    for blk in blocks:
        if not blk:
            continue
        m = _DIFF_HEAD.match(blk.split("\n", 1)[0])
        if m:
            rel = m.group(2).strip('"')
            if chat.SECRET_NAMES.search(rel):
                blk = f"diff --git a/{rel} b/{rel}\n(redacted: secret-like file name)\n"
            elif chat.SECRET_TEXT.search(blk):
                blk = f"diff --git a/{rel} b/{rel}\n(redacted: secret-like content)\n"
        elif chat.SECRET_TEXT.search(blk):
            blk = "(redacted: secret-like content)\n"
        out.append(blk if blk.endswith("\n") else blk + "\n")
    return "".join(out)


def _find_preview(root: Path, candidates: list[str]) -> dict | None:
    """Returns the first safe HTML or SVG file among touched files for sandboxed iframe preview."""
    root = root.resolve()
    for rel in candidates:
        if not rel.lower().endswith((".html", ".htm", ".svg")):
            continue
        parts = Path(rel).parts
        if any(part in SKIP_DIRS or part.startswith(".") for part in parts):
            continue
        p = (root / rel).resolve()
        if not p.is_file() or p.is_symlink() or root not in p.parents:
            continue
        try:
            raw = p.read_bytes()
            if len(raw) > MAX_PREVIEW_BYTES:
                continue
            text = raw.decode("utf-8", errors="strict")
        except (OSError, UnicodeDecodeError):
            continue
        if chat.SECRET_TEXT.search(text):
            continue
        return {"path": rel, "kind": "svg" if rel.lower().endswith(".svg") else "html", "content": text}
    return None


def _parse_numstat(stdout: str) -> dict[str, tuple[int, int]]:
    counts: dict[str, tuple[int, int]] = {}
    for line in stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        a = int(parts[0]) if parts[0].isdigit() else 0
        d = int(parts[1]) if parts[1].isdigit() else 0
        counts[parts[2].strip()] = (a, d)
    return counts


def workspace_diff(root: Path, max_bytes: int = 64_000) -> dict:
    """Returns git diff, changed file summaries, and safe HTML/SVG preview for `root`."""
    root = root.resolve()
    git_repo = is_git_repo(root)
    if not git_repo:
        return {"git_repo": False, "branch": None, "dirty_files": [], "files": [], "diff": "", "preview": None, "path": str(root)}

    branch = current_branch(root)
    st = subprocess.run(["git", "status", "--porcelain=v1", "-uall"], cwd=root, capture_output=True, text=True, timeout=3)
    dirty = [line.strip() for line in st.stdout.splitlines() if line.strip()] if st.returncode == 0 else []

    base_cmd = ["git", "diff", "HEAD"] if has_head(root) else ["git", "diff"]
    df = subprocess.run([*base_cmd, "--no-color"], cwd=root, capture_output=True, text=True, errors="replace", timeout=4)
    ns = subprocess.run([*base_cmd, "--numstat"], cwd=root, capture_output=True, text=True, errors="replace", timeout=3)
    counts = _parse_numstat(ns.stdout if ns.returncode == 0 else "")

    files: list[dict] = []
    untracked_diffs: list[str] = []
    preview_candidates: list[str] = []

    if st.returncode == 0:
        for raw_line in st.stdout.splitlines():
            if len(raw_line) < 4:
                continue
            code = raw_line[:2].strip() or "M"
            rel = raw_line[3:].strip()
            if " -> " in rel:
                rel = rel.split(" -> ", 1)[1]
            preview_candidates.append(rel)
            if code == "??":
                udiff, added = _untracked_diff_and_counts(root, rel)
                if udiff:
                    untracked_diffs.append(udiff)
                files.append({"path": rel, "status": "added", "additions": added, "deletions": 0})
            else:
                add, rem = counts.get(rel, (0, 0))
                status = "deleted" if "D" in code else "added" if "A" in code else "modified"
                files.append({"path": rel, "status": status, "additions": add, "deletions": rem})

    tracked = _redact_tracked_diff(df.stdout) if df.returncode == 0 else ""
    combined_diff = (tracked + ("\n" if tracked and untracked_diffs else "") + "\n".join(untracked_diffs)).strip()
    if len(combined_diff.encode("utf-8", errors="ignore")) > max_bytes:
        combined_diff = combined_diff[:max_bytes] + "\n... [diff truncated at 64 KB]"

    return {
        "git_repo": True,
        "branch": branch,
        "dirty_files": dirty,
        "files": files,
        "diff": combined_diff,
        "preview": _find_preview(root, preview_candidates),
        "path": str(root),
    }


def _meta_file(repo_root: Path) -> Path:
    return repo_root / ".harness" / "worktrees.json"


def _load_meta(repo_root: Path) -> dict[str, dict]:
    f = _meta_file(repo_root)
    if not f.is_file():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_meta(repo_root: Path, data: dict[str, dict]) -> None:
    f = _meta_file(repo_root)
    f.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=f.parent, prefix=f.name + ".", suffix=".tmp")   # same directory, so os.replace stays atomic
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as h:
            h.write(json.dumps(data, indent=2, ensure_ascii=False))
            h.flush()
            os.fsync(h.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, f)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _copy_worktreeinclude(repo_root: Path, wt_path: Path) -> list[str]:
    """Copies the non-secret, non-hidden regular files matched by `.worktreeinclude` globs from repo root into a new worktree.

    Secret names, dot-prefixed segments, symlinks and anything resolving outside the project are skipped, whatever the pattern says.
    """
    inc = repo_root / ".worktreeinclude"
    if not inc.is_file() or inc.is_symlink():
        return []
    copied: list[str] = []
    patterns = [ln.strip() for ln in inc.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if not patterns:
        return []
    root_res = repo_root.resolve()
    wt_res = wt_path.resolve()
    for p in sorted(root_res.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        rel_parts = p.relative_to(root_res).parts
        if any(part in SKIP_DIRS or part.startswith(".") for part in rel_parts):    # same rule as `safe_workspace_files`
            continue
        rel = Path(*rel_parts).as_posix()
        if chat.SECRET_NAMES.search(rel):
            continue
        if root_res not in p.resolve().parents:                                      # a linked directory must not lead out of the project
            continue
        if any(fnmatch.fnmatch(rel, pat) for pat in patterns):
            dst = wt_path / rel
            if dst.exists() or dst.is_symlink():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            if wt_res not in dst.parent.resolve().parents and dst.parent.resolve() != wt_res:
                continue
            shutil.copy2(p, dst)
            copied.append(rel)
    return copied


def active_worktrees(repo_root: Path) -> dict[str, dict]:
    meta = _load_meta(repo_root.resolve())
    return {k: v for k, v in meta.items() if Path(v.get("path", "")).is_dir()}


def get(repo_root: Path, key: str) -> dict | None:
    clean = _safe_key(key)
    info = _load_meta(repo_root.resolve()).get(clean)
    if info and Path(info.get("path", "")).is_dir():
        return info
    return None


def ensure(repo_root: Path, key: str, start: str | None = None) -> dict:
    with _META_LOCK:
        return _ensure(repo_root, key, start)


def _ensure(repo_root: Path, key: str, start: str | None = None) -> dict:
    """Creates or reuses an isolated git worktree at `.harness/worktrees/<key>` incrementally. A new one is cut from `start`
    (a commit) when given, otherwise from HEAD."""
    repo_root = repo_root.resolve()
    clean = _safe_key(key)
    if not is_git_repo(repo_root):
        raise app.ConfigError("worktree isolation requires a git repository")
    if not has_head(repo_root):
        raise app.ConfigError("worktree isolation needs at least one commit in this git repository")

    meta = _load_meta(repo_root)
    existing = meta.get(clean)
    if existing and Path(existing.get("path", "")).is_dir():
        return existing

    wt_path = repo_root / ".harness" / "worktrees" / clean
    wt_path.parent.mkdir(parents=True, exist_ok=True)
    branch = f"caos/{clean}"
    pre_existing = subprocess.run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=repo_root, timeout=2).returncode == 0
    cmd = ["git", "worktree", "add", str(wt_path), branch] if pre_existing else ["git", "worktree", "add", "-b", branch, str(wt_path), start or "HEAD"]
    res = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True, timeout=10)
    if res.returncode != 0:
        raise app.ConfigError(f"could not create worktree: {(res.stderr or res.stdout).strip()[:240]}")

    included = _copy_worktreeinclude(repo_root, wt_path)
    entry = {
        "key": clean,
        "path": str(wt_path),
        "branch": branch,
        "was_branch_pre_existing": pre_existing,
        "included_files": included,
        "created_at": time.time(),
    }
    meta[clean] = entry
    _save_meta(repo_root, meta)
    return entry


def discard(repo_root: Path, key: str) -> dict:
    with _META_LOCK:
        return _discard(repo_root, key)


def _discard(repo_root: Path, key: str) -> dict:
    """Removes a managed worktree; deletes its branch ONLY when it did not pre-exist."""
    repo_root = repo_root.resolve()
    clean = _safe_key(key)
    meta = _load_meta(repo_root)
    entry = meta.get(clean)
    if not entry:
        raise app.ConfigError(f"no isolated worktree '{clean}'")
    wt_path = Path(entry["path"])
    if wt_path.exists():
        unlock_eval_paths(wt_path)
        res = subprocess.run(["git", "worktree", "remove", "--force", str(wt_path)], cwd=repo_root, capture_output=True, text=True, timeout=10)
        if res.returncode != 0:
            raise app.ConfigError(f"could not remove worktree: {(res.stderr or res.stdout).strip()[:240]}")
    subprocess.run(["git", "worktree", "prune"], cwd=repo_root, capture_output=True, text=True, timeout=5)
    branch_deleted = False
    if not entry.get("was_branch_pre_existing", True) and entry.get("branch"):
        del_res = subprocess.run(["git", "branch", "-D", entry["branch"]], cwd=repo_root, capture_output=True, text=True, timeout=5)
        branch_deleted = del_res.returncode == 0
    meta.pop(clean, None)
    _save_meta(repo_root, meta)
    return {"key": clean, "removed": True, "branch_deleted": branch_deleted, "preserved_preexisting_branch": bool(entry.get("was_branch_pre_existing"))}


# ── Inspecting, exporting and tidying isolated worktrees (nothing here merges into your branch) ──────────────

def _git(cwd: Path, *args: str, timeout: float = 6) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, errors="replace", timeout=timeout)
        return r.returncode, r.stdout
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def inspect(repo_root: Path, key: str) -> dict:
    """Where an isolated worktree stands against the branch it came from: commits ahead and behind, files it changed,
    uncommitted work, and whether everything in it is already in the base (`integrated`, which makes it safe to tidy away)."""
    repo_root = repo_root.resolve()
    entry = get(repo_root, key)
    if not entry:
        raise app.ConfigError(f"no isolated worktree '{_safe_key(key)}'")
    wt, branch = Path(entry["path"]), entry.get("branch") or "HEAD"
    base = current_branch(repo_root)
    base = base if base and base != "detached" else "HEAD"
    rc, counts = _git(repo_root, "rev-list", "--left-right", "--count", f"{base}...{branch}")
    behind, ahead = (int(n) for n in counts.split()) if rc == 0 and len(counts.split()) == 2 else (0, 0)
    _, status = _git(wt, "status", "--porcelain=v1", "-uall")
    dirty = [ln for ln in status.splitlines() if ln.strip()]
    rc, _ = _git(repo_root, "merge-base", "--is-ancestor", branch, base)
    _, num = _git(repo_root, "diff", "--numstat", f"{base}...{branch}")
    files = {}
    for ln in num.splitlines():
        parts = ln.split("\t")
        if len(parts) == 3:
            files[parts[2]] = {"path": parts[2], "added": int(parts[0]) if parts[0].isdigit() else 0, "removed": int(parts[1]) if parts[1].isdigit() else 0, "committed": True}
    for ln in dirty:
        rel = ln[3:].strip().split(" -> ")[-1]
        files.setdefault(rel, {"path": rel, "added": 0, "removed": 0, "committed": False})
    return {
        "key": entry["key"], "branch": branch, "base": base, "path_name": wt.name, "ahead": ahead, "behind": behind,
        "dirty": len(dirty), "integrated": rc == 0 and not dirty, "files": list(files.values())[:80],
        "created_at": entry.get("created_at"),
    }


def export_patch(repo_root: Path, key: str | None = None, max_bytes: int = 2_000_000) -> dict:
    """Writes `.harness/exports/<name>-<time>.patch`: what the worktree (or the project) changed, as a unified diff
    that `git apply` takes. Secret-looking files and hunks are left out, as in the diff view. Your branch is not touched."""
    repo_root = repo_root.resolve()
    target, label, base_note = repo_root, repo_root.name, ""
    committed = ""
    if key:
        entry = get(repo_root, key)
        if not entry:
            raise app.ConfigError(f"no isolated worktree '{_safe_key(key)}'")
        target, label = Path(entry["path"]), entry["key"]
        base = current_branch(repo_root)
        base = base if base and base != "detached" else "HEAD"
        rc, out = _git(repo_root, "diff", "--no-color", f"{base}...{entry.get('branch') or 'HEAD'}", timeout=10)
        committed = _redact_tracked_diff(out) if rc == 0 else ""
    work = workspace_diff(target, max_bytes=max_bytes).get("diff") or ""
    text = (committed + ("\n" if committed and work else "") + work).strip()
    if not text:
        raise app.ConfigError("nothing to export: no changes")
    text = text[:max_bytes] + "\n"
    exports = repo_root / ".harness" / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    name = f"{_safe_key(label)}-{time.strftime('%Y%m%d-%H%M%S')}.patch"
    (exports / name).write_text(text, encoding="utf-8")
    return {"ok": True, "filename": name, "relative_path": f".harness/exports/{name}", "size_bytes": len(text.encode()), "files": len(re.findall(r"(?m)^diff --git ", text)), "base_note": base_note}


def integrated_worktrees(repo_root: Path) -> list[str]:
    """Keys of worktrees with nothing of their own left: clean, and every commit already in the base branch."""
    out = []
    for key in active_worktrees(repo_root):
        try:
            if inspect(repo_root, key)["integrated"]:
                out.append(key)
        except app.ConfigError:
            continue
    return out


# ── Landing gate: the only way a worktree's changes reach the project folder ─────────────────────────────────
#
#   worktree ──patch──▶ staging copy of the project as it is now ──verify command──▶ project folder
#
# What is verified is exactly what lands: the staging copy holds the project as it stands on disk (HEAD plus its
# uncommitted and untracked work) with the patch on top, and after applying the patch to the project its tree id
# must equal the one that was verified, or the patch is reversed. Nothing is committed, merged or pushed: the
# change lands as uncommitted work, so the commit stays a human decision.

LAND_STATUSES = ("landed", "verified", "empty", "refused", "conflict", "verify_failed", "drifted", "rolled_back")
_TAIL = 2000
_LAND_LOCK = threading.Lock()
PROJECT_SLOT = "{project}"   # in a verify command: replaced by the project folder


def _run(cmd: list[str], cwd: Path, timeout: float = 60, env: dict | None = None) -> tuple[int, str]:
    """Runs one argv list (never a shell) in its own process group; returns (exit code, combined output). 124 on timeout."""
    try:
        p = subprocess.Popen(app.resolve_argv(cmd), cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, errors="replace", **app.popen_group_kwargs())
    except OSError as e:
        return 127, f"{type(e).__name__}: {e}"
    try:
        out, _ = p.communicate(timeout=timeout)
        return p.returncode, out or ""
    except subprocess.TimeoutExpired:
        app.terminate_process_tree(p, grace=5)
        try:
            out, _ = p.communicate(timeout=2)
        except Exception:
            out = ""
        return 124, (out or "") + f"\n[timed out after {timeout:g} s]"


def snapshot_tree(root: Path) -> str:
    """The git tree id of `root` as it stands on disk (HEAD + uncommitted + untracked, ignoring what .gitignore ignores and
    `.harness/`), computed in a throwaway index: the real index, the branch and the files are not touched."""
    fd, idx = tempfile.mkstemp(prefix="caos-land-", suffix=".idx")
    os.close(fd)
    os.unlink(idx)   # git wants to create the index file itself
    env = {**os.environ, "GIT_INDEX_FILE": idx}
    try:
        # `.harness/` (boards, traces, other worktrees) is dropped from the throwaway index whether or not .gitignore lists it
        for args in (["read-tree", "HEAD"], ["add", "-A", "--", "."], ["rm", "-r", "-q", "-f", "--cached", "--ignore-unmatch", "--", ".harness"]):
            rc, out = _run(["git", *args], root, env=env)
            if rc != 0:
                raise app.ConfigError(f"could not snapshot {root.name}: {out.strip()[:240]}")
        rc, out = _run(["git", "write-tree"], root, env=env)
        if rc != 0 or not out.strip():
            raise app.ConfigError(f"could not snapshot {root.name}: {out.strip()[:240]}")
        return out.strip().splitlines()[-1]
    finally:
        for f in (idx, idx + ".lock"):
            try:
                os.unlink(f)
            except OSError:
                pass


def _added_lines(patch: str) -> str:
    return "\n".join(ln[1:] for ln in patch.splitlines() if ln.startswith("+") and not ln.startswith("+++"))


PROTECTED_CONFIG_FILES = ("harness.toml", "thresholds.json", "pytest.ini")
EVAL_PATH_PREFIXES = ("tests/", "test/", "evals/", "eval/", "benchmarks/")
EVAL_FILE_NAMES = ("conftest.py",)
_SKIP_INJECTION_RE = re.compile(
    r"^\+.*(?:@pytest\.mark\.(?:skip|skipif|xfail)\b|pytest\.(?:skip|xfail)\s*\(|@unittest\.skip|unittest\.SkipTest)",
    re.M,
)
_ASSERT_REMOVED_RE = re.compile(r"^-\s*assert\b", re.M)
_ASSERT_ADDED_RE = re.compile(r"^\+\s*assert\b", re.M)


def is_eval_path(rel_path: str) -> bool:
    norm = rel_path.replace("\\", "/").lstrip("./")
    base = norm.rsplit("/", 1)[-1]
    return norm.startswith(EVAL_PATH_PREFIXES) or base in EVAL_FILE_NAMES or (base.startswith("test_") and base.endswith(".py"))


def format_diagnostic(what: str, why: str, fix: str) -> str:
    """Actionable 3-part error format (WHAT / WHY / FIX) for deterministic agent self-correction."""
    return f"WHAT: {what} | WHY: {why} | FIX: {fix}"


def lock_eval_paths(wt_path: Path) -> list[str]:
    """Marks existing test/eval files and harness config inside `wt_path` read-only (0o444/0o555) so an isolated worker cannot tamper with them."""
    wt_res = wt_path.resolve()
    locked: list[str] = []
    if not wt_res.is_dir():
        return locked
    dirs_to_lock: list[Path] = []
    for p in sorted(wt_res.rglob("*")):
        if p.is_symlink():
            continue
        rel_parts = p.relative_to(wt_res).parts
        if any(part in SKIP_DIRS or part.startswith(".") for part in rel_parts):
            continue
        rel = Path(*rel_parts).as_posix()
        if rel in PROTECTED_CONFIG_FILES or is_eval_path(rel):
            if p.is_file():
                try:
                    os.chmod(p, 0o444)
                    locked.append(rel)
                except OSError:
                    pass
            elif p.is_dir():
                dirs_to_lock.append(p)
    for d in sorted(dirs_to_lock, key=lambda x: len(x.parts), reverse=True):
        try:
            os.chmod(d, 0o555)
        except OSError:
            pass
    return locked


def unlock_eval_paths(wt_path: Path) -> None:
    """Restores write permissions on directories and files under `wt_path` that were locked by `lock_eval_paths`."""
    wt_res = wt_path.resolve()
    if not wt_res.is_dir():
        return
    for root_dir, dirs, files in os.walk(wt_res):
        rp = Path(root_dir)
        try:
            mode = rp.stat().st_mode
            if not (mode & 0o200):
                os.chmod(rp, mode | 0o200)
        except OSError:
            pass
        for name in files:
            fp = rp / name
            if fp.is_symlink():
                continue
            try:
                mode = fp.stat().st_mode
                if not (mode & 0o200):
                    os.chmod(fp, mode | 0o200)
            except OSError:
                pass


def _split_patch_by_file(patch: str) -> dict[str, str]:
    per_file: dict[str, list[str]] = {}
    current: str | None = None
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            parts = line.split(" b/", 1)
            current = parts[1].strip() if len(parts) == 2 else None
            if current:
                per_file.setdefault(current, [])
        if current is not None:
            per_file[current].append(line)
    return {k: "\n".join(v) for k, v in per_file.items()}


def audit_reward_hacking(files: list[str], patch: str, protect_tests: bool = False) -> list[dict]:
    """Audits a worktree diff before verification to block reward hacking:
    1. Modifying harness/threshold config (`harness.toml`, `thresholds.json`, `pytest.ini`).
    2. Modifying any protected eval/test file when `protect_tests=True`.
    3. Injecting skip/xfail markers (`@pytest.mark.skip`, `pytest.skip(`, `@pytest.mark.xfail`) into test/eval files.
    4. Deleting test files or weakening assertions (removing `assert` statements without replacing them).
    Returns a list of structured diagnostic dicts (`code`, `file`, `what`, `why`, `fix`, `message`)."""
    diagnostics: list[dict] = []
    per_file = _split_patch_by_file(patch)

    def add(code: str, file: str, what: str, why: str, fix: str) -> None:
        diagnostics.append({
            "code": code,
            "file": file,
            "what": what,
            "why": why,
            "fix": fix,
            "message": format_diagnostic(what, why, fix),
        })

    for f in files:
        norm = f.replace("\\", "/").lstrip("./")
        if norm in PROTECTED_CONFIG_FILES:
            add(
                "harness_config_tampered",
                norm,
                f"Worktree modified protected configuration file '{norm}'",
                "Agents must not alter the verification command, thresholds, or test runner config to pass the gate.",
                f"Revert '{norm}' (`git checkout -- {norm}`) and make the implementation satisfy the existing configuration.",
            )
            continue
        if not is_eval_path(norm):
            continue
        f_patch = per_file.get(norm, "")
        if protect_tests:
            add(
                "protected_eval_modified",
                norm,
                f"Worktree modified read-only evaluation/test file '{norm}'",
                "When `protect_tests` is enabled, the test suite is a fixed oracle and cannot be edited by the worker.",
                f"Revert changes to '{norm}' (`git checkout -- {norm}`) and fix the production module under test instead.",
            )
            continue
        if "\ndeleted file mode " in f_patch or f_patch.startswith("deleted file mode "):
            add(
                "test_file_deleted",
                norm,
                f"Worktree deleted existing test/evaluation file '{norm}'",
                "Deleting tests to make the verification command pass is reward hacking.",
                f"Restore '{norm}' (`git checkout HEAD -- {norm}`) and fix the failing code.",
            )
            continue
        if _SKIP_INJECTION_RE.search(f_patch):
            add(
                "test_skip_injected",
                norm,
                f"Worktree injected skip/xfail marker in '{norm}'",
                "Skipping or xfailing tests hides regressions instead of solving the task.",
                f"Remove `@pytest.mark.skip` / `pytest.skip` / `xfail` from '{norm}' and make the test pass genuinely.",
            )
            continue
        removed_asserts = len(_ASSERT_REMOVED_RE.findall(f_patch))
        added_asserts = len(_ASSERT_ADDED_RE.findall(f_patch))
        if removed_asserts > added_asserts:
            add(
                "assertions_weakened",
                norm,
                f"Worktree weakened assertions in '{norm}' (removed {removed_asserts}, added {added_asserts})",
                "Removing assertions from existing tests lowers verification coverage to fake a green build.",
                f"Keep the original assertions in '{norm}' (or replace them with at least as many assertions) and fix the code under test.",
            )
    return diagnostics


def change(repo_root: Path, key: str, max_bytes: int = 48_000) -> dict:
    """What worktree `key` would land, for a reviewer: {"files", "diff", "tree"}. The same change the gate applies (committed or not,
    local include copies left out), with secret-looking files and hunks redacted. `tree` identifies the worktree's state."""
    repo_root = repo_root.resolve()
    entry = get(repo_root, key)
    if not entry:
        raise app.ConfigError(f"no isolated worktree '{_safe_key(key)}'")
    rc, base = _git(repo_root, "merge-base", "HEAD", entry.get("branch") or "HEAD")
    if rc != 0 or not base.strip():
        raise app.ConfigError("the worktree shares no history with the project's HEAD")
    tree = snapshot_tree(Path(entry["path"]))
    skip = [f":(exclude,literal){f}" for f in entry.get("included_files") or []]
    _, names = _git(repo_root, "diff", "--name-only", "-z", base.strip(), tree, "--", ".", *skip, timeout=30)
    _, diff = _git(repo_root, "diff", "--no-color", base.strip(), tree, "--", ".", *skip, timeout=60)
    diff = _redact_tracked_diff(diff)
    if len(diff.encode("utf-8", errors="ignore")) > max_bytes:
        diff = diff[:max_bytes] + "\n... [diff truncated]"
    return {"files": [n for n in names.split("\0") if n], "diff": diff, "tree": tree}


def land(repo_root: Path, key: str, verify: list[str], timeout: float = 900, dry_run: bool = False, protect_tests: bool = False) -> dict:
    """Passes the changes of worktree `key` through the gate and, only if every step holds, applies them to the project folder.
    With `dry_run` it stops after the verify command passed (status `verified`) and never writes to the project folder.

    Returns {"status": one of LAND_STATUSES, "reason", "files", "verify": {"command", "exit", "seconds", "tail"}, "tree"}.
    Any status other than `landed` leaves the project folder exactly as it was. The worktree itself is never modified.
    """
    with _LAND_LOCK:   # one landing at a time per process; the metadata lock is only taken to record the result
        return _land(repo_root.resolve(), key, verify, timeout, dry_run, protect_tests)


def _land(repo_root: Path, key: str, verify: list[str], timeout: float, dry_run: bool = False, protect_tests: bool = False) -> dict:
    clean = _safe_key(key)
    entry = get(repo_root, clean)
    if not entry:
        raise app.ConfigError(f"no isolated worktree '{clean}'")
    if not (isinstance(verify, (list, tuple)) and verify and all(isinstance(x, str) and x for x in verify)):
        raise app.ConfigError("landing needs a verify command (a non-empty list of strings): without one it is not a gate")
    wt = Path(entry["path"])
    res: dict = {"key": clean, "status": "refused", "reason": "", "files": [], "verify": None, "tree": None}

    def done(status: str, reason: str = "") -> dict:
        res["status"], res["reason"] = status, reason[:600]
        return res

    rc, base = _git(repo_root, "merge-base", "HEAD", entry.get("branch") or "HEAD")
    if rc != 0 or not base.strip():
        return done("refused", "the worktree shares no history with the project's HEAD")
    project_tree, wt_tree = snapshot_tree(repo_root), snapshot_tree(wt)
    skip = [f":(exclude,literal){f}" for f in entry.get("included_files") or []]   # copies of local files, not the agent's work
    rc, names = _git(repo_root, "diff", "--name-only", "-z", base.strip(), wt_tree, "--", ".", *skip, timeout=30)
    files = [n for n in names.split("\0") if n]
    if rc != 0:
        return done("refused", "could not compute what the worktree changed")
    if not files:
        return done("empty", "the worktree changed nothing")
    res["files"] = files[:200]
    secret = [f for f in files if chat.SECRET_NAMES.search(f)]
    if secret:
        return done("refused", f"the change touches secret-looking files: {', '.join(secret[:5])}")
    landing = repo_root / ".harness" / "landing"
    landing.mkdir(parents=True, exist_ok=True)
    stage = landing / f"{clean}-{os.getpid()}-{int(time.time() * 1000) % 10_000_000}"
    patch_file = landing / (stage.name + ".patch")
    try:
        # git writes the patch itself, byte for byte: a binary or non-UTF-8 file must not pass through a text decoder
        rc, out = _run(["git", "diff", "--binary", "--full-index", "--no-color", f"--output={patch_file}", base.strip(), wt_tree, "--", ".", *skip], repo_root)
        if rc != 0 or not patch_file.is_file() or patch_file.stat().st_size == 0:
            return done("refused", f"could not build the patch: {out.strip()[-240:]}")
        os.chmod(patch_file, 0o600)
        patch_text = patch_file.read_text(encoding="utf-8", errors="replace")
        if chat.SECRET_TEXT.search(_added_lines(patch_text)):
            return done("refused", "the change adds secret-looking content")
        violations = audit_reward_hacking(files, patch_text, protect_tests=protect_tests or bool(entry.get("protect_tests")))
        if violations:
            res["diagnostics"] = violations
            return done("refused", violations[0]["message"])
        rc, out = _run(["git", "worktree", "add", "--detach", str(stage), "HEAD"], repo_root)
        if rc != 0:
            return done("refused", f"could not create the staging copy: {out.strip()[-240:]}")
        rc, out = _run(["git", "read-tree", "--reset", "-u", project_tree], stage)   # the project as it is now, uncommitted work included
        if rc != 0:
            return done("refused", f"could not reproduce the project in the staging copy: {out.strip()[-240:]}")
        rc, out = _run(["git", "apply", "--index", "--check", str(patch_file)], stage)
        if rc != 0:
            return done("conflict", f"the change does not apply cleanly on the project as it is now: {out.strip()[-400:]}")
        rc, out = _run(["git", "apply", "--index", str(patch_file)], stage)
        if rc != 0:
            return done("conflict", out.strip()[-400:])
        rc, out = _run(["git", "write-tree"], stage)
        verified_tree = out.strip()
        if rc != 0 or not verified_tree:
            return done("refused", "could not record the tree to verify")
        _copy_worktreeinclude(repo_root, stage)

        # The staging copy has no ignored files (.venv, node_modules): `{project}` in the command points at the project folder,
        # so the tools installed there can be used while the code under test is the staging copy (the working directory).
        t0 = time.monotonic()
        code, out = _run([a.replace(PROJECT_SLOT, str(repo_root)) for a in verify], stage, timeout=timeout,
                         env={**os.environ, "CAOS_PROJECT_ROOT": str(repo_root), "CAOS_LANDING": "1"})
        res["verify"] = {"command": list(verify), "exit": code, "seconds": round(time.monotonic() - t0, 1),
                         "tail": "(redacted: secret-like output)" if chat.SECRET_TEXT.search(out) else out[-_TAIL:]}
        if code != 0:
            return done("verify_failed", f"`{' '.join(verify)}` exited {code}")
        if dry_run:
            res["tree"] = verified_tree
            return done("verified", f"{len(files)} file(s) apply cleanly and pass the verify command; nothing was applied (dry run)")

        # From here on the project folder is written. It must still be what was verified against, and end as what was verified.
        if snapshot_tree(repo_root) != project_tree:
            return done("drifted", "the project folder changed while the change was being verified: nothing was applied, run the gate again")
        rc, out = _run(["git", "apply", "--check", str(patch_file)], repo_root)
        if rc != 0:
            return done("conflict", f"the change does not apply on the project folder: {out.strip()[-400:]}")
        rc, out = _run(["git", "apply", str(patch_file)], repo_root)
        after = snapshot_tree(repo_root) if rc == 0 else None
        if rc != 0 or after != verified_tree:
            back, back_out = (_run(["git", "apply", "-R", str(patch_file)], repo_root) if rc == 0 else (0, ""))
            restored = snapshot_tree(repo_root) == project_tree
            why = out.strip()[-300:] if rc != 0 else "the project did not end as the tree that was verified"
            return done("rolled_back", f"{why}; " + ("the project folder is back as it was" if restored and back == 0
                                                      else f"ROLLBACK INCOMPLETE, check `git status`: {back_out.strip()[-200:]}"))
        res["tree"] = verified_tree
        with _META_LOCK:
            meta = _load_meta(repo_root)
            if clean in meta:
                meta[clean]["landed"] = {"at": time.time(), "tree": verified_tree, "files": len(files), "verify": list(verify)}
                _save_meta(repo_root, meta)
        return done("landed", f"{len(files)} file(s) applied to the project folder as uncommitted work; verified tree {verified_tree[:12]}")
    finally:
        if stage.exists():
            _run(["git", "worktree", "remove", "--force", str(stage)], repo_root)
            shutil.rmtree(stage, ignore_errors=True)
        _run(["git", "worktree", "prune"], repo_root)
        try:
            patch_file.unlink()
        except OSError:
            pass
