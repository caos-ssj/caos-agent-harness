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


def ensure(repo_root: Path, key: str) -> dict:
    with _META_LOCK:
        return _ensure(repo_root, key)


def _ensure(repo_root: Path, key: str) -> dict:
    """Creates or reuses an isolated git worktree at `.harness/worktrees/<key>` incrementally."""
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
    cmd = ["git", "worktree", "add", str(wt_path), branch] if pre_existing else ["git", "worktree", "add", "-b", branch, str(wt_path), "HEAD"]
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
