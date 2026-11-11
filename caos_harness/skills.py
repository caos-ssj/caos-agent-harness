"""Role skills: the working instructions an agent loads for a kind of task (`skills/<name>/SKILL.md`).

A skill is a short document with a `name` and a `description` that says when to use it. A task queued with a skill
is sent with a pointer to it first (`Board.add(..., skill=...)`), so an agent starts from the same rules every time.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRONT = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.S)


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    path: Path
    local: bool = False   # True: comes from the operator's own folders, not from the repository


def parse(path: Path) -> Skill:
    m = FRONT.match(path.read_text(encoding="utf-8"))
    if not m:
        raise ValueError(f"{path}: missing front matter")
    meta = dict(line.split(":", 1) for line in m.group(1).splitlines() if ":" in line)
    name, desc = meta.get("name", "").strip(), meta.get("description", "").strip()
    if not name or not desc:
        raise ValueError(f"{path}: front matter needs name and description")
    if name != path.parent.name:
        raise ValueError(f"{path}: name '{name}' does not match its folder")
    return Skill(name, desc, m.group(2).strip(), path)


def load_packaged(root: Path | None = None) -> dict[str, Skill]:
    """The skills that ship with the repository."""
    return {s.name: s for s in (parse(p) for p in sorted((root or ROOT / "skills").glob("*/SKILL.md")))}


def local_dirs() -> list[Path]:
    """Where the operator keeps skills of their own: `<project>/.harness/skills` (never committed) and every folder
    listed in the environment variable CAOS_HARNESS_SKILLS (separated by `:`)."""
    dirs = [Path(d).expanduser() for d in os.environ.get("CAOS_HARNESS_SKILLS", "").split(":") if d.strip()]
    try:
        from .app import find_config
        dirs.insert(0, find_config().parent / ".harness" / "skills")
    except Exception:
        pass
    return [d for d in dirs if d.is_dir()]


def load_all(root: Path | None = None) -> dict[str, Skill]:
    """Packaged skills plus the operator's local ones. A local skill with the name of a packaged one replaces it.
    A local file that does not parse is skipped: someone else's folder must not break the board."""
    skills = load_packaged(root)
    if root is None:
        for d in local_dirs():
            for p in sorted(d.glob("*/SKILL.md")):
                try:
                    s = parse(p)
                except (ValueError, OSError):
                    continue
                skills[s.name] = Skill(s.name, s.description, s.body, s.path, local=True)
    return skills


def known(name: str, root: Path | None = None) -> bool:
    """The board stores a skill by name; check the name before queuing a task with it."""
    return name in load_all(root)
