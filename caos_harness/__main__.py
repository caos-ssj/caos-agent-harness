"""One entry point for the harness.

    python -m caos_harness <command> [options]

On a terminal the output is drawn with rounded panels, aligned tables and colour; piped, the same commands print the
plain lines scripts have always read. `--json` gives data for any command that has some; a failure under `--json`
is `{"ok": false, "error": "..."}`. Exit codes: 0 done, 1 the thing failed or a check found a problem, 2 bad usage,
3 a task is waiting for a person.
"""
from __future__ import annotations

import json
import os
import runpy
import sys
from pathlib import Path

COMMANDS = {
    "demo": ("caos_harness.board.demo", "board end to end: router, two simulated agents, validation, review (no model needed)"),
    "route": ("caos_harness.router.route", "which measured system each cost-of-error tier gets"),
    "eval": ("caos_harness.validation.evaluate", "validation pipeline against acceptance thresholds"),
    "regress": ("caos_harness.validation.regress", "regression gate against the stored baseline"),
    "mutation": ("caos_harness.validation.mutation", "inject faults and count how many the tests catch"),
    "benchmark": ("caos_harness.validation.benchmark", "measure local models: precision, coverage, seconds and tokens (needs Ollama)"),
    "agent-eval": ("caos_harness.agent_eval.evaluate", "agent over a real MCP server against plain retrieval (needs Ollama and a knowledge base)"),
    "calibrate": ("caos_harness.agent_eval.calibrate", "recalculate the relevance threshold (needs a knowledge base)"),
}


WORK = {
    "tui": "the full-screen 5-tab interface (default interactive `caos-harness`) [--resume [id]]",
    "repl": "line-mode interactive session [--emblem]",
    "init": "create harness.toml and .harness/ in this folder",
    "doctor": "preflight: ready | warning | blocked, and what to do next [--dry-run] [--strict] [--json]; spends no tokens",
    "task": 'task add "<text>" (--queue <agent> | --tier <tier>) [--skill <name>] · task list [--all] [--json] [--watch] · task show <id> [--json]',
    "run": 'send pending tasks [--agent a] · or run "<text>" [--intent I [--profile P] | --provider P --model M | --agent a | --tier t] [--skill S] [--json]',
    "review": 'review <id> ok|redo|verify|superseded ["note"] [--json]: nothing closes without a verdict; a redo needs the note',
    "discard": "discard <id>: drop a task that is still pending [--json]",
    "status": "counts by status, review and agent (no task text) [--json] [--watch]",
    "chat": 'workstation console: chat [--intent rapido|codigo|razonar|local] [--profile local-first|hybrid|cloud-max] [--skill S] [--provider P] [--model NAME] [--act] [--json] "task"',
    "orchestrate": 'orchestrate "<goal>" [--orchestrator A] [--agents a,b,c] [--plan-only] [--json]: one agent splits the goal, several work in parallel, the same one writes the synthesis',
    "providers": "providers list|add|test|smoke|failover|ollama-hosts [--profile P] [--json]",
    "metrics": "metrics [--project|--global] [--md] [--json] [--watch]",
    "share": "share doctor|preview|pack|upload [--format zip|dir|tar.gz] [--dry-run] [--parent-id ID] [--json]",
    "worktree": "worktree list|diff|discard [<key>] [--json]",
    "serve": "local dashboard on http://127.0.0.1:8791 [--port N]",
    "completion": "completion bash|zsh: print a shell completion script",
}


def usage() -> str:
    width = max(map(len, [*COMMANDS, *WORK])) + 2
    from . import style
    lines = [style.banner(), "", "usage: caos-harness <command> [options]      (or: python -m caos_harness <command>)", "", style.paint("Work with a project (needs harness.toml):", style.CHAMPAN)]
    lines += [f"  {name:<{width}}{help_}" for name, help_ in WORK.items()]
    lines += ["", style.paint("Measure and check the harness itself (run from the repository):", style.CHAMPAN)]
    lines += [f"  {name:<{width}}{help_}" for name, (_, help_) in COMMANDS.items()]
    lines += [f"  {'skills':<{width}}list the role skills [--json]", f"  {'trace':<{width}}trace <file.db> [run_id]: event counts, or the timeline of one run"]
    return "\n".join(lines)


def home() -> str:
    """What `caos-harness` shows on its own: where you are, and the one or two things worth doing next."""
    from . import app, style
    lines = [style.banner(), ""]
    try:
        p = app.load()
    except app.ConfigError:
        lines += ["No project in this folder.", "", style.heading("Get started"),
                  style.command("caos-harness init", "write harness.toml and .harness/ in this folder"),
                  style.command("caos-harness demo", "watch the board end to end; no model needed"),
                  style.command("caos-harness doctor --dry-run", "check what is ready, without touching the network"),
                  style.command("caos-harness help", "every command"), ""]
        return "\n".join(lines)
    s = app.summary(p)
    word = lambda n, one, many: f"{n} {one if n == 1 else many}"
    lines += [f"{style.paint(p.root.name, style.HUESO, True)}  {style.dim(word(s['agents'], 'agent', 'agents'))}",
              f"{word(s['tasks'], 'task', 'tasks')}" + (f" · {style.paint(str(s['needs_you']) + ' waiting for you', style.AMBAR)}" if s["needs_you"] else "") + (f" · {s['runnable']} ready to run" if s["runnable"] else ""), "",
              style.heading("Next")]
    if s["needs_you"]:
        lines.append(style.command("caos-harness task list", "what is open, in the order it needs you"))
        lines.append(style.command('caos-harness review <id> ok "why"', "accept, or redo | verify | superseded"))
    if s["runnable"]:
        lines.append(style.command("caos-harness run", f"send {word(s['runnable'], 'task', 'tasks')} to their agents"))
    if not s["tasks"]:
        lines.append(style.command('caos-harness task add "…" --queue <agent>', "put the first task on the board"))
    lines += [style.command("caos-harness doctor", "is this folder ready to work in, and to share?"), style.command("caos-harness serve", "the desk, at http://127.0.0.1:8791"), style.command("caos-harness help", "every command"), ""]
    return "\n".join(lines)


def short(text: str, n: int = 72) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def _flag(args: list[str], name: str) -> str | None:
    if name not in args:
        return None
    i = args.index(name)
    if i + 1 >= len(args):
        raise ValueError(f"{name} needs a value")
    return args[i + 1]


