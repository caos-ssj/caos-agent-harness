"""Workspaces: the project folders the dashboard can switch between.

A workspace is a folder with a `harness.toml`; its board, traces and sessions live in its own `.harness/`. The list
the operator chose is kept in `~/.config/caos-harness/workspaces.json` (override with CAOS_HARNESS_HOME): paths only,
nothing from inside a project. The browser never reads an arbitrary folder: it can only switch to a folder that is
in that list, and adding one checks that it is a real directory with a valid `harness.toml`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from . import app


def home() -> Path:
    base = os.environ.get("CAOS_HARNESS_HOME")
    return Path(base) if base else Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "caos-harness"


def registered() -> list[str]:
    try:
        data = json.loads((home() / "workspaces.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [p for p in data if isinstance(p, str)] if isinstance(data, list) else []


def _save(paths: list[str]) -> None:
    f = home() / "workspaces.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(paths, indent=2), encoding="utf-8")


def check(raw) -> Path:
    """A folder that exists, as an absolute resolved path."""
    if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
        raise app.ConfigError("give the path of a folder")
    p = Path(raw.strip()).expanduser()
    if not p.is_absolute():
        raise app.ConfigError("give an absolute path, starting with /")
    p = p.resolve()
    if not p.is_dir():
        raise app.ConfigError(f"{p} is not a folder")
    return p


def describe(path: str | Path, current: Path) -> dict:
    p = Path(path)
    return {"name": p.name or str(p), "path": str(p), "current": p == current, "ready": (p / app.CONFIG).is_file()}


def listing(current: Path) -> list[dict]:
    paths = [str(current)] + [p for p in registered() if p != str(current)]
    return [describe(p, current) for p in paths]


def register(raw, initialize: bool = False) -> Path:
    """Adds a folder to the list. Without a harness.toml it is refused, unless `initialize` asks to write the example one."""
    p = check(raw)
    cfg = p / app.CONFIG
    if not cfg.is_file():
        if not initialize:
            raise app.ConfigError(f"{p} has no {app.CONFIG}. Run `caos-harness init` there, or add it with 'create the project file' turned on.")
        app.init(p, smart=True)
    app.load(cfg)   # a harness.toml that does not parse is refused here, not later
    paths = registered()
    if str(p) not in paths:
        _save(paths + [str(p)])
    return p


def forget(raw) -> None:
    paths = registered()
    _save([p for p in paths if p != str(check(raw))])


def remember(raw) -> None:
    """Keeps a folder in the list without re-validating it (used for the one the dashboard is leaving)."""
    paths = registered()
    if str(raw) not in paths:
        _save(paths + [str(raw)])
