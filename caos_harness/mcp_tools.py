"""Inspect dev tools and MCP integrations available to a harness project without reading secrets."""
from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path


def _module_installed(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _project_mcp_servers(root: Path) -> list[dict]:
    cfg = root / ".mcp.json"
    if not cfg.is_file():
        return []
    try:
        raw = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    servers = raw.get("mcpServers") if isinstance(raw, dict) else None
    if not isinstance(servers, dict):
        return []
    out = []
    for name, entry in servers.items():
        if not isinstance(entry, dict):
            continue
        cmd = entry.get("command")
        args = entry.get("args") if isinstance(entry.get("args"), list) else []
        out.append({
            "id": f"mcp:{name}",
            "name": str(name),
            "kind": "mcp",
            "status": "ready" if isinstance(cmd, str) and bool(cmd) else "configured",
            "summary": " ".join([str(cmd or ""), *(str(a) for a in args[:2])]).strip() or "project .mcp.json",
            "shareable": True,
        })
    return out


def discover_tools(root: Path) -> list[dict]:
    """Lists active workstation tools, MCP servers and share helpers for the project."""
    git_ok = (root / ".git").exists() and shutil.which("git") is not None
    mcp_ok = _module_installed("mcp")
    pw_ok = shutil.which("playwright") is not None or _module_installed("playwright")
    gd_ok = shutil.which("gdrive") is not None or shutil.which("rclone") is not None
    tools = [
        {"id": "ws-read", "name": "Workspace Reader", "kind": "builtin", "status": "online", "summary": "read_file, list_files, grep, git_diff (auto-run safely in repo)", "shareable": True},
        {"id": "ws-act", "name": "Guarded Editor & Shell", "kind": "builtin", "status": "online", "summary": "write_file, edit_file, run_command with pre-action intent card", "shareable": True},
        {"id": "git-wt", "name": "Git Worktrees", "kind": "tool", "status": "online" if git_ok else "offline", "summary": "Isolated branches under .harness/worktrees for agent edits", "shareable": True},
        {"id": "mcp-memory", "name": "CAOS Memory MCP", "kind": "mcp", "status": "ready" if mcp_ok else "optional", "summary": "python -m caos_harness.memory.server over stdio", "shareable": True},
        {"id": "pw-e2e", "name": "Playwright E2E", "kind": "tool", "status": "online" if pw_ok else "optional", "summary": "Real Chromium layout & UX gate across desktop/mobile", "shareable": True},
        {"id": "team-drive", "name": "Google Drive / Sync", "kind": "team", "status": "online" if gd_ok else "optional", "summary": "Optional Share Pack upload via connected gdrive/rclone CLI", "shareable": True},
    ]
    return tools + _project_mcp_servers(root)
