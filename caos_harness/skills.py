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
SKILL_SLUG = re.compile(r"^[a-z0-9][a-z0-9\-]{1,48}$")

CATEGORY_BY_SKILL = {
    "coder": "Código & Infra",
    "mcp-builder": "Código & Infra",
    "qa": "QA & Testing",
    "webapp-testing": "QA & Testing",
    "ui-design": "UI & Frontend",
    "model-selection": "Modelos & Router",
    "context-engineering": "Modelos & Router",
    "source-research": "Investigación & Docs",
    "writer": "Investigación & Docs",
    "doc-converter": "Investigación & Docs",
    "social-content": "Agencia",
    "proposals": "Agencia",
}

NON_DEV_SKILLS = {"social-content", "proposals"}


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    path: Path
    local: bool = False   # True: comes from the operator's own folders, not from the repository
    category: str = "Proyecto"
    team_shareable: bool = True


def _infer_category(name: str, explicit: str | None, local: bool) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    if name in CATEGORY_BY_SKILL:
        return CATEGORY_BY_SKILL[name]
    low = name.lower()
    if any(k in low for k in ("qa", "test", "verify")):
        return "QA & Testing"
    if any(k in low for k in ("ui", "front", "css", "design")):
        return "UI & Frontend"
    if any(k in low for k in ("model", "router", "prompt", "context")):
        return "Modelos & Router"
    if any(k in low for k in ("doc", "write", "research", "invest")):
        return "Investigación & Docs"
    if any(k in low for k in ("code", "codig", "infra", "mcp", "dev")):
        return "Código & Infra"
    return "Proyecto" if local else "Código & Infra"


def _is_shareable(name: str, path: Path, local: bool, project_root: Path | None) -> bool:
    if name in NON_DEV_SKILLS:
        return False
    if not local:
        return True
    try:
        resolved = path.resolve()
        if path.is_symlink() or path.parent.is_symlink():
            return bool(project_root and project_root.resolve() in resolved.parents)
        return bool(project_root and project_root.resolve() in resolved.parents)
    except OSError:
        return False


def parse(path: Path, local: bool = False, project_root: Path | None = None) -> Skill:
    m = FRONT.match(path.read_text(encoding="utf-8"))
    if not m:
        raise ValueError(f"{path}: missing front matter")
    meta = dict(line.split(":", 1) for line in m.group(1).splitlines() if ":" in line)
    name, desc = meta.get("name", "").strip(), meta.get("description", "").strip()
    if not name or not desc:
        raise ValueError(f"{path}: front matter needs name and description")
    if name != path.parent.name:
        raise ValueError(f"{path}: name '{name}' does not match its folder")
    cat = _infer_category(name, meta.get("category"), local)
    shareable = _is_shareable(name, path, local, project_root)
    return Skill(name, desc, m.group(2).strip(), path, local=local, category=cat, team_shareable=shareable)


def load_packaged(root: Path | None = None) -> dict[str, Skill]:
    """The skills that ship with the repository."""
    return {s.name: s for s in (parse(p, local=False) for p in sorted((root or ROOT / "skills").glob("*/SKILL.md")))}


def local_dirs(project_root: Path | None = None) -> tuple[list[Path], Path | None]:
    """Where the operator keeps skills of their own: `<project>/.harness/skills` (never committed) and `CAOS_HARNESS_SKILLS`."""
    dirs = [Path(d).expanduser() for d in os.environ.get("CAOS_HARNESS_SKILLS", "").split(":") if d.strip()]
    resolved_project = project_root
    if resolved_project is None:
        try:
            from .app import find_config
            resolved_project = find_config().parent
        except Exception:
            resolved_project = None
    if resolved_project is not None:
        dirs.insert(0, resolved_project / ".harness" / "skills")
    return [d for d in dirs if d.is_dir()], resolved_project


def load_all(root: Path | None = None, project_root: Path | None = None) -> dict[str, Skill]:
    """Packaged skills plus the operator's local ones. A local skill replaces a packaged one with the same name."""
    skills = load_packaged(root)
    if root is None:
        dirs, proj = local_dirs(project_root)
        for d in dirs:
            for p in sorted(d.glob("*/SKILL.md")):
                try:
                    s = parse(p, local=True, project_root=proj)
                except (ValueError, OSError):
                    continue
                skills[s.name] = s
    return skills


def save_local_skill(project_root: Path, name: str, description: str, body: str, category: str = "Proyecto") -> Skill:
    """Writes or updates `<project>/.harness/skills/<name>/SKILL.md` cleanly within project scope."""
    slug = (name or "").strip().lower()
    if not SKILL_SLUG.fullmatch(slug):
        raise ValueError("skill name must be lowercase letters, numbers or '-' (2-49 chars)")
    desc = " ".join((description or "").split())
    if len(desc) < 8:
        raise ValueError("skill description must be at least 8 characters")
    content_body = (body or "").strip()
    if not content_body:
        raise ValueError("skill markdown body cannot be empty")
    folder = (project_root / ".harness" / "skills" / slug).resolve()
    base = (project_root / ".harness" / "skills").resolve()
    if base not in folder.parents:
        raise ValueError("invalid skill destination")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "SKILL.md"
    cat_line = f"category: {category.strip()}\n" if category and category.strip() else ""
    text = f"---\nname: {slug}\ndescription: {desc}\n{cat_line}---\n\n{content_body}\n"
    target.write_text(text, encoding="utf-8")
    return parse(target, local=True, project_root=project_root)


def clone_to_project(project_root: Path, name: str) -> Skill:
    """Copies a packaged skill into `<project>/.harness/skills/<name>/SKILL.md`, where it is editable and replaces the packaged one for this project."""
    slug = (name or "").strip().lower()
    src = load_packaged().get(slug)
    if src is None:
        raise ValueError(f"'{slug}' is not a packaged skill")
    if (project_root / ".harness" / "skills" / slug / "SKILL.md").is_file():
        raise ValueError(f"the project already has its own '{slug}'")
    return save_local_skill(project_root, slug, src.description, src.body, src.category)


def known(name: str, root: Path | None = None) -> bool:
    """The board stores a skill by name; check the name before queuing a task with it."""
    return name in load_all(root)
