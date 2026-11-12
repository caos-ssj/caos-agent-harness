"""Share Pack generator, pre-push leak doctor and optional Google Drive upload.

The pack is built fail-closed: a file holding a credential is left out, a private path is rewritten in the copy (never in
your files), `harness.toml` loses every secret-looking value, and the finished bundle is scanned once more before it is sealed.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import tarfile
import zipfile
from pathlib import Path

from . import providers, skills

SECRET_FILE_NAMES = re.compile(r"(^|/)(\.env(?!\.example$|\.sample$)[^/]*|.*\.(pem|key|p12|pfx|db|sqlite3?)|id_[a-z0-9_]+)$", re.I)
PRIVATE_RE = re.compile(r"(?:/home/(?!usuario\b|user\b|developer\b|ubuntu\b)\w+|/Users/(?!username\b|user\b)\w+|[A-Z]:\\\\Users\\\\(?!username\b|user\b)\w+|\.obsidian/)")
FORMATS = ("zip", "dir", "tar.gz")
REDACTED = "[redacted]"
PATH_PLACEHOLDER = "/path/to/workspace"
MAX_SCAN_BYTES = 512_000
SKIP_DIRS = {".git", ".harness", "node_modules", "__pycache__", ".venv", "venv", ".pytest_cache", "dist"}


def _current_user_pattern() -> re.Pattern | None:
    """Builds a runtime regex for the active local user home folder without hardcoding usernames."""
    uname = Path.home().name
    if len(uname) >= 3 and uname not in ("root", "user", "usuario", "runner", "ubuntu"):
        return re.compile(rf"(?:/home/|/Users/|\\\\Users\\\\){re.escape(uname)}\b")
    return None


def normalize_format(fmt: str | None) -> str:
    """`zip`, `dir` or `tar.gz`. Anything else is an error, not a quiet zip."""
    f = (fmt or "zip").strip().lower()
    if f not in FORMATS:
        raise ValueError(f"unknown format '{fmt}': use {', '.join(FORMATS)}")
    return f


def _iter_workspace_files(root: Path, selected: list[str] | None = None, limit: int = 800) -> list[Path]:
    root = root.resolve()
    out: list[Path] = []
    if selected:
        for rel in selected:
            cand = (root / rel).resolve()
            if (root in cand.parents or cand == root) and cand.is_file():
                out.append(cand)
        return out[:limit]
    for cur, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for fn in sorted(files):
            p = Path(cur) / fn
            if p.is_symlink():
                continue
            out.append(p)
            if len(out) >= limit:
                return out
    return out


def _read_text(p: Path) -> str | None:
    """The text of a file the scanner can read; None for a big or binary one (those are reported as unscanned)."""
    try:
        if p.stat().st_size > MAX_SCAN_BYTES:
            return None
        return p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _redact_paths(line: str, user_re: re.Pattern | None) -> str:
    line = PRIVATE_RE.sub(lambda m: ".obsidian-redacted/" if m.group(0).startswith(".obsidian") else PATH_PLACEHOLDER, line)
    return user_re.sub(PATH_PLACEHOLDER, line) if user_re else line


def redact_text(text: str, *, secrets: bool = False) -> tuple[str, list[dict]]:
    """Rewrites private paths (and, with `secrets`, every secret-looking value) line by line.
    Returns the new text and `[{"line": n, "kind": "private_path" | "secret_token"}]`."""
    user_re = _current_user_pattern()
    out: list[str] = []
    found: list[dict] = []
    for n, line in enumerate(text.splitlines(), 1):
        new = line
        if secrets:
            if providers.SECRET.search(new):
                new = providers.SECRET.sub(REDACTED, new)
                found.append({"line": n, "kind": "secret_token"})
            for _name, a, b in reversed(providers.secret_assignments(new)):
                raw = new[a:b]
                quote = raw[0] if raw[:1] in "\"'" else ""
                new = new[:a] + (f"{quote}{REDACTED}{quote}" if quote else f'"{REDACTED}"') + new[b:]
                found.append({"line": n, "kind": "secret_token"})
        moved = _redact_paths(new, user_re)
        if moved != new:
            found.append({"line": n, "kind": "private_path"})
        out.append(moved)
    tail = "\n" if text.endswith("\n") else ""
    return "\n".join(out) + tail, found


def _scan(root: Path, files: list[str] | None = None) -> tuple[list[dict], list[Path], list[str]]:
    """Every issue (not a capped list: a file past the cap would slip into a pack), the files scanned, and the ones that could not be."""
    root = root.resolve()
    candidates = _iter_workspace_files(root, selected=files)
    issues: list[dict] = []
    unscanned: list[str] = []
    for env_candidate in sorted(root.glob(".env*")):
        if env_candidate.is_file() and env_candidate.name not in (".env.example", ".env.sample"):
            issues.append({
                "path": env_candidate.relative_to(root).as_posix(),
                "line": 0,
                "kind": "secret_file",
                "message": "Environment file excluded from Share Pack (keep only .env.example)",
            })
    user_re = _current_user_pattern()
    for p in candidates:
        rel = p.relative_to(root).as_posix()
        if SECRET_FILE_NAMES.search(rel):
            issues.append({"path": rel, "line": 0, "kind": "secret_file", "message": "Secret or database file must not be shared"})
            continue
        text = _read_text(p)
        if text is None:
            unscanned.append(rel)
            continue
        for idx, line in enumerate(text.splitlines(), 1):
            if providers.looks_like_secret(line):
                issues.append({"path": rel, "line": idx, "kind": "secret_token", "message": "Potential API key, token or password detected"})
            elif PRIVATE_RE.search(line) or (user_re and user_re.search(line)):
                issues.append({"path": rel, "line": idx, "kind": "private_path", "message": "Personal local path or private workspace reference detected"})
    return issues, candidates, unscanned


def doctor(root: Path, files: list[str] | None = None) -> dict:
    """Scans files (or workspace) before sharing for secret keys, `.env`/SQLite files, and personal local paths."""
    issues, candidates, unscanned = _scan(root, files)
    return {"clean": not issues, "scanned": len(candidates) - len(unscanned), "unscanned": len(unscanned), "total_issues": len(issues), "issues": issues[:60]}


def _sanitize_harness_toml(root: Path) -> tuple[str, list[dict]]:
    """`harness.toml` for the pack: every secret-looking value and every private path rewritten. Fail-closed: the
    name decides first (`*key*`, `*secret*`, `*token*`, `*password*`), then the shape of the value."""
    src = root / "harness.toml"
    if not src.is_file():
        return "", []
    text, found = redact_text(src.read_text(encoding="utf-8", errors="ignore"), secrets=True)
    return text.rstrip("\n") + "\n", found


def _env_example_text(root: Path) -> str:
    vars_needed: list[str] = [v["env"] for v in providers.PRESETS.values()]
    for c in providers.custom_providers(root=root):
        if c.get("api_key_env") and c["api_key_env"] not in vars_needed:
            vars_needed.append(c["api_key_env"])
    lines = [
        "# CAOS Agent Harness — copy to .harness/.env.local (never commit secrets)",
        "# Fill only the providers you actually use:",
        f"OLLAMA_HOST={providers.default_ollama_url()}",
    ]
    for v in vars_needed:
        lines.append(f"# {v}=your_key_here")
    return "\n".join(lines) + "\n"


def _team_setup_guide(project_name: str, skills_count: int) -> str:
    return f"""# Team Onboarding — {project_name}

