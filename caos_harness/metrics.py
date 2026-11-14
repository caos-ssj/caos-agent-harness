"""Operational telemetry and quality metrics across runs, smoke tests, and board verdicts."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import statistics
import threading
import time
from pathlib import Path

from . import providers

_LOCK = threading.RLock()


def _db_path() -> Path:
    return providers.config_home() / "telemetry.db"


def _connect() -> sqlite3.Connection:
    p = _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS telemetry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            project TEXT NOT NULL,
            root TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            intent TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL DEFAULT 'chat',
            latency_ms INTEGER NOT NULL DEFAULT 0,
            ok INTEGER NOT NULL DEFAULT 1,
            prompt_tokens INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            json_ok INTEGER,
            tools_ok INTEGER,
            failover_used TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT ''
        )
        """
    )
    return conn


def record_run(
    root: Path | None,
    provider: str,
    model: str,
    latency_ms: int,
    ok: bool,
    *,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    intent: str = "",
    kind: str = "chat",
    json_ok: bool | None = None,
    tools_ok: bool | None = None,
    failover_used: str = "",
    error: str = "",
) -> None:
    resolved = str(root.resolve()) if root else ""
    proj = root.name if root else "global"
    safe_err = providers.redact((error or "")[:200], os.environ.get(providers.API.get(provider, {}).get("env", ""), ""))
    with _LOCK:
        try:
            with _connect() as conn:
                conn.execute(
                    """
                    INSERT INTO telemetry
                    (ts, project, root, provider, model, intent, kind, latency_ms, ok, prompt_tokens, completion_tokens, json_ok, tools_ok, failover_used, error)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        time.time(),
                        proj,
                        resolved,
                        provider or "ollama",
                        model or "unknown",
                        intent or "",
                        kind or "chat",
                        max(0, int(latency_ms)),
                        1 if ok else 0,
                        max(0, int(prompt_tokens or 0)),
                        max(0, int(completion_tokens or 0)),
                        None if json_ok is None else (1 if json_ok else 0),
                        None if tools_ok is None else (1 if tools_ok else 0),
                        failover_used or "",
                        safe_err,
                    ),
                )
        except sqlite3.Error:
            pass


def _override_path(root: Path | None = None) -> Path:
    return (root / ".harness" / "router_overrides.json") if root else (providers.config_home() / "router_overrides.json")


def load_demotions(root: Path | None = None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for fp in [providers.config_home() / "router_overrides.json"] + ([root / ".harness" / "router_overrides.json"] if root else []):
        try:
            raw = json.loads(fp.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                out.update({k: v for k, v in raw.items() if isinstance(v, dict)})
        except (OSError, ValueError):
            pass
    return out


def demotion_key(provider: str | None, model: str) -> str:
    """The router's systems are Ollama models, so those keep their plain name; any other provider's model is `provider:model`,
    so a cloud model that shares a name with a local one is never degraded by mistake."""
    model = (model or "").strip()
    return model if not provider or provider == "ollama" else f"{provider}:{model}"


def set_demotion(root: Path | None, system_name: str, demoted: bool = True, reason: str = "Degraded from operational metrics") -> dict:
    name = (system_name or "").strip()
    if not name:
        raise ValueError("system name is required")
    for fp in (providers.config_home() / "router_overrides.json", *([root / ".harness" / "router_overrides.json"] if root else [])):
        try:
            cur = json.loads(fp.read_text(encoding="utf-8")) if fp.is_file() else {}
            if not isinstance(cur, dict):
                cur = {}
        except (OSError, ValueError):
            cur = {}
        if demoted:
            cur[name] = {"demoted": True, "reason": reason, "at": time.time()}
        else:
            cur.pop(name, None)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(json.dumps(cur, indent=2, ensure_ascii=False), encoding="utf-8")
    return load_demotions(root)


def _repo_gates(reports_dir: Path | None) -> dict:
    gates: dict = {"mutation": None, "eval_precision": None, "regress_status": None}
    if not reports_dir:
        return gates
    mut = reports_dir / "validation" / "mutation.md"
    if mut.is_file():
        m = re.search(r"Detectadas: \*\*(\d+)/(\d+)\*\*", mut.read_text(encoding="utf-8", errors="ignore"))
        if m:
            gates["mutation"] = {"caught": int(m.group(1)), "total": int(m.group(2))}
    ev = reports_dir / "validation" / "evaluate.json"
    if ev.is_file():
        try:
            raw = json.loads(ev.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("precision"), (int, float)):
                gates["eval_precision"] = round(float(raw["precision"]), 4)
        except (OSError, ValueError):
            pass
    reg = reports_dir / "validation" / "regress.json"
    if reg.is_file():
        try:
            raw = json.loads(reg.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                gates["regress_status"] = "pass" if raw.get("ok") else "check"
        except (OSError, ValueError):
            pass
    return gates


def snapshot(project, scope: str = "project", reports_dir: Path | None = None) -> dict:
    """Computes real operational metrics for the active project or globally across all projects."""
    scope = "global" if scope == "global" else "project"
    resolved_root = str(project.root.resolve())
    with _LOCK:
        try:
            with _connect() as conn:
                if scope == "global":
                    rows = conn.execute("SELECT * FROM telemetry WHERE kind != 'compare' ORDER BY ts DESC LIMIT 2000").fetchall()
                else:
                    rows = conn.execute("SELECT * FROM telemetry WHERE root = ? AND kind != 'compare' ORDER BY ts DESC LIMIT 1000", (resolved_root,)).fetchall()
        except sqlite3.Error:
            rows = []

    latencies = [int(r["latency_ms"]) for r in rows if int(r["latency_ms"] or 0) > 0]
    ok_count = sum(1 for r in rows if r["ok"])
    prompt_tok = sum(int(r["prompt_tokens"] or 0) for r in rows)
    comp_tok = sum(int(r["completion_tokens"] or 0) for r in rows)

    bstats = project.board.stats()
    rev_counts = bstats.get("review") or {}
    reviewed_total = sum(int(v) for v in rev_counts.values())
    returned = int(bstats.get("returned_at_least_once") or 0)
    redo_rate = round(returned / max(1, reviewed_total), 4) if reviewed_total > 0 else None

    demotions = load_demotions(project.root)
    grouped: dict[tuple[str, str], list] = {}
    for r in rows:
        grouped.setdefault((r["provider"], r["model"]), []).append(r)

    models_out = []
    for (prov, mod), items in sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        lats = [int(x["latency_ms"]) for x in items if int(x["latency_ms"] or 0) > 0]
        ok_n = sum(1 for x in items if x["ok"])
        err_n = len(items) - ok_n
        smoke = next((x for x in items if x["kind"] == "smoke"), None)
        toks = sum(int(x["prompt_tokens"] or 0) + int(x["completion_tokens"] or 0) for x in items)
        dem = demotions.get(demotion_key(prov, mod))
        models_out.append({
            "provider": prov,
            "model": mod,
            "runs": len(items),
            "ok": ok_n,
            "errors": err_n,
            "success_rate": round(ok_n / len(items), 4),
            "p50_ms": round(statistics.median(lats)) if lats else 0,
            "tokens": toks,
            "last_smoke": (
                {"ok": bool(smoke["ok"]), "ms": int(smoke["latency_ms"]), "json_ok": bool(smoke["json_ok"]), "ts": smoke["ts"]}
                if smoke is not None
                else None
            ),
            "demoted": bool(dem and dem.get("demoted")),
        })

    from . import ledger
    led = ledger.summary(project)
    return {
        "scope": scope,
        "project": project.root.name,
        "kpis": {
            "runs_total": len(rows),
            "run_success_rate": round(ok_count / len(rows), 4) if rows else None,
            "human_redo_rate": redo_rate,
            "returned": returned,
            "reviewed_total": reviewed_total,
            "p50_latency_ms": round(statistics.median(latencies)) if latencies else None,
            "tokens": {"prompt": prompt_tok, "completion": comp_tok, "total": prompt_tok + comp_tok},
            "gates": _repo_gates(reports_dir),
            "scout": {
                "briefs": led.get("scout_briefs", 0),
                "cached": led.get("scout_cached", 0),
                "paid_avoided_calls": led.get("paid_avoided_calls", 0),
            },
        },
        "models": models_out,
        "compare": compare_summary(project, scope),
    }


def export_markdown(data: dict) -> str:
    k = data["kpis"]
    succ = f"{k['run_success_rate'] * 100:.1f}%" if k["run_success_rate"] is not None else "n/a"
    redo = f"{k['human_redo_rate'] * 100:.1f}%" if k["human_redo_rate"] is not None else "n/a"
    p50 = f"{k['p50_latency_ms']} ms" if k["p50_latency_ms"] is not None else "n/a"
    mut = k["gates"].get("mutation")
    lines = [
        f"# CAOS Operational Metrics ({data['project']} · {data['scope']})",
        "",
        f"- **Runs recorded:** {k['runs_total']} · **Success rate:** {succ}",
        f"- **Human return/redo rate:** {redo} ({k['returned']}/{k['reviewed_total']})",
        f"- **Median latency (p50):** {p50}",
        f"- **Measured tokens:** {k['tokens']['total']:,}",
        f"- **Mutation gate:** {mut['caught']}/{mut['total']}" if mut else "- **Mutation gate:** not measured locally",
        "",
        "| Provider | Model | Runs | Success | p50 ms | Errors | Demoted |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for m in data["models"]:
        lines.append(
            f"| {m['provider']} | {m['model']} | {m['runs']} | {m['success_rate'] * 100:.0f}% | {m['p50_ms']} | {m['errors']} | {'yes' if m['demoted'] else 'no'} |"
        )
    if not data["models"]:
        lines.append("| — | No runs recorded yet | 0 | — | — | — | — |")
    return "\n".join(lines) + "\n"


MIN_SERIES_RUNS = 5
BUCKETS = {"hour": 3600, "day": 86400}


def series(project, scope: str = "project", bucket: str = "day", limit: int = 48) -> dict:
    """Runs, success rate and median latency per hour or day, read from the same rows as the KPIs (comparisons excluded).
    Below five runs `enough` is false and the dashboard says so instead of drawing a trend from nothing."""
    scope = "global" if scope == "global" else "project"
    if bucket not in BUCKETS:
        raise ValueError("bucket must be hour or day")
    size = BUCKETS[bucket]
    root = str(project.root.resolve())
    with _LOCK:
        try:
            with _connect() as conn:
                if scope == "global":
                    rows = conn.execute("SELECT ts, ok, latency_ms FROM telemetry WHERE kind != 'compare' ORDER BY ts DESC LIMIT 5000").fetchall()
                else:
                    rows = conn.execute("SELECT ts, ok, latency_ms FROM telemetry WHERE root = ? AND kind != 'compare' ORDER BY ts DESC LIMIT 5000", (root,)).fetchall()
        except sqlite3.Error:
            rows = []
    groups: dict[int, list] = {}
    for r in rows:
        groups.setdefault(int(r["ts"] // size) * size, []).append(r)
    points = []
    for t in sorted(groups)[-limit:]:
        g = groups[t]
        lats = [int(x["latency_ms"]) for x in g if int(x["latency_ms"] or 0) > 0]
        points.append({"t": t, "runs": len(g), "ok": sum(1 for x in g if x["ok"]), "success_rate": round(sum(1 for x in g if x["ok"]) / len(g), 4), "p50_ms": round(statistics.median(lats)) if lats else None})
    return {"scope": scope, "bucket": bucket, "min_runs": MIN_SERIES_RUNS, "total_runs": len(rows), "enough": len(rows) >= MIN_SERIES_RUNS, "points": points if len(rows) >= MIN_SERIES_RUNS else []}


def compare_summary(project, scope: str = "project") -> dict:
    """Side-by-side comparison runs, kept apart: they say how two engines answered one prompt, not how work went."""
    root = str(project.root.resolve())
    with _LOCK:
        try:
            with _connect() as conn:
                q = "SELECT provider, model, ok, latency_ms FROM telemetry WHERE kind = 'compare'" + ("" if scope == "global" else " AND root = ?") + " ORDER BY ts DESC LIMIT 400"
                rows = conn.execute(q, () if scope == "global" else (root,)).fetchall()
        except sqlite3.Error:
            rows = []
    by: dict[tuple[str, str], list] = {}
    for r in rows:
        by.setdefault((r["provider"], r["model"]), []).append(r)
    models = []
    for (prov, mod), items in sorted(by.items(), key=lambda kv: -len(kv[1])):
        lats = [int(x["latency_ms"]) for x in items if int(x["latency_ms"] or 0) > 0]
        models.append({"provider": prov, "model": mod, "runs": len(items), "ok_rate": round(sum(1 for x in items if x["ok"]) / len(items), 4), "p50_ms": round(statistics.median(lats)) if lats else None})
    return {"runs": len(rows), "models": models}
