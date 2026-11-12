"""TUI Tabs 3-5: Providers & Health, Operational Metrics, and Categorized Skills & Team Share."""
from __future__ import annotations

from .. import app, mcp_tools, metrics, providers, share, skills
from .common import Row, box_rows, clip, pad, wrap
from .board_view import SPLIT_AT


def provider_entries(p: app.Project, ol: dict, hosts: list[dict]) -> list[dict]:
    """The rows of Tab 3, in order: Ollama, the cloud presets, then the project's own gateways. One list for the screen and for the keys,
    so the row you see selected is the row `t`, `s` and Enter act on."""
    custom_rows = {c["id"]: c for c in providers.custom_providers(root=p.root)}
    entries: list[dict] = [
        {
            "provider": "ollama",
            "model": ol["models"][0] if ol["models"] else "qwen2.5:7b",
            "label": "Ollama (Local & LAN)",
            "ok": ol["online"],
            "status": f"online · {len(ol['models'])} modelos · {len([x for x in ol['hosts'] if x['online']])}/{len(hosts)} hosts",
        }
    ]
    for pid, spec in providers.API.items():
        ov = custom_rows.get(pid) or {}
        try:
            k, src = providers.key_for(pid, ov.get("api_key_env") or spec["env"], root=p.root)
        except providers.ProviderError:
            k, src = None, "error"
        entries.append({
            "provider": pid,
            "model": ov.get("default_model") or spec["default_model"],
            "label": spec["name"],
            "ok": bool(k),
            "status": f"key ok ({src})" if k else f"falta {ov.get('api_key_env') or spec['env']}",
        })
    for cid, cp in custom_rows.items():
        if cid in providers.API:
            continue
        entries.append({
            "provider": cid,
            "model": cp.get("default_model") or (cp.get("models") or [""])[0],
            "label": cp.get("name", cid),
            "ok": True,
            "status": clip(str(cp.get("base_url") or "custom"), 36),
        })
    return entries


def compose_providers_tab(p: app.Project, w: int, h: int, pick_i: int, last_probe: dict | None, last_smoke: dict | None, msg: str) -> tuple[list[Row], int]:
    """Renders Tab 3: Ollama hosts, API Presets, active intents and Failover policy."""
    body_h = max(6, h - 2)
    hosts = providers.ollama_hosts(p.root)
    ol = providers.probe_ollama(hosts)
    rows: list[Row] = []

    entries = provider_entries(p, ol, hosts)
    sel = max(0, min(pick_i, len(entries) - 1)) if entries else 0
    list_rows: list[Row] = []
    for i, e in enumerate(entries):
        cur = i == sel
        dot = ("● " if e["ok"] else "○ ")
        dot_st = "sageb" if e["ok"] else "coral"
        list_rows.append([
            ("› " if cur else "  ", "champagne"),
            (dot, dot_st),
            (clip(e["label"], 24).ljust(25), "rev" if cur else "bone"),
            (clip(e["model"], 24).ljust(25), "steel"),
            (clip(e["status"], max(10, w - 58)), "sage" if e["ok"] else "dim"),
        ])
    rows += box_rows("Motores · Ollama Hosts & Presets", list_rows[: max(4, body_h - 10)], w - 2, border="silver", title_style="champagne")

    intents = {k: providers.resolve_intent(k, root=p.root, local_models=ol["models"]) for k in providers.INTENTS}
    fo = providers.load_failover(p.root)
    route_lines: list[Row] = [
        [("  Rápido: ", "steel"), (clip(f"{intents['rapido']['provider']} · {intents['rapido']['model']}", 30).ljust(32), "bone"),
         ("Código: ", "steel"), (clip(f"{intents['codigo']['provider']} · {intents['codigo']['model']}", 28), "bone")],
        [("  Razonar: ", "steel"), (clip(f"{intents['razonar']['provider']} · {intents['razonar']['model']}", 29).ljust(32), "bone"),
         ("Local:  ", "steel"), (clip(f"{intents['local']['provider']} · {intents['local']['model']}", 28), "bone")],
        [("  Failover: ", "amber" if fo["enabled"] else "dim"),
         (f"{'ACTIVO' if fo['enabled'] else 'apagado'} · {fo['strategy']} → {fo['fallback_target']}{' · ' + fo['fallback_model'] if fo['fallback_model'] else ''}", "bone" if fo["enabled"] else "dim")],
    ]
    if last_smoke:
        ok_s = bool(last_smoke.get("ok"))
        route_lines.append([
            ("  Smoke test: ", "bold"),
            ("✓ OK" if ok_s else "✗ FAIL", "sageb" if ok_s else "coralb"),
            (f" · {last_smoke.get('latency_ms', 0)}ms · JSON={'ok' if last_smoke.get('json_ok') else 'no'} · Tools={'ok' if last_smoke.get('tools_ok') else 'no'} · {clip(last_smoke.get('error') or 'listo', w - 64)}", "dim"),
        ])
    elif last_probe:
        route_lines.append([
            ("  Ping test:  ", "bold"),
            ("✓ ONLINE" if last_probe.get("ok") else "✗ OFFLINE", "sageb" if last_probe.get("ok") else "coralb"),
            (f" · {clip(last_probe.get('message', ''), w - 28)}", "dim"),
        ])

    rows += box_rows("Router por intención & Verificación en vivo", route_lines, w - 2, border="silver", title_style="steelb")
    rows = rows[:body_h]
    while len(rows) < body_h:
        rows.append([])
    footer = f" [t] Ping · [s] Smoke test · [Enter] Fijar motor en Chat · [j/k] Mover · {msg}"
    rows.append([("─" * w, "silver")])
    rows.append([(clip(footer, w - 1), "dim")])
    return rows[:h], sel