## 1. Install / verify harness
```bash
pip install -e .
caos-harness providers list
```

## 2. Configure only your local or API credentials
Copy `.env.example` to `.harness/.env.local` (already gitignored, chmod 0600) or run:
```bash
caos-harness providers add openrouter --env OPENROUTER_API_KEY
```

## 3. Launch dashboard or terminal workstation
```bash
caos-harness            # Unified CAOS TUI
caos-harness serve      # Local web desk at http://127.0.0.1:8791
```

Bundled team skills included in `team_skills/`: **{skills_count}** curated dev/QA/UI/docs modules.
"""


def _plan(root: Path, include_code: bool, include_docs: bool, include_skills: bool, selected_files: list[str] | None) -> dict:
    """What a pack would hold, decided once, so the preview shows exactly what the build writes."""
    root = root.resolve()
    doc_extensions = {".md", ".txt", ".rst", ".csv"}
    excluded: list[dict] = []
    wanted: list[Path] = []
    for p in _iter_workspace_files(root, selected=selected_files):
        rel = p.relative_to(root).as_posix()
        if rel == "harness.toml":
            continue
        if SECRET_FILE_NAMES.search(rel):
            excluded.append({"path": rel, "reason": "secret or database file"})
            continue
        is_doc = p.suffix.lower() in doc_extensions or rel.startswith("docs/")
        if is_doc and not include_docs:
            continue
        if not is_doc and not include_code:
            continue
        wanted.append(p)
    issues, _, _ = _scan(root, [p.relative_to(root).as_posix() for p in wanted] or None) if wanted else ([], [], [])
    leaky = {i["path"] for i in issues if i["kind"] in ("secret_file", "secret_token")}
    included: list[dict] = []
    redactions: list[dict] = []
    unscanned: list[str] = []
    for p in wanted:
        rel = p.relative_to(root).as_posix()
        if rel in leaky:
            excluded.append({"path": rel, "reason": "holds a credential"})
            continue
        text = _read_text(p)
        lines = 0
        if text is None:
            unscanned.append(rel)
        else:
            _, found = redact_text(text)
            lines = len(found)
            if found:
                redactions.append({"path": rel, "lines": [f["line"] for f in found], "kinds": sorted({f["kind"] for f in found})})
        included.append({"path": rel, "size": p.stat().st_size, "redacted_lines": lines})
    toml_text, toml_found = _sanitize_harness_toml(root)
    if toml_text:
        included.append({"path": "harness.toml", "size": len(toml_text.encode()), "redacted_lines": len(toml_found), "sanitized": True})
        if toml_found:
            redactions.append({"path": "harness.toml", "lines": [f["line"] for f in toml_found], "kinds": sorted({f["kind"] for f in toml_found})})
    team_skills = [s for s in skills.load_all(project_root=root).values() if s.team_shareable] if include_skills else []
    return {"included": included, "excluded": excluded, "redactions": redactions, "unscanned": unscanned, "team_skills": team_skills,
            "toml_text": toml_text, "truncated": len(wanted) >= 800 and not selected_files}


def _checklist(plan: dict) -> list[dict]:
    secret_ex = [e for e in plan["excluded"] if e["reason"] == "secret or database file"]
    cred_ex = [e for e in plan["excluded"] if e["reason"] == "holds a credential"]
    paths = sum(len(r["lines"]) for r in plan["redactions"] if "private_path" in r["kinds"])
    toml_vals = sum(1 for r in plan["redactions"] if r["path"] == "harness.toml" and "secret_token" in r["kinds"])
    return [
        {"id": "secret_files", "label": f"{len(secret_ex)} secret or database file(s) left out", "ok": True},
        {"id": "credentials", "label": f"{len(cred_ex)} file(s) holding a credential left out", "ok": True},
        {"id": "private_paths", "label": f"{paths} line(s) with a private path rewritten in the copy", "ok": True},
        {"id": "harness_toml", "label": "harness.toml carries no secret-looking value" + (f" ({toml_vals} file entry redacted)" if toml_vals else ""), "ok": True},
        {"id": "env_example", "label": ".env.example lists variable names only", "ok": True},
        {"id": "unscanned", "label": f"{len(plan['unscanned'])} large or binary file(s) could not be scanned", "ok": not plan["unscanned"]},
        {"id": "truncated", "label": "the workspace is larger than the 800 files a pack holds" if plan["truncated"] else "every file in the workspace was considered", "ok": not plan["truncated"]},
    ]


def preview_share_pack(
    root: Path,
    *,
    include_code: bool = True,
    include_docs: bool = True,
    include_skills: bool = True,
    fmt: str = "zip",
    selected_files: list[str] | None = None,
) -> dict:
    """What `build_share_pack` would write, without writing anything: the files, what is left out and why, what is rewritten."""
    fmt = normalize_format(fmt)
    root = root.resolve()
    plan = _plan(root, include_code, include_docs, include_skills, selected_files)
    generated = [{"path": ".env.example", "size": len(_env_example_text(root).encode())}, {"path": "TEAM_SETUP.md", "size": len(_team_setup_guide(root.name, len(plan["team_skills"])).encode())}]
    generated += [{"path": f"team_skills/{s.name}/SKILL.md", "size": len(s.body.encode())} for s in plan["team_skills"]]
    total = sum(i["size"] for i in plan["included"]) + sum(g["size"] for g in generated)
    return {
        "ok": True,
        "dry_run": True,
        "format": fmt,
        "included": plan["included"],
        "generated": generated,
        "excluded": plan["excluded"],
        "redactions": plan["redactions"],
        "redacted_paths": [r["path"] for r in plan["redactions"]],
        "unscanned": plan["unscanned"][:20],
        "files_count": len(plan["included"]) + len(generated),
        "total_bytes": total,
        "skills_included": [s.name for s in plan["team_skills"]],
        "sanitization": _checklist(plan),
        "onboarding": ["pip install -e .", "cp .env.example .harness/.env.local   # then fill only the providers you use", "caos-harness doctor --dry-run", "caos-harness"],
    }


def _write_archive(fmt: str, bundle_dir: Path, exports_dir: Path, stem: str) -> Path:
    if fmt == "dir":
        return bundle_dir
    files = [f for f in sorted(bundle_dir.rglob("*")) if f.is_file()]
    if fmt == "zip":
        out = exports_dir / f"{stem}.zip"
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                zf.write(f, f.relative_to(bundle_dir).as_posix())
    else:
        out = exports_dir / f"{stem}.tar.gz"

        def plain(info: tarfile.TarInfo) -> tarfile.TarInfo:
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            return info

        with tarfile.open(out, "w:gz") as tf:
            for f in files:
                tf.add(str(f), arcname=f.relative_to(bundle_dir).as_posix(), recursive=False, filter=plain)
    shutil.rmtree(bundle_dir, ignore_errors=True)
    return out


def build_share_pack(
    root: Path,
    *,
    include_code: bool = True,
    include_docs: bool = True,
    include_skills: bool = True,
    fmt: str = "zip",
    selected_files: list[str] | None = None,
) -> dict:
    """Builds a clean, secret-free Share Pack (`.zip`, `.tar.gz` or a folder) ready for a teammate or Drive.

    Files holding a credential are left out; private paths are rewritten in the copy; the bundle is scanned again before it is
    sealed, and anything still flagged is removed (`verified` says the final scan came back clean)."""
    fmt = normalize_format(fmt)
    root = root.resolve()
    plan = _plan(root, include_code, include_docs, include_skills, selected_files)

    exports_dir = root / ".harness" / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    stem = f"{root.name}-share-pack-{stamp}"
    bundle_dir = exports_dir / stem
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    bundle_dir.mkdir(parents=True)

    for item in plan["included"]:
        rel = item["path"]
        if item.get("sanitized"):
            continue
        src, dst = root / rel, bundle_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        text = _read_text(src) if item["redacted_lines"] else None
        if text is not None:
            dst.write_text(redact_text(text)[0], encoding="utf-8")
            shutil.copystat(src, dst)
        else:
            shutil.copy2(src, dst)

    if plan["toml_text"]:
        (bundle_dir / "harness.toml").write_text(plan["toml_text"], encoding="utf-8")
    (bundle_dir / ".env.example").write_text(_env_example_text(root), encoding="utf-8")
    (bundle_dir / "TEAM_SETUP.md").write_text(_team_setup_guide(root.name, len(plan["team_skills"])), encoding="utf-8")
    for sk in plan["team_skills"]:
        sk_dst = bundle_dir / "team_skills" / sk.name
        sk_dst.mkdir(parents=True, exist_ok=True)
        (sk_dst / "SKILL.md").write_text(
            f"---\nname: {sk.name}\ndescription: {sk.description}\ncategory: {sk.category}\n---\n\n{sk.body}\n",
            encoding="utf-8",
        )

    # The last gate: scan what is about to be sealed. A path that slipped through is rewritten; a credential removes its file.
    excluded = list(plan["excluded"])
    issues, _, _ = _scan(bundle_dir)
    for rel in sorted({i["path"] for i in issues if i["kind"] in ("secret_file", "secret_token")}):
        (bundle_dir / rel).unlink(missing_ok=True)
        excluded.append({"path": rel, "reason": "caught by the final scan"})
    for rel in sorted({i["path"] for i in issues if i["kind"] == "private_path"} - {e["path"] for e in excluded}):
        f = bundle_dir / rel
        text = _read_text(f)
        if text is not None:
            f.write_text(redact_text(text)[0], encoding="utf-8")
    verified = not _scan(bundle_dir)[0]

    total_files = sum(1 for _ in bundle_dir.rglob("*") if _.is_file())
    out_path = _write_archive(fmt, bundle_dir, exports_dir, stem)
    size = sum(f.stat().st_size for f in out_path.rglob("*") if f.is_file()) if out_path.is_dir() else out_path.stat().st_size
    scan = doctor(root, files=[i["path"] for i in plan["included"] if not i.get("sanitized")] or None)

    return {
        "ok": True,
        "format": fmt,
        "path": str(out_path),
        "relative_path": out_path.relative_to(root).as_posix(),
        "filename": out_path.name,
        "size_bytes": size,
        "files_count": total_files,
        "skills_included": [s.name for s in plan["team_skills"]],
        "redacted_paths": [r["path"] for r in plan["redactions"]],
        "redactions": plan["redactions"],
        "excluded": excluded,
        "verified": verified,
        "doctor": scan,
    }


def upload_gdrive(file_path: Path, parent_id: str | None = None, runner=subprocess.run) -> dict:
    """Uploads an exported Share Pack or file to Google Drive using the connected `gdrive` CLI."""
    target = file_path.resolve()
    if not target.is_file():
        return {"ok": False, "message": f"File not found: {target.name}"}
    gd = shutil.which("gdrive")
    if not gd:
        return {
            "ok": False,
            "message": "gdrive CLI is not installed on PATH. Use the downloaded Share Pack zip or connect Google Drive plugin.",
        }
    cmd = [gd, "mutate", "upload", str(target), "--json"]
    if parent_id and re.fullmatch(r"[A-Za-z0-9_\-]{6,120}", parent_id.strip()):
        cmd += ["--parent", parent_id.strip()]
    res = runner(cmd, capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        err = (res.stderr or res.stdout or "").strip()[:240]
        return {"ok": False, "message": err or "gdrive upload failed"}
    file_id = ""
    web_url = ""
    try:
        parsed = json.loads(res.stdout or "{}")
        file_id = str(parsed.get("id") or parsed.get("fileId") or "")
        web_url = str(parsed.get("webViewLink") or parsed.get("url") or "")
    except ValueError:
        pass
    if file_id and not web_url:
        u = runner([gd, "readonly", "url", file_id, "--json"], capture_output=True, text=True, timeout=15)
        if u.returncode == 0:
            try:
                web_url = str(json.loads(u.stdout or "{}").get("url") or "")
            except ValueError:
                web_url = (u.stdout or "").strip()
    return {"ok": True, "provider": "gdrive", "file_id": file_id, "url": web_url, "filename": target.name}