def _pos(args: list[str], value_flags: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    skip = False
    for a in args:
        if skip:
            skip = False
            continue
        if a in value_flags:
            skip = True
            continue
        if a.startswith("--"):
            continue
        out.append(a)
    return out


def _dump(obj, force_indent: bool | None = None) -> None:
    """One JSON document on stdout: indented for a person at a terminal, compact for a script."""
    indent = 2 if (sys.stdout.isatty() if force_indent is None else force_indent) else None
    print(json.dumps(obj, ensure_ascii=False, indent=indent))


def _watching(rest: list[str], render) -> int | None:
    """`--watch [--interval S]`: redraw `render()` until Ctrl-C. Returns None when the flag is absent."""
    if "--watch" not in rest:
        return None
    from . import term
    count = _flag(rest, "--count")
    if not sys.stdout.isatty() and count is None:
        raise ValueError("--watch redraws the screen, so it needs a terminal")
    try:
        interval = float(_flag(rest, "--interval") or 2)
    except ValueError as e:
        raise ValueError("--interval takes a number of seconds") from e
    tty = sys.stdout.isatty()
    return term.watch(lambda: term.capture(render, fancy=tty), max(0.2, interval), count=int(count) if count else None)


def _validated_skill(p, name: str | None) -> str | None:
    from . import app
    if name and not app.known(name):
        raise app.ConfigError(f"unknown skill: {name} (caos-harness skills lists them)")
    return name


def _profile(rest: list[str]) -> str | None:
    from . import providers
    raw = _flag(rest, "--profile")
    return providers.normalize_profile(raw) if raw else None


# ─ providers ─

def _render_providers(payload: dict, hosts: list, ol: dict) -> None:
    from . import style, term
    if not style.fancy():
        print(f"Ollama: {'online' if ol['online'] else 'offline'} · {len(ol['models'])} models across {len(hosts)} host(s)")
        for r in payload["providers"]:
            st = f"ok ({r['source']})" if r["configured"] else "no key"
            print(f"  {r['id']:<14} {r['default_model']:<32} {st}")
        for c in payload["clis"]:
            print(f"  {c['id']:<14} {'CLI agent':<32} {('installed' if c['installed'] else 'not installed') + (', in harness.toml' if c['added'] else '')}")
        return
    online = [h for h in ol["hosts"] if h["online"]]
    host_lines = [f"{style.paint('●' if h['online'] else '○', style.SALVIA if h['online'] else style.CORAL)} {h['label'] if 'label' in h else h['id']:<14} {style.dim(h['url'])}  {len(h['models'])} model(s)" if h["online"] else f"{style.paint('○', style.CORAL)} {h.get('label', h['id']):<14} {style.dim(h['url'])}  offline" for h in ol["hosts"]]
    print("\n".join(term.panel(f"ollama · {len(online)}/{len(hosts)} online · {len(ol['models'])} models", host_lines or [style.dim("no hosts")])))
    rows = [[r["id"] + (style.dim(" custom") if r.get("custom") else ""), r["default_model"], style.paint("✓ ready", style.SALVIA) if r["configured"] else style.paint("✗ no key", style.CORAL), style.dim(r["source"])] for r in payload["providers"]]
    print("\n".join(term.table(["provider", "default model", "key", "from"], rows, title="cloud & gateways")))
    crows = [[c["id"], c["label"], style.paint("✓ installed", style.SALVIA) if c["installed"] else style.paint("not installed", style.TENUE),
              style.dim("in harness.toml" if c["added"] else "not added")] for c in payload["clis"]]
    print("\n".join(term.table(["cli", "agent", "here", "project"], crows, title="local CLI agents")))
    irows = [[k, v["provider"], v["model"], style.dim(v["reason"])] for k, v in payload["intents"].items()]
    print("\n".join(term.table(["intent", "provider", "model", "why"], irows, title=f"intents · profile {payload['profile']}")))
    fo = payload["failover"]
    print(style.dim(f"failover {'on' if fo['enabled'] else 'off'} · {fo['strategy']} → {fo['fallback_target']}{(' · ' + fo['fallback_model']) if fo['fallback_model'] else ''}"))


def _work_providers(rest: list[str], p) -> int:
    from . import metrics, providers, term
    as_json = "--json" in rest
    vflags = ("--url", "--kind", "--model", "--env", "--secret", "--name", "--target", "--strategy", "--label", "--profile")
    pos = _pos(rest, vflags)
    sub = pos[0] if pos else "list"

    if sub == "list":
        profile = providers.normalize_profile(_flag(rest, "--profile"))
        hosts = providers.ollama_hosts(p.root)
        with term.Spinner("probing Ollama", final=False):
            ol = providers.probe_ollama(hosts, timeout=0.6)
        custom = {c["id"]: c for c in providers.custom_providers(root=p.root)}
        rows = []
        for pid, spec in providers.PRESETS.items():
            try:
                k, where = providers.key_for(pid, root=p.root)
            except providers.ProviderError:
                k, where = None, "missing"
            rows.append({"id": pid, "name": spec["name"], "kind": spec["kind"], "default_model": (custom.get(pid) or {}).get("default_model") or spec["default_model"], "configured": bool(k), "source": where})
        for cid, c in custom.items():
            if cid not in providers.PRESETS:
                try:
                    k, where = providers.key_for(cid, c.get("api_key_env"), root=p.root)
                except providers.ProviderError:
                    k, where = None, "missing"
                rows.append({"id": cid, "name": c.get("name") or cid, "kind": c.get("kind", "openai"), "default_model": c.get("default_model", ""), "configured": bool(k), "source": where, "custom": True})
        bins = {Path(a.command[0]).name for a in p.agents.values() if a.command}
        clis = [{k: c[k] for k in ("id", "label", "installed", "orchestrator_capable", "models")} | {"added": providers.CLIS[c["id"]]["bin"] in bins}
                for c in providers.detect_clis()]
        payload = {"ok": True, "profile": profile, "ollama": ol, "providers": rows, "clis": clis, "failover": providers.load_failover(p.root),
                   "intents": {k: providers.resolve_intent(k, root=p.root, local_models=ol.get("models"), profile=profile) for k in providers.INTENTS}}
        if as_json:
            _dump(payload)
        else:
            _render_providers(payload, hosts, ol)
        return 0

    if sub == "test" and len(pos) >= 2:
        with term.Spinner(f"testing {pos[1]}") as sp:
            res = providers.test(pos[1], key_env=_flag(rest, "--env"), base_url=_flag(rest, "--url"), root=p.root)
            if not res.get("ok"):
                sp.fail()
        if as_json:
            print(json.dumps(res, ensure_ascii=False))
        else:
            print(res.get("message", ""))
        return 0 if res.get("ok") else 1

    if sub == "smoke" and len(pos) >= 2:
        pid = pos[1]
        model = pos[2] if len(pos) >= 3 else (_flag(rest, "--model") or providers.PRESETS.get(pid, {}).get("default_model") or "qwen2.5:7b")
        with term.Spinner(f"smoke {pid} {model}") as sp:
            res = providers.smoke_test(pid, model, base_url=_flag(rest, "--url"), key_env=_flag(rest, "--env"), root=p.root)
            if not res.get("ok"):
                sp.fail()
        metrics.record_run(p.root, pid, model, res.get("latency_ms", 0), bool(res.get("ok")), kind="smoke")
        if as_json:
            print(json.dumps(res, ensure_ascii=False))
        else:
            print(f"{pid} {model}: {'OK' if res.get('ok') else 'FAIL'} ({res.get('latency_ms', 0)} ms) {res.get('error', '')}".strip())
        return 0 if res.get("ok") else 1

    if sub == "add" and len(pos) >= 2:
        pid = pos[1]
        url = _flag(rest, "--url")
        env_name = _flag(rest, "--env")
        model = _flag(rest, "--model")
        if url or pid not in providers.PRESETS:
            providers.save_custom_provider(
                {"id": pid, "name": _flag(rest, "--name") or pid, "base_url": url or providers.PRESETS.get(pid, {}).get("base_url", ""), "kind": _flag(rest, "--kind") or "openai", "api_key_env": env_name, "default_model": model or ""},
                root=p.root,
            )
        secret = _flag(rest, "--secret")
        key_res = None
        if secret:
            storage = "keyring" if "--keyring" in rest else ("env_local" if "--env-local" in rest else "auto")
            key_res = providers.save_key(pid, secret, env_name=env_name, storage=storage, root=p.root)
        out = {"ok": True, "provider": pid, "key_saved": bool(key_res), "storage": (key_res or {}).get("storage")}
        print(json.dumps(out, ensure_ascii=False) if as_json else f"provider {pid} saved" + (f" ({out['storage']})" if key_res else ""))
        return 0

    if sub == "failover":
        upd = {}
        if len(pos) >= 2 and pos[1] in ("on", "off"):
            upd["enabled"] = pos[1] == "on"
        if _flag(rest, "--target"):
            upd["fallback_target"] = _flag(rest, "--target")
        if _flag(rest, "--model"):
            upd["fallback_model"] = _flag(rest, "--model")
        if _flag(rest, "--strategy"):
            upd["strategy"] = _flag(rest, "--strategy")
        fo = providers.save_failover({**providers.load_failover(p.root), **upd}, root=p.root) if upd else providers.load_failover(p.root)
        print(json.dumps(fo, ensure_ascii=False) if as_json else f"failover={'on' if fo['enabled'] else 'off'} strategy={fo['strategy']} target={fo['fallback_target']}:{fo['fallback_model']}")
        return 0

    if sub == "ollama-hosts":
        act = pos[1] if len(pos) >= 2 else "list"
        if act == "add" and len(pos) >= 3:
            hosts = providers.save_ollama_host(pos[2], label=_flag(rest, "--label") or "", root=p.root)
        elif act == "remove" and len(pos) >= 3:
            hosts = providers.remove_ollama_host(pos[2], root=p.root)
        else:
            hosts = providers.ollama_hosts(p.root)
        probe = providers.probe_ollama(hosts, timeout=0.8)
        print(json.dumps({"hosts": probe["hosts"], "models": probe["models"]}, ensure_ascii=False) if as_json else "\n".join(f"  {h['id']:<12} {'online' if h['online'] else 'offline':<8} {h['url']}" for h in probe["hosts"]))
        return 0

    raise ValueError("usage: providers list [--profile P]|test <id>|smoke <id> [model]|add <id>|failover [on|off]|ollama-hosts [list|add <url>|remove <id>]")


# ─ metrics ─

def _gates_text(k: dict) -> str:
    """What the repository's own gates say, in words that do not claim more than was checked."""
    gates = k.get("gates") or {}
    mut, reg = gates.get("mutation"), gates.get("regress_status")
    return f"mut {mut['caught']}/{mut['total']}" + f" · regress {reg or 'not run'}" if mut else f"regress {reg or 'not run'}"


def _print_metrics(p, scope: str) -> None:
    from . import metrics, style, term
    snap = metrics.snapshot(p, scope=scope)
    k = snap["kpis"]
    succ = f"{k['run_success_rate'] * 100:.0f}%" if k.get("run_success_rate") is not None else "n/a"
    redo = f"{k['human_redo_rate'] * 100:.0f}%" if k.get("human_redo_rate") is not None else "n/a"
    tok_total = (k.get("tokens") or {}).get("total", 0)
    p50 = k.get("p50_latency_ms") or 0
    if not style.fancy():
        print(f"Metrics ({scope}) · success={succ} · return={redo} · p50={p50}ms · tokens={tok_total} · gates={_gates_text(k)}")
        for m in snap["models"]:
            tag = " [demoted]" if m.get("demoted") else ""
            sr = f"{m['success_rate'] * 100:.0f}%" if m.get("success_rate") is not None else "n/a"
            print(f"  {m['provider']}:{m['model']:<24} runs={m['runs']:<3} ok={sr} p50={m.get('p50_ms', 0)}ms{tag}")
        return
    kv = term.kv([("success", f"{succ}  {style.dim(str(k.get('runs_total', 0)) + ' runs')}"), ("return", f"{redo}  {style.dim('tasks sent back by a person')}"),
                  ("latency", f"{p50} ms  {style.dim('median')}"), ("tokens", f"{tok_total:,}  {style.dim(str((k.get('tokens') or {}).get('prompt', 0)) + ' in · ' + str((k.get('tokens') or {}).get('completion', 0)) + ' out')}"),
                  ("gates", _gates_text(k))])
    print("\n".join(term.panel(f"metrics · {scope} · {p.root.name if scope == 'project' else 'all projects'}", kv)))
    if not snap["models"]:
        print(style.dim("no runs recorded in this scope yet: run a prompt or `caos-harness providers smoke <id>`"))
        return
    rows = []
    for m in snap["models"]:
        sr = m.get("success_rate")
        ok = style.paint(f"{sr * 100:.0f}%", style.SALVIA if sr is not None and sr >= 0.8 else style.AMBAR) if sr is not None else style.dim("n/a")
        flag = style.paint("demoted", style.CORAL) if m.get("demoted") else ((m.get("last_smoke") or {}).get("ok") and style.paint("smoke ok", style.SALVIA)) or ""
        rows.append([f"{m['provider']}:{m['model']}", str(m["runs"]), ok, f"{m.get('p50_ms', 0)} ms", str(m.get("errors", 0)), flag])
    print("\n".join(term.table(["model", "runs", "ok", "p50", "err", ""], rows, "<>>><<", title="per model")))


def _work_metrics(rest: list[str], p) -> int:
    from . import metrics
    scope = "global" if "--global" in rest else "project"
    if "--json" in rest:
        _dump(metrics.snapshot(p, scope=scope))
        return 0
    if "--md" in rest:
        print(metrics.export_markdown(metrics.snapshot(p, scope=scope)))
        return 0
    watched = _watching(rest, lambda: _print_metrics(p, scope))
    if watched is not None:
        return watched
    _print_metrics(p, scope)
    return 0


# ─ share ─

def _size(n: int) -> str:
    return f"{n} B" if n < 1024 else (f"{n / 1024:.1f} KiB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MiB")


def _print_doctor_scan(res: dict) -> None:
    from . import style, term
    if not style.fancy():
        issue_count = len(res["issues"])
        status_txt = "clean (0 issues)" if res["clean"] else f"{res.get('total_issues', issue_count)} issue(s)"
        print(f"Doctor: {status_txt} · scanned {res['scanned']}")
        for iss in res["issues"]:
            print(f"  [{iss['kind']}] {iss['path']}:{iss['line']} {iss.get('message', '')}")
        return
    badge = style.paint("✓ CLEAN", style.SALVIA, True) if res["clean"] else style.paint(f"✗ {res.get('total_issues', len(res['issues']))} ISSUE(S)", style.CORAL, True)
    print("\n".join(term.panel("share doctor", [f"{res['scanned']} file(s) scanned" + (f" · {res['unscanned']} too large or binary to scan" if res.get("unscanned") else "")], tone=style.SALVIA if res["clean"] else style.CORAL, badge=badge)))
    if res["issues"]:
        rows = [[style.paint(i["kind"], style.CORAL if i["kind"] != "private_path" else style.AMBAR), f"{i['path']}:{i['line']}" if i["line"] else i["path"], style.dim(i.get("message", ""))] for i in res["issues"]]
        print("\n".join(term.table(["kind", "where", "what"], rows)))
        if res.get("total_issues", 0) > len(res["issues"]):
            print(style.dim(f"… and {res['total_issues'] - len(res['issues'])} more"))


def _print_pack(res: dict) -> None:
    from . import style, term
    if res.get("dry_run"):
        rows = [[i["path"] + (style.dim(" sanitized") if i.get("sanitized") else ""), _size(i["size"]), (style.paint(f"{i['redacted_lines']} line(s) rewritten", style.AMBAR) if i["redacted_lines"] else "")] for i in res["included"][:40]]
        if not style.fancy():
            print(f"Share Pack preview ({res['format']}): {res['files_count']} files · {_size(res['total_bytes'])} · nothing written")
            for i in res["included"][:40]:
                print(f"  + {i['path']}" + (f"  ({i['redacted_lines']} line(s) rewritten)" if i["redacted_lines"] else ""))
            if len(res["included"]) > 40:
                print(f"  … and {len(res['included']) - 40} more")
            for g in res["generated"][:6]:
                print(f"  + {g['path']}  (generated)")
            for e in res["excluded"]:
                print(f"  - {e['path']}  ({e['reason']})")
            for c in res["sanitization"]:
                print(f"  {'ok ' if c['ok'] else 'note'} {c['label']}")
            return
        print("\n".join(term.panel(f"share pack preview · {res['format']}", [f"{res['files_count']} files · {_size(res['total_bytes'])} · {len(res['skills_included'])} team skill(s)", style.dim("nothing was written")], tone=style.ACERO)))
        print("\n".join(term.table(["included", "size", "rewritten"], rows, "<>>")))
        if len(res["included"]) > 40:
            print(style.dim(f"… and {len(res['included']) - 40} more"))
        if res["excluded"]:
            print("\n".join(term.table(["left out", "why"], [[e["path"], style.paint(e["reason"], style.CORAL)] for e in res["excluded"]])))
        print("\n".join(term.panel("sanitization", [f"{style.paint('✓', style.SALVIA) if c['ok'] else style.paint('▲', style.AMBAR)} {c['label']}" for c in res["sanitization"]])))
        return
    if not style.fancy():
        print(f"Share Pack created: {res['path']} ({res['files_count']} files)")
        if res["redacted_paths"]:
            print(f"  rewritten in the copy: {', '.join(res['redacted_paths'][:6])}" + (" …" if len(res["redacted_paths"]) > 6 else ""))
        for e in res["excluded"]:
            print(f"  left out: {e['path']} ({e['reason']})")
        print(f"  final scan: {'clean' if res['verified'] else 'NOT clean'}")
        return
    kv = term.kv([("file", res["filename"]), ("format", res["format"]), ("size", f"{_size(res['size_bytes'])} · {res['files_count']} files"),
                  ("skills", ", ".join(res["skills_included"]) or "none"), ("rewritten", f"{len(res['redacted_paths'])} file(s) had lines rewritten"),
                  ("left out", f"{len(res['excluded'])} file(s)"), ("final scan", style.paint("clean", style.SALVIA) if res["verified"] else style.paint("NOT clean", style.CORAL))])
    print("\n".join(term.panel("share pack", kv, tone=style.SALVIA if res["verified"] else style.CORAL, badge=style.paint("✓ BUILT", style.SALVIA, True))))
    print(style.dim(res["path"]))


def _work_share(rest: list[str], p) -> int:
    from . import share, term
    as_json = "--json" in rest
    vflags = ("--format", "--parent-id")
    pos = _pos(rest, vflags)
    sub = pos[0] if pos else "doctor"
    if sub == "doctor":
        with term.Spinner("scanning files", final=False):
            res = share.doctor(p.root)
        if as_json:
            _dump(res)
        else:
            _print_doctor_scan(res)
        return 0 if res["clean"] else 1
    if sub in ("pack", "preview"):
        opts = dict(include_code="--no-code" not in rest, include_docs="--no-docs" not in rest, include_skills="--no-skills" not in rest, fmt=share.normalize_format(_flag(rest, "--format")))
        if sub == "preview" or "--dry-run" in rest:
            res = share.preview_share_pack(p.root, **opts)
        else:
            with term.Spinner("building the share pack") as sp:
                res = share.build_share_pack(p.root, **opts)
                if not res["verified"]:
                    sp.fail()
        if as_json:
            _dump(res)
        else:
            _print_pack(res)
        return 0 if res.get("verified", True) else 1
    if sub == "upload" and len(pos) >= 2:
        with term.Spinner("uploading") as sp:
            res = share.upload_gdrive(Path(pos[1]), parent_id=_flag(rest, "--parent-id"))
            if not res.get("ok"):
                sp.fail()
        if as_json:
            _dump(res)
        else:
            print(res.get("message") or res.get("url") or str(res))
        return 0 if res.get("ok") else 1
    raise ValueError("usage: share doctor|preview [--format zip|dir|tar.gz]|pack [--format zip|dir|tar.gz] [--dry-run]|upload <path> [--parent-id ID]")


# ─ doctor ─

ORCHESTRATE_HELP = """usage: caos-harness orchestrate "<goal>" [--orchestrator A] [--agents a,b,c] [--plan-only] [--json]

One agent (the orchestrator) splits the goal into subtasks, each with an agent, a mode and acceptance criteria; the subtasks then run
at the same time and the orchestrator writes the synthesis from their real deliveries.

  --orchestrator A   the agent that plans and synthesises (default: the one suggested for the goal, else claude)
  --agents a,b,c     the agents that may do the work (default: every other agent in harness.toml)
  --plan-only        print the plan and stop; nothing is sent to the workers
  --json             machine-readable output

  readonly subtasks run side by side in the project folder; isolated ones edit, each in its own git worktree.
  Edit the plan before it runs from the dashboard (Console, Orquestar mode); here the plan runs as it was made."""


def _print_plan(plan: dict) -> None:
    from . import style
    print(style.heading(f"Plan · orchestrator {plan['orchestrator']} · {plan['source']}") + (f"   {style.dim(plan['summary'])}" if plan.get("summary") else ""))
    if plan.get("note"):
        print(style.dim("  note: " + plan["note"]))
    for s in plan["subtasks"]:
        print(f"  {style.paint(s['id'], style.CHAMPAN)}  {s['agent']:<10} {s['mode']:<9} {s['title']}")
        print(style.dim(f"      criteria: {s['criteria'] or '-'}"))


def _work_orchestrate(rest: list[str], p) -> int:
    """`orchestrate "<goal>"`: plan with the chosen orchestrator, then (unless --plan-only) run the plan as it is and print the synthesis."""
    from . import app, orchestrator
    pos = _pos(rest, ("--orchestrator", "--agents"))
    goal = " ".join(pos).strip()
    if not goal:
        raise app.ConfigError('usage: orchestrate "<goal>" [--orchestrator A] [--agents a,b,c] [--plan-only] [--json]')
    as_json = "--json" in rest
    opts = orchestrator.options(p, goal)
    name = _flag(rest, "--orchestrator") or opts["suggested"]["name"] or opts["default_orchestrator"]
    if name not in p.agents:
        raise app.ConfigError(f"unknown orchestrator: {name} (agents: {', '.join(p.agents) or 'none'})")
    raw_pool = _flag(rest, "--agents")
    pool = [a.strip() for a in raw_pool.split(",") if a.strip()] if raw_pool else None
    for a in pool or []:
        if a not in p.agents:
            raise app.ConfigError(f"unknown agent: {a} (agents: {', '.join(p.agents)})")
    from . import term
    with term.Spinner(f"{name} is planning") as sp:
        plan = orchestrator.plan_orchestration(p, goal, name, pool)
        if plan["source"] == "fallback":
            sp.fail()
    if "--plan-only" in rest:
        if as_json:
            _dump({"ok": True, "plan": plan})
        else:
            _print_plan(plan)
        return 0
    if not as_json:
        _print_plan(plan)
    run = orchestrator.OrchestrationRun(p, plan)
    with term.Spinner(f"{len(plan['subtasks'])} subagents working") as sp:
        run.execute()
        if run.error:
            sp.fail()
    snap = run.snapshot()
    if as_json:
        _dump({"ok": not run.error, "run": snap})
    else:
        for s in snap["orchestration"]["subtasks"]:
            print(f"task {s['task_id']} -> {s['agent']}: {s['state']}" + (f" ({s['error']})" if s["error"] else ""))
        print(f"parent task {snap['task_id']}: synthesis delivered, waiting for review")
        print(snap["answer"])
        if run.error:
            print(f"error: {run.error}", file=sys.stderr)
    return 1 if run.error else 0


def _cmd_doctor(rest: list[str], project=None) -> int:
    from . import doctor, term
    dry = "--dry-run" in rest
    with term.Spinner("checking" if dry else "checking, probing hosts", final=False):
        res = doctor.preflight(project, dry_run=dry)
    if "--json" in rest:
        _dump(res)
    else:
        print("\n".join(doctor.render(res)))
    if res["verdict"] == "blocked":
        return 1
    return 1 if ("--strict" in rest and res["verdict"] == "warning") else 0


# ─ worktree ─

def _work_worktree(rest: list[str], p) -> int:
    from . import style, term, worktrees
    as_json = "--json" in rest
    pos = _pos(rest, ())
    sub = pos[0] if pos else "list"
    if sub == "list":
        rows = list(worktrees.active_worktrees(p.root).values())
        if as_json:
            _dump(rows)
        elif style.fancy() and rows:
            print("\n".join(term.table(["key", "branch", "path"], [[w["key"], w.get("branch", ""), style.dim(w["path"])] for w in rows], title="worktrees")))
        else:
            print("\n".join(f"  {w['key']}  {w.get('branch', '')}  {w['path']}" for w in rows) or "no active worktrees")
        return 0
    if sub == "diff":
        wt = worktrees.get(p.root, pos[1]) if len(pos) >= 2 else None
        out = worktrees.workspace_diff(Path(wt["path"]) if wt else p.root)
        if as_json:
            _dump(out)
        else:
            print("\n".join(out.get("files", [])) or "clean")
            if out.get("diff"):
                print(out["diff"])
        return 0
    if sub == "discard" and len(pos) >= 2:
        out = worktrees.discard(p.root, pos[1])
        _dump(out) if as_json else print(f"discarded worktree {pos[1]}")
        return 0
    raise ValueError("usage: worktree list|diff [key]|discard <key>")


# ─ tasks and status ─

def _print_task_list(p, args: list[str]) -> None:
    from . import app, style, term
    b = p.board
    rows = [r for r in b.rows() if "--all" in args or app.task_state(r) not in ("ok", "superseded", "discarded")]
    order = ["to_review", "verify", "person", "sending", "pending", "returned", "sent", "ok", "superseded", "discarded"]
    rows.sort(key=lambda r: (order.index(app.task_state(r)), -r["id"]))
    waiting = sum(app.task_state(r) in ("to_review", "verify", "person") for r in rows)
    footer = f"{len(rows)} shown" + (f" · {waiting} waiting for you" if waiting else "") + ("" if "--all" in args else " · --all adds the closed ones")
    if style.fancy():
        if not rows:
            print("nothing open")
            return
        cells = [[style.paint(str(r["id"]), style.TENUE), style.state(app.task_state(r), 13), style.paint(app.PERSON if app.task_state(r) == "person" else (r["queue"] or "-"), style.GRIS), short(r["text"], 90)] for r in rows]
        print("\n".join(term.table(["id", "state", "queue", "task"], cells, ">" + "<<<")))
        print(style.dim(footer))
        return
    for r in rows:
        key = app.task_state(r)
        print(f"{style.paint(format(r['id'], '>4'), style.TENUE)}  {style.state(key)} {style.paint(format(app.PERSON if key == 'person' else (r['queue'] or '-'), '<12'), style.GRIS)} {short(r['text'])}")
    if not rows:
        print("nothing open")


def _print_status(p) -> None:
    from . import app, style, term
    st = p.board.stats()
    sm = app.summary(p)
    head = f"{st['tasks']} tasks · {st['returned_at_least_once']} returned at least once" + (f" · {style.paint(str(sm['needs_you']) + ' waiting for you', style.AMBAR)}" if sm["needs_you"] else "")

    def bars(items: dict, prefix: str = "") -> list[str]:
        top = max(items.values(), default=1) or 1
        return [f"{style.paint(format(prefix + label, '<22'), style.GRIS)} {style.paint('█' * max(1, round(18 * n / top)), style.ACERO if not prefix else style.CHAMPAN)} {n}" for label, n in sorted(items.items(), key=lambda kv: -kv[1])]

    if style.fancy():
        lines = [head, ""] + bars(st["by_status"])
        if st["review"]:
            lines += [""] + bars(st["review"], "review · ")
        if st["by_agent"]:
            lines += [""] + bars(st["by_agent"], "agent · ")
        print("\n".join(term.panel(f"status · {p.root.name}", lines)))
        return
    print(style.banner())
    print(f"\n{style.paint(p.root.name, style.HUESO, True)}  {head}\n")
    for label, n in sorted(st["by_status"].items(), key=lambda kv: -kv[1]):
        print(f"  {style.paint(format(label, '<22'), style.GRIS)} {n:>3}")
    print()
    for label, n in sorted(st["review"].items(), key=lambda kv: -kv[1]):
        print(f"  {style.paint(format('review · ' + label, '<22'), style.GRIS)} {n:>3}")
    if st["by_agent"]:
        print()
        for label, n in sorted(st["by_agent"].items(), key=lambda kv: -kv[1]):
            print(f"  {style.paint(format('agent · ' + label, '<22'), style.GRIS)} {n:>3}")
    print(style.dim("\n--json for the same numbers as data"))


def _print_task_show(p, r) -> None:
    from . import app, style, term
    b = p.board
    state = app.task_state(r)
    meta = f"task {r['id']} · {r['status']} · queue {r['queue']} · agent {r['agent'] or '-'} · skill {r['skill'] or '-'} · review {r['review'] or '-'} {('(' + r['review_note'] + ')') if r['review_note'] else ''}"
    trace = b.trace.timeline(f"task:{r['id']}")
    if not style.fancy():
        print(meta)
        print("\n" + r["text"])
        if r["result"] is not None:
            print("\n--- delivered ---\n" + r["result"])
        print("\n--- trace ---")
        for e in trace:
            print(f"  {e['source']:<10} {e['kind']:<11} {e['name'] or '-':<20} {e['status'] or '-':<13} {e['reason'] or ''}")
        return
    print("\n".join(term.panel(f"task {r['id']}", [r["text"], "", style.dim(f"queue {r['queue']} · agent {r['agent'] or '-'} · skill {r['skill'] or '-'}" + (f" · review {r['review']}: {r['review_note']}" if r["review"] else ""))], tone=style.TONE.get(state, style.PLATA), badge=style.state(state, 0))))
    if r["result"] is not None:
        print("\n".join(term.panel("delivered", r["result"].splitlines()[:40] or [""], tone=style.SALVIA)))
    if trace:
        print("\n".join(term.table(["source", "kind", "name", "status", "reason"], [[e["source"], e["kind"], e["name"] or "-", e["status"] or "-", style.dim(e["reason"] or "")] for e in trace], title="trace")))


def _print_chat_header(provider: str, model: str, mode: str, skill: str, profile: str | None, intent: str) -> None:
    from . import style, term
    tone = style.AMBAR if mode == "act" else style.ACERO
    badge = style.paint(mode.upper(), tone, True)
    bits = [f"{provider} · {model}"] + ([f"intent {intent}"] if intent else []) + ([f"profile {profile}"] if profile else []) + [f"skill {skill}"]
    print("\n".join(term.panel("chat", [style.dim(" · ".join(bits))], tone=tone, badge=badge)), file=sys.stderr)


def _show_approval(step: dict, workspace: str) -> str:
    """Prints what a person is asked to approve, and returns the question to ask."""
    from . import style
    pv = step.get("preview")
    if pv and not pv.get("error"):
        kind = "new file" if pv["new_file"] else "change"
        print(f"\n{style.paint('write', style.AMBAR)} {pv['path']}  {style.dim(kind + f' · +{pv['added']} -{pv['removed']} · {pv['bytes']} B')}")
        if step.get("summary_what"):
            print(style.dim(f"  {step['summary_what']}"))
        for ln in (pv.get("diff") or "").splitlines():
            tone = style.SALVIA if ln.startswith("+") and not ln.startswith("+++") else (style.CORAL if ln.startswith("-") and not ln.startswith("---") else (style.ACERO if ln.startswith("@@") else style.TENUE))
            print("  " + style.paint(ln, tone))
        if pv.get("diff_truncated"):
            print(style.dim("  … the change continues beyond this preview"))
        return "Apply this change? [y/N] "
    if pv and pv.get("error"):
        print(f"\n{style.paint('write', style.AMBAR)} {step.get('input', '')}  {style.dim(pv['error'])}")
        return "Try it anyway? [y/N] "
    print(f"\nCommand in {workspace}:\n{step['input']}")
    return "Run with your OS permissions? [y/N] "


def work(cmd: str, rest: list[str], project=None) -> int:
    from . import app, style
    try:
        if cmd == "init":
            print("created", app.init(Path.cwd()))
            return 0
        if cmd == "doctor":
            return _cmd_doctor(rest, project)
        if cmd == "orchestrate" and ("--help" in rest or "-h" in rest):
            print(ORCHESTRATE_HELP)
            return 0
        p = project or app.load()
        b = p.board
        if cmd == "orchestrate":
            return _work_orchestrate(rest, p)
        if cmd == "providers":
            return _work_providers(rest, p)
        if cmd == "metrics":
            return _work_metrics(rest, p)
        if cmd == "share":
            return _work_share(rest, p)
        if cmd == "worktree":
            return _work_worktree(rest, p)
        if cmd == "task":
            sub, args = (rest[0], rest[1:]) if rest else ("list", [])
            as_json = "--json" in args
            if sub == "add":
                opt = {k: args[args.index(k) + 1] for k in ("--queue", "--tier", "--skill") if k in args and args.index(k) + 1 < len(args)}
                text = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] not in ("--queue", "--tier", "--skill"))]
                if len(text) != 1:
                    raise app.ConfigError('usage: task add "<text>" (--queue <agent> | --tier <tier>) [--skill <name>]')
                tid, queue, why = app.add_task(p, text[0], opt.get("--queue"), opt.get("--skill"), opt.get("--tier"))
                if as_json:
                    _dump({"ok": True, "id": tid, "queue": queue, "why": why})
                else:
                    print(f"task {tid} -> {queue} ({why})")
            elif sub == "list":
                if as_json:
                    order = ["to_review", "verify", "person", "sending", "pending", "returned", "sent", "ok", "superseded", "discarded"]
                    rows = [r for r in b.rows() if "--all" in args or app.task_state(r) not in ("ok", "superseded", "discarded")]
                    rows.sort(key=lambda r: (order.index(app.task_state(r)), -r["id"]))
                    print(json.dumps([{"id": r["id"], "state": app.task_state(r), "queue": r["queue"], "agent": r["agent"], "skill": r["skill"], "text": r["text"], "review": r["review"], "review_note": r["review_note"]} for r in rows], ensure_ascii=False))
                    return 0
                watched = _watching(args, lambda: _print_task_list(p, args))
                if watched is not None:
                    return watched
                _print_task_list(p, args)
            elif sub == "show" and args:
                tid_tok = next((a for a in args if not a.startswith("--")), "")
                r = b.get(int(tid_tok))
                if not r:
                    raise app.ConfigError(f"no task {tid_tok}")
                if as_json:
                    print(json.dumps({"task": dict(r), "state": app.task_state(r), "trace": b.trace.timeline(f"task:{r['id']}")}, ensure_ascii=False))
                    return 0
                _print_task_show(p, r)
            else:
                raise app.ConfigError("usage: task add|list|show")
            return 0
        if cmd == "run":
            opts = ("--agent", "--tier", "--skill", "--intent", "--provider", "--model", "--profile")
            text = _pos(rest, opts)
            intent_val = _flag(rest, "--intent")
            prov_val = _flag(rest, "--provider")
            mod_val = _flag(rest, "--model")
            profile = _profile(rest)
            skill = _validated_skill(p, _flag(rest, "--skill"))
            if profile and not intent_val:
                raise app.ConfigError("--profile steers --intent routing: add --intent, or drop --profile")
            if text and (intent_val or prov_val):
                from . import providers, term
                from .engines.workstation import Run
                if intent_val:
                    resolved = providers.resolve_intent(intent_val, root=p.root, profile=profile)
                    prov_val, mod_val = resolved["provider"], resolved["model"]
                elif not mod_val:
                    mod_val = providers.PRESETS.get(prov_val, {}).get("default_model", "qwen3.5:4b")
                run = Run(p.root, " ".join(text), mod_val, "plan", skill or "coder", provider=prov_val, intent=intent_val or "")
                with term.Spinner(f"{prov_val} · {mod_val}") as sp:
                    run.execute()
                    snap = run.snapshot()
                    if snap["error"]:
                        sp.fail()
                if "--json" in rest:
                    print(json.dumps(snap, ensure_ascii=False))
                else:
                    print(snap["answer"] or snap["error"])
                return 0 if not snap["error"] else 1
            if text:   # one-shot: add the task, send it, print the delivery (for scripts: 0 delivered, 1 failed, 3 waits for a person)
                from . import term
                get = lambda k: rest[rest.index(k) + 1] if k in rest and rest.index(k) + 1 < len(rest) else None
                queue, tier = get("--agent"), get("--tier")
                if not queue and not tier:
                    queue = next(iter(p.agents), None)
                tid, queue, why = app.add_task(p, " ".join(text), queue, skill, tier)
                with term.Spinner(f"task {tid} → {queue}") as sp:
                    res = app.run_task(p, tid)
                    if not res["ok"]:
                        sp.fail()
                if "--json" in rest:
                    print(json.dumps({k: v for k, v in res.items()}, ensure_ascii=False))
                else:
                    print(f"task {tid} -> {queue} ({why})", file=sys.stderr)
                    if res["person"]:
                        print("waiting for a person: no agent was asked", file=sys.stderr)
                    elif res["ok"]:
                        print("delivered, waiting for review", file=sys.stderr)
                        print(res["result"])
                    else:
                        print(res["reason"], file=sys.stderr)
                return 3 if res["person"] else (0 if res["ok"] else 1)
            from . import term
            only = rest[rest.index("--agent") + 1] if "--agent" in rest else None
            with term.Spinner("sending pending tasks") as sp:
                res = app.run_pending(p, only)
                if not all(r["ok"] for r in res):
                    sp.fail()
            if "--json" in rest:
                _dump({"ok": all(r["ok"] for r in res), "results": res})
            else:
                for r in res:
                    print(f"task {r['id']} -> {r['agent']}: " + ("delivered, waiting for review" if r["ok"] else r["reason"]))
                if not res:
                    print("nothing to send")
            return 0 if all(r["ok"] for r in res) else 1
        if cmd == "review":
            pos = _pos(rest, ())
            if len(pos) < 2:
                raise app.ConfigError('usage: review <id> ok|redo|verify|superseded ["note"] [--json]')
            tid, verdict, note = int(pos[0]), pos[1], " ".join(pos[2:]).strip()
            if verdict == "redo" and not note:
                raise app.ConfigError('a redo needs a note: say what to fix, as in: review 5 redo "what to fix"')
            ok = b.review(tid, verdict, note)
            if "--json" in rest:
                _dump({"ok": ok, "id": tid, "verdict": verdict, "note": note})
            else:
                print(f"task {tid}: {verdict}" if ok else f"task {tid}: not in a state that accepts '{verdict}'")
            return 0 if ok else 1
        if cmd == "discard":
            pos = _pos(rest, ())
            ok = bool(pos) and b.discard(int(pos[0]))
            if "--json" in rest:
                _dump({"ok": ok, "id": int(pos[0]) if pos else None})
            else:
                print("discarded" if ok else "only a pending task can be discarded")
            return 0 if ok else 1
        if cmd == "status":
            if "--json" in rest or (not sys.stdout.isatty() and "--watch" not in rest):
                print(json.dumps(b.stats(), indent=2))
                return 0
            watched = _watching(rest, lambda: _print_status(p))
            if watched is not None:
                return watched
            _print_status(p)
            return 0
        if cmd == "chat":
            import threading
            import time
            from . import providers, term
            from .engines.workstation import Run
            intent_val = _flag(rest, "--intent")
            provider = _flag(rest, "--provider")
            model = _flag(rest, "--model")
            profile = _profile(rest)
            skill = _validated_skill(p, _flag(rest, "--skill"))
            if profile and not intent_val and (provider or model):
                raise app.ConfigError("--profile steers --intent routing: drop --provider/--model, or add --intent")
            if profile and not intent_val:
                intent_val = "codigo"
            if intent_val:
                resolved = providers.resolve_intent(intent_val, root=p.root, profile=profile)
                provider = provider or resolved["provider"]
                model = model or resolved["model"]
            provider = provider or "ollama"
            model = model or providers.PRESETS.get(provider, {}).get("default_model") or "qwen3.5:4b"
            prompt_parts = _pos(rest, ("--model", "--provider", "--intent", "--profile", "--skill"))
            if not prompt_parts:
                raise app.ConfigError('usage: chat [--intent I [--profile P] | --provider P --model NAME] [--skill S] [--act] [--json] "task"')
            mode = "act" if "--act" in rest else "plan"
            run = Run(p.root, " ".join(prompt_parts), model, mode, skill or "coder", provider=provider, intent=intent_val or "")
            if "--json" not in rest:
                _print_chat_header(provider, model, mode, skill or "coder", profile, intent_val or "")
            t0 = time.monotonic()
            threading.Thread(target=run.execute, daemon=True).start()
            seen = -1
            while True:
                with term.Spinner(f"{provider} · {model}", final=False) as sp:
                    while True:
                        snap = run.snapshot()
                        if snap["status"] == "awaiting_approval" and len(snap["steps"]) - 1 != seen:
                            break
                        if snap["status"] in ("finishing", "completed", "failed"):
                            break
                        if snap["steps"]:
                            sp.update(f"{provider} · {model} · {snap['steps'][-1]['name'][:50]}")
                        time.sleep(.2)
                if snap["status"] == "awaiting_approval" and len(snap["steps"]) - 1 != seen:
                    seen = len(snap["steps"]) - 1
                    question = _show_approval(snap["steps"][seen], snap["workspace"])
                    if not sys.stdin.isatty():
                        run.decide(seen, False)
                        print("Rejected: interactive terminal required.")
                    else:
                        run.decide(seen, input(question).strip().lower() == "y")
                    continue
                break
            if "--json" in rest:
                print(json.dumps(snap, ensure_ascii=False))
            else:
                for step in snap["steps"]:
                    mark = {"completed": "✓", "failed": "✗", "denied": "✗"}.get(step["status"], "·")
                    if style.fancy():
                        print(f"{style.paint(mark, style.SALVIA if mark == '✓' else style.CORAL)} {step['name']}  {style.dim(str(step.get('duration_ms', '')) + (' ms' if step.get('duration_ms') is not None else ''))}")
                    else:
                        print(f"\n{step['status']}: {step.get('output', '')}")
                print(("\n" if style.fancy() else "") + (snap["answer"] or snap["error"]))
                if style.fancy():
                    u = snap.get("usage") or {}
                    print(style.dim(f"\n{'✗ failed' if snap['error'] else '✓ done'} · {len(snap['steps'])} step(s) · {time.monotonic() - t0:.1f} s · {u.get('prompt_tokens', 0)} in / {u.get('completion_tokens', 0)} out tokens"))
            return 1 if snap["error"] else 0
        if cmd == "serve":
            from .web.server import serve
            return serve(p, int(rest[rest.index("--port") + 1]) if "--port" in rest else 8791)
    except (app.ConfigError, ValueError) as e:
        if "--json" in rest:
            _dump({"ok": False, "error": str(e)}, force_indent=False)
        else:
            print(f"error: {e}", file=sys.stderr)
        return 2
    return 2