def compose_metrics_tab(p: app.Project, scope: str, w: int, h: int, pick_i: int, msg: str) -> tuple[list[Row], int]:
    """Renders Tab 4: 5 concise KPI cards + per-model operational table with Smoke & Demote controls."""
    body_h = max(6, h - 2)
    snap = metrics.snapshot(p, scope=scope)
    k = snap["kpis"]
    succ = f"{k['run_success_rate'] * 100:.0f}%" if k["run_success_rate"] is not None else "n/a"
    redo = f"{k['human_redo_rate'] * 100:.0f}%" if k["human_redo_rate"] is not None else "n/a"
    p50 = f"{k['p50_latency_ms']}ms" if k["p50_latency_ms"] is not None else "n/a"
    mut = k["gates"].get("mutation")
    gate_str = f"mut {mut['caught']}/{mut['total']}" if mut else "gates sin correr"

    kpi_row: list[Row] = [
        [
            ("  Éxito ", "dim"), (f"{succ} ({k['runs_total']} runs)".ljust(16), "sageb" if k["runs_total"] else "dim"),
            ("Redo humano ", "dim"), (f"{redo}".ljust(9), "amberb" if (k["human_redo_rate"] or 0) > 0 else "bone"),
            ("p50 ", "dim"), (f"{p50}".ljust(9), "steelb"),
            ("Tokens ", "dim"), (f"{k['tokens']['total']:,}".ljust(11), "champagne"),
            ("Gates ", "dim"), (clip(gate_str, 18), "sage" if mut else "dim"),
        ]
    ]
    rows: list[Row] = box_rows(f"KPIs Operativos · {'Proyecto ' + p.root.name if scope == 'project' else 'Global'}", kpi_row, w - 2, border="silver", title_style="champagne")

    models = snap["models"]
    sel = max(0, min(pick_i, len(models) - 1)) if models else 0
    tbl: list[Row] = [
        [("  ", ""), ("Proveedor/Modelo".ljust(34), "dim"), ("Runs".rjust(6), "dim"), ("Éxito".rjust(7), "dim"), ("p50".rjust(8), "dim"), ("Err".rjust(5), "dim"), ("  Estado", "dim")],
    ]
    if not models:
        tbl.append([("  Aún no hay runs registrados en este alcance. Ejecuta un chat o smoke test.", "dim")])
    else:
        cap = max(3, body_h - 8)
        first = max(0, min(sel - cap // 2, len(models) - cap))     # the selected row is always on screen
        for i, m in enumerate(models[first : first + cap], first):
            cur = i == sel
            label = clip(f"{m['provider']} · {m['model']}", 33)
            st_lbl = "DEGRADADO" if m["demoted"] else ("SMOKE OK" if (m["last_smoke"] or {}).get("ok") else "activo")
            st_col = "coral" if m["demoted"] else ("sage" if st_lbl == "SMOKE OK" else "steel")
            tbl.append([
                ("› " if cur else "  ", "champagne"),
                (label.ljust(34), "rev" if cur else "bone"),
                (str(m["runs"]).rjust(6), "bone"),
                (f"{m['success_rate'] * 100:.0f}%".rjust(7), "sage" if m["success_rate"] >= 0.8 else "amber"),
                (f"{m['p50_ms']}ms".rjust(8), "steel"),
                (str(m["errors"]).rjust(5), "coralb" if m["errors"] else "dim"),
                ("  " + st_lbl, st_col),
            ])
    rows += box_rows("Desempeño por Modelo · Re-enrutado operativo", tbl, w - 2, border="silver", title_style="bone")
    rows = rows[:body_h]
    while len(rows) < body_h:
        rows.append([])
    footer = f" [g] Scope ({scope}) · [s] Smoke test · [d] Degradar/Restaurar en Router · {msg}"
    rows.append([("─" * w, "silver")])
    rows.append([(clip(footer, w - 1), "dim")])
    return rows[:h], sel


def _share_lines(w: int, tool_str: str, doctor_res: dict | None, pack_res: dict | None) -> list[Row]:
    lines: list[Row] = [[("  Tools & MCP: ", "steel"), (clip(tool_str, max(8, w - 18)), "dim")]]
    if doctor_res:
        clean = bool(doctor_res.get("clean"))
        lines.append([
            ("  Doctor: ", "bold"),
            ("✓ LIMPIO para compartir" if clean else f"⚠ {len(doctor_res.get('issues', []))} alerta(s)", "sageb" if clean else "coralb"),
            (f" · {doctor_res.get('scanned', 0)} archivos escaneados", "dim"),
        ])
    else:
        lines.append([("  Doctor: ", "dim"), (clip("Pulsa [c] para auditar llaves y rutas locales antes de compartir", max(8, w - 14)), "dim")])
    if pack_res and pack_res.get("ok"):
        lines.append([
            ("  Share Pack: ", "bold"),
            (f"✓ {clip(pack_res['filename'], max(8, w - 40))}", "sageb"),
            (f" ({pack_res['files_count']} archivos · {len(pack_res.get('skills_included', []))} skills)", "dim"),
        ])
    return lines


def compose_skills_share_tab(p: app.Project, w: int, h: int, pick_i: int, active_skill: str | None, doctor_res: dict | None, pack_res: dict | None, msg: str) -> tuple[list[Row], int]:
    """Renders Tab 5: Categorized Skills, active Tools/MCPs, and Share Pack / Doctor controls.

    From 120 columns it is two columns: the skills on the left, and on the right the selected skill in full (what it is for,
    an excerpt of its SKILL.md), the tools, the Doctor and the Share Pack. Narrower, the same things stack."""
    body_h = max(6, h - 2)
    all_sk = list(skills.load_all(project_root=p.root).values())
    sel = max(0, min(pick_i, len(all_sk) - 1)) if all_sk else 0
    tools = mcp_tools.discover_tools(p.root)
    tool_str = " · ".join(f"{t['name']}({t['status']})" for t in tools[:5])
    footer = f" [Enter] Usar skill · [c] Doctor · [p] Crear Share Pack .zip · {msg}"

    if w >= SPLIT_AT:
        lw = max(46, int((w - 1) * 0.42))
        rw = w - lw - 2
        cap = max(4, body_h - 3)
        start = max(0, min(sel - cap // 2, max(0, len(all_sk) - cap)))
        left_rows: list[Row] = []
        for i, sk in enumerate(all_sk[start : start + cap]):
            idx = start + i
            cur = idx == sel
            mark = "✓ " if active_skill == sk.name else ("· " if sk.team_shareable else "⊘ ")
            left_rows.append([
                ("› " if cur else "  ", "champagne"),
                (mark, "sageb" if active_skill == sk.name else ("steel" if sk.team_shareable else "dim")),
                (clip(sk.name, 20).ljust(21), "rev" if cur else "bone"),
                (clip(f"[{sk.category}]", max(6, lw - 34)), "steel"),
            ])
        left = box_rows(f"Skills ({len(all_sk)})", left_rows, lw, border="silver", title_style="champagne")

        right_rows: list[Row] = []
        if all_sk:
            sk = all_sk[sel]
            scope = "local del proyecto" if sk.local else "bundle (solo lectura)"
            right_rows += [[(clip(sk.name, rw - 6), "bone")], [(f"  {sk.category} · {scope}" + (" · solo local" if not sk.team_shareable else ""), "steel")], []]
            right_rows += [[("  " + ln, "")] for ln in wrap(sk.description, rw - 8)[:3]] + [[]]
            excerpt = [ln for ln in (sk.body or "").splitlines() if ln.strip()][: max(3, body_h - 20)]
            right_rows += [[("  SKILL.md", "dim")]] + [[("    " + clip(ln, rw - 10), "dim")] for ln in excerpt]
            right_rows.append([])
        right_rows += _share_lines(rw - 4, tool_str, doctor_res, pack_res)
        right = box_rows("Skill · Tools · Doctor · Share Pack", right_rows[: max(4, body_h - 2)], rw, border="silver", title_style="steelb")
        rows: list[Row] = []
        for i in range(max(len(left), len(right))):
            rows.append(pad(left[i][:] if i < len(left) else [], lw) + [(" ", "")] + (right[i] if i < len(right) else []))
        rows = rows[:body_h]
        while len(rows) < body_h:
            rows.append([])
        rows.append([("─" * w, "silver")])
        rows.append([(clip(footer, w - 1), "dim")])
        return rows[:h], sel

    sk_rows: list[Row] = []
    max_sk = max(4, body_h - 11)
    start = max(0, min(sel - max_sk // 2, max(0, len(all_sk) - max_sk)))
    for i, sk in enumerate(all_sk[start : start + max_sk]):
        idx = start + i
        cur = idx == sel
        mark = "✓ " if active_skill == sk.name else ("· " if sk.team_shareable else "⊘ ")
        cat_tag = f"[{sk.category}]"
        sk_rows.append([
            ("› " if cur else "  ", "champagne"),
            (mark, "sageb" if active_skill == sk.name else ("steel" if sk.team_shareable else "dim")),
            (clip(sk.name, 20).ljust(21), "rev" if cur else "bone"),
            (clip(cat_tag, 12).ljust(13), "steel"),
            (clip(sk.description, max(12, w - 44)), "dim"),
        ])
    rows = box_rows(f"Skills ({len(all_sk)}) · [Enter] activa en Chat", sk_rows, w - 2, border="silver", title_style="champagne")
    rows += box_rows("Equipo · Herramientas, Doctor & Share Pack", _share_lines(w, tool_str, doctor_res, pack_res), w - 2, border="silver", title_style="steelb")
    rows = rows[:body_h]
    while len(rows) < body_h:
        rows.append([])
    rows.append([("─" * w, "silver")])
    rows.append([(clip(footer, w - 1), "dim")])
    return rows[:h], sel
