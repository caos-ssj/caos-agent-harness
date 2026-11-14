"""60-second repository onboarding: inspect folder ecosystem, test runner and locally available engines."""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

from . import app, providers

_MAKE_TARGET = re.compile(r"^([A-Za-z0-9_.-]+)\s*:", re.MULTILINE)
_COST_BY_CLI = {"opencode": "free", "agy": "cheap", "claude": "paid", "codex": "paid"}
_LOCAL_RANK = ("qwen2.5-coder:7b", "qwen2.5:7b", "qwen3.5:4b", "llama3.2:3b")


def _toml_str(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _toml_list(items: list[str]) -> str:
    return "[" + ", ".join(_toml_str(x) for x in items) + "]"


def detect_stack(folder: Path) -> dict:
    """Detect repo languages, verification command and git status deterministically from files on disk."""
    stacks: list[str] = []
    verify: list[str] | None = None

    has_py = any((folder / name).exists() for name in ("pyproject.toml", "pytest.ini", "setup.py", "setup.cfg")) or (folder / "tests").is_dir()
    if has_py:
        stacks.append("python")
        if (folder / ".venv" / "Scripts" / "pytest.exe").is_file():
            verify = [".venv/Scripts/pytest.exe", "-q"]
        elif (folder / ".venv" / "bin" / "pytest").is_file():
            verify = [".venv/bin/pytest", "-q"]
        elif shutil.which("pytest"):
            verify = ["pytest", "-q"]
        else:
            verify = [Path(sys.executable or "python3").name, "-m", "pytest", "-q"]

    pkg_path = folder / "package.json"
    if pkg_path.is_file():
        stacks.append("node")
        if verify is None:
            try:
                scripts = json.loads(pkg_path.read_text(encoding="utf-8")).get("scripts") or {}
            except (OSError, ValueError):
                scripts = {}
            test_cmd = str(scripts.get("test") or "")
            if test_cmd and "no test specified" not in test_cmd:
                verify = ["npm", "test"]
            elif scripts.get("build"):
                verify = ["npm", "run", "build"]

    if (folder / "Cargo.toml").is_file():
        stacks.append("rust")
        if verify is None:
            verify = ["cargo", "test", "--quiet"]

    if (folder / "go.mod").is_file():
        stacks.append("go")
        if verify is None:
            verify = ["go", "test", "./..."]

    makefile = folder / "Makefile"
    if makefile.is_file():
        stacks.append("make")
        if verify is None:
            try:
                targets = set(_MAKE_TARGET.findall(makefile.read_text(encoding="utf-8")))
            except OSError:
                targets = set()
            for cand in ("check", "test"):
                if cand in targets:
                    verify = ["make", cand]
                    break

    return {"stacks": stacks, "verify": verify, "has_git": (folder / ".git").exists()}


def _pick_ollama_models(models: list[str]) -> list[tuple[str, str]]:
    """Select up to two distinct local Ollama models (author coder + secondary reviewer) without embeddings."""
    chat_models = [m for m in models if "embed" not in m.lower()]
    ordered: list[str] = [m for m in _LOCAL_RANK if m in chat_models]
    for m in chat_models:
        if m not in ordered:
            ordered.append(m)
    picks: list[tuple[str, str]] = []
    if ordered:
        picks.append(("local", ordered[0]))
    if len(ordered) > 1:
        picks.append(("reviewer", ordered[1]))
    return picks


def detect_engines(probe_local_ollama: bool = True) -> list[dict]:
    """Discover installed CLI agents and responsive local Ollama models ready to populate harness.toml."""
    engines: list[dict] = []
    for cli in providers.detect_clis():
        if not cli.get("installed"):
            continue
        cid = cli["id"]
        spec = providers.CLIS[cid]
        engines.append({
            "name": cid,
            "kind": "cli",
            "command": list(spec["command"]),
            "cost": _COST_BY_CLI.get(cid, "paid"),
            "timeout": int(spec.get("timeout", 600)),
            "system": None,
        })

    if probe_local_ollama:
        probe = providers.probe_ollama(timeout=0.5)
        for name, model in _pick_ollama_models(list(probe.get("models") or [])):
            engines.append({
                "name": name,
                "kind": "local",
                "command": ["ollama", "run", model],
                "cost": "free",
                "timeout": 300,
                "system": model if model in {"llama3.2:3b", "qwen2.5:7b"} else None,
            })

    if not engines:
        engines.append({
            "name": "echo",
            "kind": "command",
            "command": ["cat"],
            "cost": "free",
            "timeout": 30,
            "system": None,
        })
    return engines


def _pick_default_verifier(engines: list[dict]) -> str | None:
    if len(engines) < 2:
        return None
    for e in engines:
        if e["name"] != "echo" and e["cost"] == "free":
            return e["name"]
    return engines[0]["name"]


def render_toml(folder: Path, plan: dict) -> str:
    """Render a clean, valid harness.toml from a `scan()` plan."""
    name = (folder.name or "workspace")[:80]
    verify = plan.get("verify")
    engines: list[dict] = plan.get("engines") or []
    verifier = plan.get("verifier")

    lines = [
        f"# CAOS project config for {name}. Paths are relative to this folder.",
        "[board]",
        'db = ".harness/board.db"',
        'trace = ".harness/trace.db"',
    ]

    if verify:
        lines.extend(["", "[landing]", 'target = "branch"', "autonomous = false", f"verify = {_toml_list(list(verify))}"])

    for eng in engines:
        lines.extend([
            "",
            f"[agents.{eng['name']}]",
            f"command = {_toml_list(list(eng['command']))}",
            f"cost = {_toml_str(eng['cost'])}",
            f"timeout = {int(eng['timeout'])}",
        ])
        if eng.get("system"):
            lines.append(f"system = {_toml_str(str(eng['system']))}")

    return "\n".join(lines) + "\n"


def scan(folder: Path, probe_local_ollama: bool = True) -> dict:
    """Inspect `folder` without writing anything and return the onboarding plan + generated TOML."""
    target = Path(folder).expanduser().resolve()
    stack = detect_stack(target)
    engines = detect_engines(probe_local_ollama=probe_local_ollama)
    verifier = _pick_default_verifier(engines)
    plan = {
        "folder": str(target),
        "name": target.name or str(target),
        "has_config": (target / app.CONFIG).is_file(),
        "has_git": stack["has_git"],
        "stacks": stack["stacks"],
        "verify": stack["verify"],
        "verifier": verifier,
        "engines": engines,
    }
    plan["toml"] = render_toml(target, plan)
    return plan


def apply_init(folder: Path, probe_local_ollama: bool = True, overwrite: bool = False) -> dict:
    """Write detected `harness.toml` + `.harness/` and verify it loads cleanly via `app.load`."""
    target = Path(folder).expanduser().resolve()
    if not target.is_dir():
        raise app.ConfigError(f"not a folder: {target}")
    cfg = target / app.CONFIG
    if cfg.exists() and not overwrite:
        raise app.ConfigError(f"{cfg} already exists")
    plan = scan(target, probe_local_ollama=probe_local_ollama)
    cfg.write_text(plan["toml"], encoding="utf-8")
    (target / ".harness").mkdir(exist_ok=True)
    app.load(cfg)
    return {**plan, "created": str(cfg), "has_config": True}
