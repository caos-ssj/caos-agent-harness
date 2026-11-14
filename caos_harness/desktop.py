"""Desktop runtime helpers: user PATH discovery, fallback workspace loading, and local session token/CORS policy."""
from __future__ import annotations

import hmac
import json
import os
import re
import signal
import threading
import time
from pathlib import Path

from . import app, workspaces

DESKTOP_ORIGINS = frozenset(
    {
        "http://tauri.localhost",
        "https://tauri.localhost",
        "tauri://localhost",
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    }
)
_LOCALHOST_ORIGIN_RE = re.compile(r"^(https?|tauri)://(127\.0\.0\.1|localhost|tauri\.localhost)(:\d+)?$")


def user_bin_dirs(home: Path | None = None) -> list[Path]:
    """Candidate user tool directories that graphical desktop launchers omit from PATH."""
    base = home or Path.home()
    if os.name == "nt":
        dirs: list[Path] = [
            base / ".local" / "bin",
            base / ".cargo" / "bin",
        ]
        for env_key, rel in (
            ("APPDATA", "npm"),
            ("LOCALAPPDATA", "Programs/Ollama"),
            ("LOCALAPPDATA", "Microsoft/WinGet/Links"),
            ("LOCALAPPDATA", "Programs/Microsoft VS Code/bin"),
        ):
            raw = os.environ.get(env_key)
            if raw:
                dirs.append(Path(raw) / rel)
        return [d for d in dirs if d.is_dir()]
    dirs = [
        base / ".local" / "bin",
        base / ".cargo" / "bin",
        base / ".npm-global" / "bin",
        base / ".opencode" / "bin",
        Path("/usr/local/bin"),
    ]
    nvm_versions = base / ".nvm" / "versions" / "node"
    if nvm_versions.is_dir():
        versions = sorted((p / "bin" for p in nvm_versions.iterdir() if (p / "bin").is_dir()), reverse=True)
        dirs.extend(versions[:2])
    return [d for d in dirs if d.is_dir()]


def ensure_user_path(home: Path | None = None) -> str:
    """Appends missing user tool directories to PATH without duplicating existing entries."""
    current = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    seen = {os.path.normpath(p) for p in current}
    added = [str(d) for d in user_bin_dirs(home) if os.path.normpath(str(d)) not in seen]
    if added:
        os.environ["PATH"] = os.pathsep.join(current + added)
    return os.environ.get("PATH", "")


def last_workspace_file() -> Path:
    return workspaces.home() / "last-workspace"


def save_last_workspace(path: Path) -> None:
    try:
        target = last_workspace_file()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(path.resolve()), encoding="utf-8")
    except OSError:
        pass


def load_last_workspace() -> Path | None:
    try:
        raw = last_workspace_file().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    p = Path(raw).expanduser()
    return p if p.is_dir() and (p / app.CONFIG).is_file() else None


def default_desktop_workspace() -> Path:
    base = os.environ.get("CAOS_HARNESS_HOME") or os.environ.get("XDG_DATA_HOME")
    root = (Path(base) / "default-workspace") if os.environ.get("CAOS_HARNESS_HOME") else (
        (Path(base) if base else Path.home() / ".local" / "share") / "caos-harness" / "workspace"
    )
    if not (root / app.CONFIG).is_file():
        root.mkdir(parents=True, exist_ok=True)
        app.init(root)
    return root


def resolve_desktop_project(workspace_arg: str | None = None) -> app.Project:
    """Resolves the project for desktop launches outside a git/harness working directory."""
    if workspace_arg:
        p = workspaces.register(workspace_arg, initialize=False)
        proj = app.load(p / app.CONFIG)
        save_last_workspace(proj.root)
        return proj

    try:
        proj = app.load()
        workspaces.remember(proj.root)
        save_last_workspace(proj.root)
        return proj
    except app.ConfigError:
        pass

    last = load_last_workspace()
    if last is not None:
        workspaces.remember(last)
        return app.load(last / app.CONFIG)

    for raw in reversed(workspaces.registered()):
        candidate = Path(raw)
        if candidate.is_dir() and (candidate / app.CONFIG).is_file():
            try:
                proj = app.load(candidate / app.CONFIG)
                save_last_workspace(proj.root)
                return proj
            except app.ConfigError:
                continue

    fallback = default_desktop_workspace()
    workspaces.remember(fallback)
    proj = app.load(fallback / app.CONFIG)
    save_last_workspace(proj.root)
    return proj


def is_allowed_origin(origin: str | None) -> bool:
    if not origin:
        return False
    return origin in DESKTOP_ORIGINS or bool(_LOCALHOST_ORIGIN_RE.match(origin))


def token_matches(expected: str | None, header_token: str | None, auth_header: str | None, query_token: str | None) -> bool:
    """Constant-time check for desktop session tokens supplied via header, Bearer, or SSE query parameter."""
    if not expected:
        return True
    candidates = [header_token or "", query_token or ""]
    if auth_header and auth_header.lower().startswith("bearer "):
        candidates.append(auth_header[7:].strip())
    return any(c and hmac.compare_digest(c, expected) for c in candidates if c)


def format_ready_line(port: int, desktop: bool = True) -> str:
    payload = {"port": port, "url": f"http://127.0.0.1:{port}", "desktop": desktop}
    return f"CAOS_DESKTOP_READY {json.dumps(payload, ensure_ascii=False)}"


def install_shutdown_handlers() -> None:
    """SIGTERM/SIGHUP (the app quitting or the session ending) unwind serve() so running agents are cancelled."""
    def _stop(signum, frame):  # noqa: ARG001
        raise SystemExit(0)
    for name in ("SIGTERM", "SIGHUP"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, _stop)
            except (ValueError, OSError):
                pass


def watch_parent(interval: float = 1.0) -> threading.Thread | None:
    """Exits when the launching app disappears (crash, kill -9), so no engine is left orphaned."""
    parent = os.getppid()
    if parent <= 1:
        return None

    def _loop() -> None:
        while True:
            time.sleep(interval)
            if os.getppid() != parent:
                os.kill(os.getpid(), signal.SIGTERM)
                return

    t = threading.Thread(target=_loop, name="parent-watch", daemon=True)
    t.start()
    return t
