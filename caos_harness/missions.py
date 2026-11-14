"""Zero-token workspace mission detector for Console's first-mission assistant.

Scans repository state using deterministic git, AST/symbol, and file checks only (never spends LLM tokens).
Every returned mission cites verified relative `path:line` anchors so the operator starts from real facts.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from . import app, cycle, scout, worktrees

_CODE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go"}
_MARKER_RX = re.compile(r"(?:#|//|/\*)\s*\b(TODO|FIXME|XXX)\b[:\s-]*(.{0,120})", re.I)
_TEST_FILE_RX = re.compile(r"(?:^|/)(?:tests?|__tests__)/|(?:^test_|\.test\.|\.spec\.)", re.I)


def _git_dirty_files(root: Path) -> list[str]:
    if not worktrees.is_git_repo(root):
        return []
    try:
        r = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True, timeout=3)
        if r.returncode != 0:
            return []
        files: list[str] = []
        for raw in r.stdout.splitlines():
            if len(raw) < 4:
                continue
            path = raw[3:].strip()
            if " -> " in path:
                path = path.split(" -> ", 1)[1].strip()
            path = path.strip('"')
            if path and not path.startswith(".harness/"):
                files.append(path)
        return files
    except Exception:
        return []


def _test_stems(files: list[str]) -> tuple[bool, set[str]]:
    has_tests = False
    stems: set[str] = set()
    for rel in files:
        if _TEST_FILE_RX.search(rel):
            has_tests = True
            stem = Path(rel).stem.lower()
            for prefix in ("test_",):
                if stem.startswith(prefix):
                    stem = stem[len(prefix):]
            for suffix in ("_test", ".test", ".spec"):
                if stem.endswith(suffix):
                    stem = stem[:-len(suffix)]
            if stem:
                stems.add(stem)
    return has_tests, stems


def _scan_markers_and_untested(root: Path, files: list[str], test_stems: set[str], max_files: int = 240) -> tuple[list[dict], list[dict], list[str]]:
    markers: list[dict] = []
    untested: list[dict] = []
    top_modules: list[str] = []

    for rel in files:
        if len(top_modules) < 8 and Path(rel).suffix in _CODE_EXTS and not _TEST_FILE_RX.search(rel):
            top_modules.append(rel)
        p = root / rel
        if p.suffix not in _CODE_EXTS or not p.is_file() or _TEST_FILE_RX.search(rel):
            continue
        try:
            if p.stat().st_size > 160_000:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        if len(markers) < 6:
            for idx, line in enumerate(text.splitlines(), 1):
                m = _MARKER_RX.search(line)
                if m:
                    markers.append({"cite": f"{rel}:{idx}", "tag": m.group(1).upper(), "note": " ".join(m.group(2).split())[:90]})
                    break

        if len(untested) < 6:
            stem = p.stem.lower()
            if stem not in ("__init__", "main", "index", "types", "constants", "icons") and stem not in test_stems:
                _, syms = scout._symbols(p)
                pub = [(name, line_a) for name, line_a, _ in syms if not name.startswith("_") and "." not in name]
                if pub:
                    untested.append({"cite": f"{rel}:{pub[0][1]}", "path": rel, "symbol": pub[0][0], "count": len(pub)})

        max_files -= 1
        if max_files <= 0:
            break

    return markers, untested, top_modules


def detect_missions(project: app.Project, limit: int = 4) -> dict:
    """Inspect `project.root` deterministically and return prioritized mission starters with verified citations."""
    root = Path(project.root)
    files = scout._files(root)
    has_git = worktrees.is_git_repo(root)
    has_tests, test_stems = _test_stems(files)
    dirty = _git_dirty_files(root)
    markers, untested, top_modules = _scan_markers_and_untested(root, files, test_stems)

    missions: list[dict] = []

    # 1. Recent failed cycles or Board items waiting for review/redo
    try:
        recent_cycles = cycle.recent(project, 6)
    except Exception:
        recent_cycles = []
    bad_cycle = next((c for c in recent_cycles if c.get("status") in ("verify_failed", "rejected", "conflict")), None)
    if bad_cycle:
        findings = (bad_cycle.get("review") or {}).get("findings") or []
        cites = [f["file"] for f in findings if isinstance(f, dict) and f.get("file") and (root / f["file"]).exists()][:3]
        missions.append({
            "id": "failed-cycle",
            "kind": "verify",
            "title": "Diagnosticar ciclo fallido",
            "subtitle": bad_cycle.get("reason") or f"Ciclo {bad_cycle.get('status')} en {bad_cycle.get('key', 'worktree')}",
            "prompt": f"Inspecciona por qué falló el ciclo `{bad_cycle.get('id', '')}` ({bad_cycle.get('status')}: {bad_cycle.get('reason', '')}). Propón los pasos exactos para resolverlo.",
            "mode": "plan",
            "citations": cites,
            "score": 100,
        })

    # 2. Dirty working-tree changes
    if dirty:
        cites = [f"{p}:1" for p in dirty[:3] if (root / p).is_file()]
        missions.append({
            "id": "dirty-changes",
            "kind": "diff",
            "title": f"Revisar {len(dirty)} cambio{'s' if len(dirty) != 1 else ''} local{'es' if len(dirty) != 1 else ''}",
            "subtitle": ", ".join(dirty[:3]) + (f" (+{len(dirty) - 3})" if len(dirty) > 3 else ""),
            "prompt": "Revisa los cambios sin confirmar (`git diff`): detecta riesgos, regresiones, archivos que no deberían incluirse y qué pruebas correr antes de validar.",
            "mode": "plan",
            "citations": cites,
            "score": 90,
        })

    # 3. TODO / FIXME markers in codebase
    if markers:
        cites = [m["cite"] for m in markers[:3]]
        first = markers[0]
        missions.append({
            "id": "todo-fixme",
            "kind": "debt",
            "title": f"Resolver {len(markers)} pendiente{'s' if len(markers) != 1 else ''} ({first['tag']})",
            "subtitle": f"{first['cite']} · {first['note'] or first['tag']}",
            "prompt": f"Inspecciona los marcadores pendientes encontrados en el código ({', '.join(cites)}), evalúa su impacto real y propón un plan acotado para resolver el prioritario.",
            "mode": "plan",
            "citations": cites,
            "score": 75,
        })

    # 4. Untested public modules
    if untested:
        first_u = untested[0]
        cites = [u["cite"] for u in untested[:3]]
        missions.append({
            "id": "untested-module",
            "kind": "tests",
            "title": f"Añadir tests a `{Path(first_u['path']).name}`",
            "subtitle": f"{first_u['cite']} · `{first_u['symbol']}` y {max(0, first_u['count'] - 1)} símbolo(s)",
            "prompt": f"Lee `{first_u['path']}` (empezando en `{first_u['symbol']}`), resume sus invariantes y propón pruebas unitarias enfocadas en casos límite.",
            "mode": "plan",
            "citations": cites,
            "score": 65,
        })

    # 5. Deterministic architecture tour / repo baseline
    if len(missions) < limit and top_modules:
        cites = [f"{m}:1" for m in top_modules[:3] if (root / m).is_file()]
        missions.append({
            "id": "repo-map",
            "kind": "explore",
            "title": "Mapa rápido y estado del repo",
            "subtitle": f"{len(files)} archivos indexados · {top_modules[0]}",
            "prompt": "Analiza la arquitectura principal del proyecto a partir de sus módulos clave, señala qué pruebas ejecutar primero y qué puntos conviene reforzar.",
            "mode": "plan",
            "citations": cites,
            "score": 40,
        })

    missions.sort(key=lambda m: -m["score"])
    return {
        "missions": missions[:max(1, int(limit))],
        "scanned_files": len(files),
        "has_git": has_git,
        "has_tests": has_tests,
    }
