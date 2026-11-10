"""Shared memory for the agents: a knowledge base behind an MCP server, reached through one connection helper.

The harness does not own the knowledge. It talks to any MCP server that offers a search tool returning rows like
`{"ruta": "<note path>", "puntos": <relevance>}` and a read tool for one note (caos-cerebro does). What the harness adds
is on its side of the wire: the policy guard on every call, and the relevance score kept for the citation check.

`InMemoryKnowledge` is the same interface without a process, for tests and offline runs.
"""
from __future__ import annotations

import json
import os
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

SEARCH_TOOL, READ_TOOL = "buscar_notas", "leer_nota"


@dataclass(frozen=True)
class KnowledgeBase:
    """Where the MCP server lives and how to start it (stdio)."""
    root: Path
    command: str
    args: tuple = ()

    @classmethod
    def from_env(cls) -> "KnowledgeBase":
        root = Path(os.environ.get("CEREBRO_DIR", Path.home() / "repos" / "caos-cerebro-producto"))
        return cls(root, str(root / ".venv" / "bin" / "python"), (str(root / "tools" / "servidor_mcp.py"),))

    @asynccontextmanager
    async def connect(self):
        from mcp import ClientSession, StdioServerParameters  # imported here: the rest of the harness runs without `mcp`
        from mcp.client.stdio import stdio_client
        params = StdioServerParameters(command=self.command, args=list(self.args), cwd=str(self.root))
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                yield session


def rows_of(result) -> list[dict]:
    """Search rows from a tool result; anything that is not a JSON object with a path is ignored."""
    out = []
    for c in getattr(result, "content", None) or []:
        try:
            row = json.loads(getattr(c, "text", ""))
        except ValueError:
            continue
        if isinstance(row, dict) and "ruta" in row:
            out.append(row)
    return out


async def search(session, question: str, n: int = 3) -> list[dict]:
    return rows_of(await session.call_tool(SEARCH_TOOL, {"pregunta": question, "n": n}))


class _Text:
    def __init__(self, text: str):
        self.text = text


class _Result:
    def __init__(self, texts: list[str], is_error: bool = False):
        self.content, self.isError, self.structuredContent = [_Text(t) for t in texts], is_error, None


@dataclass
class InMemoryKnowledge:
    """A few notes in a dict behind the same two tools. Relevance is 1 + the share of question words found in the note."""
    notes: dict[str, str]
    calls: list = field(default_factory=list)

    async def call_tool(self, name: str, args: dict):
        self.calls.append((name, args))
        if name == SEARCH_TOOL:
            words = set(re.findall(r"\w{4,}", args["pregunta"].lower()))
            scored = sorted(((1 + sum(w in text.lower() for w in words) / max(1, len(words)), path) for path, text in self.notes.items()), reverse=True)
            return _Result([json.dumps({"ruta": p, "puntos": round(s, 3)}, ensure_ascii=False) for s, p in scored[: int(args.get("n", 3))]])
        if name == READ_TOOL:
            path = args["ruta"]
            key = path if path in self.notes else path + ".md"
            return _Result([self.notes[key]]) if key in self.notes else _Result([f"not found: {path}"], is_error=True)
        return _Result([f"unknown tool: {name}"], is_error=True)
