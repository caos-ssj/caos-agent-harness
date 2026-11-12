"""Preflight: is this folder ready to work in, and ready to share? It answers `ready`, `warning` or `blocked` and says what to do next.

It never calls a model and spends no tokens. With `dry_run` it does not touch the network either: configuration, keys,
tools, git and the leak scan are read from disk, and the engines are reported as configured, not probed.

    blocked   something stops work: no project, a broken board, no model engine reachable, a credential sitting in a file
    warning   work can go on, but something needs a look: a missing key an agent uses, an offline host, a leak to clean
    ready     nothing to do
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from . import app, mcp_tools, providers, share, style, term, worktrees

ORDER = {"blocked": 0, "warning": 1, "info": 2, "ok": 3}


def _check(cid: str, label: str, level: str, detail: str = "", action: str = "") -> dict:
    return {"id": cid, "label": label, "level": level, "detail": detail, "action": action}


def _git_state(root: Path) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, timeout=5)
        return (len([ln for ln in r.stdout.splitlines() if ln.strip()]), "") if r.returncode == 0 else (0, r.stderr.strip()[:80])
    except (OSError, subprocess.TimeoutExpired):
        return 0, "git did not answer"


def preflight(project: app.Project | None = None, dry_run: bool = False) -> dict:
    checks: list[dict] = []
    if project is None:
        try:
            project = app.load()
        except app.ConfigError as e:
            checks.append(_check("project", "Project", "blocked", str(e), "caos-harness init"))
            return _result(None, checks, dry_run)
    root = project.root
    checks.append(_check("project", "Project", "ok", f"{root.name} · harness.toml loaded"))

    # Agents: a command that is not on PATH, or an API agent whose key is not set.
    problems, ready = [], 0
    for name, a in project.agents.items():
        if a.provider:
            try:
                key, _ = providers.key_for(a.provider, a.key_env, root=root)
            except providers.ProviderError as e:
                key, problems = None, problems + [f"{name}: {e}"]
                continue
            if key:
                ready += 1
            else:
                env = a.key_env or providers.API.get(a.provider, {}).get("env", "the key")
                problems.append(f"{name}: {env} is not set")
        elif a.command and shutil.which(a.command[0]):
            ready += 1
        else:
            problems.append(f"{name}: `{a.command[0] if a.command else '?'}` is not on PATH")
    if not project.agents:
        checks.append(_check("agents", "Agents", "warning", "none in harness.toml", "Add an [agents.<name>] table to harness.toml, or queue work for `person`"))
    elif problems:
        checks.append(_check("agents", "Agents", "warning", f"{ready}/{len(project.agents)} ready · " + "; ".join(problems[:3]), "Set the missing key in .harness/.env.local, or fix the agent's command"))
    else:
        checks.append(_check("agents", "Agents", "ok", f"{ready}/{len(project.agents)} ready"))

    # The board.
    if not project.db.exists():
        checks.append(_check("board", "Board", "info", "no board yet; it is created with the first task"))
    else:
        try:
            st = project.board.stats()
            checks.append(_check("board", "Board", "ok", f"{st['tasks']} task(s)"))
        except Exception as e:   # a corrupt database is the one thing the preflight must not hide
            checks.append(_check("board", "Board", "blocked", f"{type(e).__name__}: {str(e)[:80]}", "Move .harness/board.db aside; the board is rebuilt empty"))

    # Engines: local hosts and cloud keys.
    hosts = providers.ollama_hosts(root)
    online = 0
    if dry_run:
        checks.append(_check("ollama", "Ollama", "info", f"{len(hosts)} host(s) configured · not probed (dry run)"))
    else:
        probe = providers.probe_ollama(hosts, timeout=0.8)
        online = sum(1 for h in probe["hosts"] if h["online"])
        if probe["online"]:
            checks.append(_check("ollama", "Ollama", "ok", f"{online}/{len(hosts)} host(s) online · {len(probe['models'])} model(s)"))
        else:
            checks.append(_check("ollama", "Ollama", "warning", f"0/{len(hosts)} host(s) online", "Start Ollama (`ollama serve`), or point a host at another machine: caos-harness providers ollama-hosts add <url>"))
    keyed, bad = [], []
    for pid in providers.API:
        try:
            if providers.key_for(pid, None, root=root)[0]:
                keyed.append(pid)
        except providers.ProviderError as e:
            bad.append(f"{pid}: {e}")
    if bad:
        checks.append(_check("cloud", "Cloud keys", "warning", "; ".join(bad[:2]), "Fix the key so it has no spaces or line breaks"))
    elif keyed:
        checks.append(_check("cloud", "Cloud keys", "ok", f"{len(keyed)}/{len(providers.API)} set · " + ", ".join(keyed)))
    else:
        checks.append(_check("cloud", "Cloud keys", "info", f"none of {len(providers.API)} set: local models only"))
    if not dry_run and not online and not keyed:
        checks.append(_check("engine", "Model engine", "blocked", "no local host answers and no cloud key is set", "Start Ollama, or save a key: caos-harness providers add <id> --env <VAR> and put the value in .harness/.env.local"))

    fo = providers.load_failover(root)
    if fo["enabled"]:
        target = fo["fallback_target"]
        if target == "ollama":
            checks.append(_check("failover", "Failover", "ok" if dry_run or online else "warning", f"on → ollama {fo['fallback_model'] or '(first model)'}", "" if dry_run or online else "Failover points at Ollama, which is offline"))
        else:
            has = bool(providers.key_for(target, None, root=root)[0]) if target in providers.API else True
            checks.append(_check("failover", "Failover", "ok" if has else "warning", f"on → {target}", "" if has else f"Set the key for {target}, the failover target"))
    else:
        checks.append(_check("failover", "Failover", "info", "off"))

    # Tools and MCP servers declared by the project.
    mcp = [t for t in mcp_tools.discover_tools(root) if t["id"].startswith("mcp:") and t["id"] != "mcp-memory"]
    broken = [t["name"] for t in mcp if t["status"] != "ready"]
    if broken:
        checks.append(_check("mcp", "MCP servers", "warning", f"{len(broken)} without a command: " + ", ".join(broken[:3]), "Give each server a `command` in .mcp.json"))
    else:
        checks.append(_check("mcp", "MCP servers", "ok" if mcp else "info", f"{len(mcp)} configured" if mcp else "none in .mcp.json"))

    # Git and worktrees.
    if worktrees.is_git_repo(root):
        dirty, err = _git_state(root)
        wt = len(worktrees.active_worktrees(root))
        detail = f"{worktrees.current_branch(root) or 'detached'} · {'clean' if not dirty else f'{dirty} changed file(s)'} · {wt} worktree(s)"
        checks.append(_check("git", "Git", "warning" if err else "ok", err or detail))
    else:
        checks.append(_check("git", "Git", "info", "not a git repository: isolated worktrees are unavailable"))

    # Leaks: what a Share Pack would have to leave out or rewrite.
    scan = share.doctor(root)
    kinds = {i["kind"] for i in scan["issues"]}
    if scan["clean"]:
        checks.append(_check("leaks", "Leak scan", "ok", f"{scan['scanned']} file(s), nothing to clean"))
    elif "secret_token" in kinds:
        n = sum(1 for i in scan["issues"] if i["kind"] == "secret_token")
        checks.append(_check("leaks", "Leak scan", "blocked", f"{n} credential(s) found in files", "caos-harness share doctor   # lists each file and line; move the value to .harness/.env.local"))
    else:
        checks.append(_check("leaks", "Leak scan", "warning", f"{scan['total_issues']} item(s): " + ", ".join(sorted(kinds)), "caos-harness share doctor   # a pack leaves these out or rewrites them"))
    return _result(project, checks, dry_run)


def _result(project: app.Project | None, checks: list[dict], dry_run: bool) -> dict:
    levels = {c["level"] for c in checks}
    verdict = "blocked" if "blocked" in levels else ("warning" if "warning" in levels else "ready")
    actions: list[str] = []
    for c in sorted(checks, key=lambda c: ORDER[c["level"]]):
        if c["action"] and c["level"] in ("blocked", "warning") and c["action"] not in actions:
            actions.append(c["action"])
    return {
        "ok": verdict != "blocked",
        "verdict": verdict,
        "dry_run": dry_run,
        "tokens_spent": 0,
        "project": project.root.name if project else None,
        "summary": {lv: sum(1 for c in checks if c["level"] == lv) for lv in ("ok", "info", "warning", "blocked")},
        "checks": checks,
        "next_actions": actions,
    }


def render(res: dict, w: int | None = None) -> list[str]:
    """The preflight as lines: a rounded panel with a verdict badge on a terminal, a plain list when piped."""
    v = res["verdict"]
    tone = style.VERDICT_TONE[v]
    mark = {"ready": "●", "warning": "▲", "blocked": "■"}[v]
    badge = style.paint(f"{mark} {v.upper()}", tone, True)
    mode = "dry run, nothing contacted" if res["dry_run"] else "live probes"
    lines = []
    width = max(len(c["label"]) for c in res["checks"])
    for c in res["checks"]:
        glyph, gt = style.LEVEL_MARK[c["level"]]
        lines.append(f"{style.paint(glyph, gt)} {term.pad(c['label'], width)}  {style.paint(c['detail'], style.GRIS) if c['level'] != 'ok' else c['detail']}")
    if res["next_actions"]:
        lines += ["", style.heading("Next")] + [f"  {i}. {a}" for i, a in enumerate(res["next_actions"], 1)]
    if not style.fancy():   # piped: a word per level, so a script can grep it
        plain = [f"  {c['level']:<8} {term.pad(c['label'], width)}  {c['detail']}".rstrip() for c in res["checks"]]
        if res["next_actions"]:
            plain += ["Next:"] + [f"  {i}. {a}" for i, a in enumerate(res["next_actions"], 1)]
        return [f"Doctor: {v} ({mode}, 0 tokens)"] + plain
    lines += ["", style.dim(f"{mode} · 0 tokens spent")]
    return term.panel(f"doctor · {res['project'] or 'no project'}", lines, w, tone=tone, badge=badge)