def _skills(rest: list[str]) -> int:
    from . import app, style, term
    from .skills import load_all
    try:
        proj = app.find_config().parent
    except Exception:
        proj = None
    all_sk = load_all(project_root=proj)
    if "--json" in rest:
        print(json.dumps([{"name": s.name, "description": s.description, "category": s.category, "local": s.local, "team_shareable": s.team_shareable} for s in all_sk.values()], ensure_ascii=False))
    elif style.fancy():
        rows = [[s.name, style.dim(s.category), style.paint("local", style.CHAMPAN) if s.local else style.dim("bundle"), short(s.description, 80)] for s in all_sk.values()]
        print("\n".join(term.table(["skill", "category", "from", "description"], rows, title=f"{len(rows)} skills")))
    else:
        for s in all_sk.values():
            print(f"{s.name}: {s.description}")
    return 0


def main(argv: list[str]) -> int:
    if not argv:
        # On a terminal, `caos-harness` opens the interactive session; piped or scripted, it prints the entry screen.
        if sys.stdin.isatty() and sys.stdout.isatty():
            from . import app, repl
            try:
                p = app.load()
                if os.environ.get("CAOS_TUI") != "0":
                    try:
                        from . import tui
                        return tui.run_chat(p)
                    except ImportError:   # no curses on this platform: the line-mode session still works
                        pass
                return repl.run(p, emblem=(os.environ.get("CAOS_TUI") == "0"))
            except app.ConfigError:
                pass
        print(home())
        return 0
    if argv[0] == "tui":
        from . import app, tui
        try:
            p = app.load()
        except app.ConfigError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            print("error: the full-screen interface needs a terminal; `caos-harness repl` reads commands from a pipe", file=sys.stderr)
            return 2
        resume = None
        if "--resume" in argv or "--continue" in argv:
            i = argv.index("--resume") if "--resume" in argv else -1
            resume = argv[i + 1] if i >= 0 and i + 1 < len(argv) and not argv[i + 1].startswith("--") else ""
        return tui.run_chat(p, resume)
    if argv[0] == "repl":
        from . import app, repl
        try:
            return repl.run(app.load(), interactive=False if not sys.stdin.isatty() else None, emblem=("--emblem" in argv))
        except app.ConfigError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    if argv[0] in ("-h", "--help", "help"):
        print(usage())
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "doctor":
        return _cmd_doctor(rest)
    if cmd == "completion":
        from . import completion
        try:
            sys.stdout.write(completion.script(rest[0] if rest else ""))
            return 0
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    if cmd == "skills":
        return _skills(rest)
    if cmd == "trace":
        if not rest:
            print("usage: python -m caos_harness trace <file.db> [run_id]", file=sys.stderr)
            return 2
        from .traces.store import Trace
        t = Trace(rest[0])
        if len(rest) == 1:
            print(json.dumps(t.counts(), indent=2))
        else:
            for e in t.timeline(rest[1]):
                print(f"{e['seq']:>5}  {e['source']:<10} {e['kind']:<12} {e['name'] or '-':<22} {e['status'] or '-':<14} {e['reason'] or ''}")
        return 0
    if cmd in WORK:
        return work(cmd, rest)
    if cmd not in COMMANDS:
        print(f"unknown command: {cmd}\n\n{usage()}", file=sys.stderr)
        return 2
    if cmd in ("regress", "mutation", "benchmark", "agent-eval", "calibrate") and not (Path(__file__).resolve().parent.parent / "reports").is_dir():
        print(f"`{cmd}` writes reports and runs the repository's tests, so it needs a source checkout:\n"
              "  git clone https://gitlab.com/braynerssj26/caos-agent-harness && cd caos-agent-harness && make check", file=sys.stderr)
        return 2
    sys.argv = [COMMANDS[cmd][0], *rest]
    try:
        runpy.run_module(COMMANDS[cmd][0], run_name="__main__", alter_sys=True)
    except SystemExit as e:
        return int(e.code or 0) if not isinstance(e.code, str) else 1
    return 0


def cli() -> None:
    sys.exit(main(sys.argv[1:]))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
