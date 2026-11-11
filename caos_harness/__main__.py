"""One entry point for the harness.

    python -m caos_harness <command> [options]
"""
from __future__ import annotations

import json
import runpy
import sys

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
    "init": "create harness.toml and .harness/ in this folder",
    "task": "task add \"<text>\" (--queue <agent> | --tier <tier>) [--skill <name>] · task list [--all] · task show <id>",
    "run": "send pending tasks to their agents and store what they deliver [--agent <name>]",
    "review": "review <id> ok|redo|verify|superseded [note]: nothing closes without a verdict",
    "discard": "discard <id>: drop a task that is still pending",
    "status": "counts by status, review and agent (no task text)",
    "chat": "local Ollama console: chat --model NAME [--act] \"task\"",
    "serve": "local dashboard on http://127.0.0.1:8791 [--port N]",
}


def usage() -> str:
    width = max(map(len, [*COMMANDS, *WORK])) + 2
    from . import style
    lines = [style.banner(), "", "usage: caos-harness <command> [options]      (or: python -m caos_harness <command>)", "", style.paint("Work with a project (needs harness.toml):", style.CHAMPAN)]
    lines += [f"  {name:<{width}}{help_}" for name, help_ in WORK.items()]
    lines += ["", style.paint("Measure and check the harness itself (run from the repository):", style.CHAMPAN)]
    lines += [f"  {name:<{width}}{help_}" for name, (_, help_) in COMMANDS.items()]
    lines += [f"  {'skills':<{width}}list the role skills", f"  {'trace':<{width}}trace <file.db> [run_id]: event counts, or the timeline of one run"]
    return "\n".join(lines)


def short(text: str, n: int = 72) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def work(cmd: str, rest: list[str]) -> int:
    from pathlib import Path

    from . import app, style
    try:
        if cmd == "init":
            print("created", app.init(Path.cwd()))
            return 0
        p = app.load()
        b = p.board
        if cmd == "task":
            sub, args = (rest[0], rest[1:]) if rest else ("list", [])
            if sub == "add":
                opt = {k: args[args.index(k) + 1] for k in ("--queue", "--tier", "--skill") if k in args and args.index(k) + 1 < len(args)}
                text = [a for i, a in enumerate(args) if not a.startswith("--") and (i == 0 or args[i - 1] not in ("--queue", "--tier", "--skill"))]
                if len(text) != 1:
                    raise app.ConfigError('usage: task add "<text>" (--queue <agent> | --tier <tier>) [--skill <name>]')
                tid, queue, why = app.add_task(p, text[0], opt.get("--queue"), opt.get("--skill"), opt.get("--tier"))
                print(f"task {tid} -> {queue} ({why})")
            elif sub == "list":
                rows = b.conn.execute("SELECT * FROM tasks" + ("" if "--all" in args else " WHERE status IN ('pending','sending') OR (status='sent' AND (review IS NULL OR review='verify'))") + " ORDER BY id").fetchall()
                for r in rows:
                    state = r["status"] if r["status"] != "sent" else ("delivered, to review" if r["result"] is not None and not r["review"] else (r["review"] or "sent"))
                    print(f"{style.paint(format(r['id'], '>4'), style.TENUE)}  {style.state(state, person=r['queue'] == app.PERSON)} {style.paint(format(r['queue'] or '-', '<12'), style.GRIS)} {short(r['text'])}")
                if not rows:
                    print("nothing open")
            elif sub == "show" and args:
                r = b.get(int(args[0]))
                if not r:
                    raise app.ConfigError(f"no task {args[0]}")
                print(f"task {r['id']} · {r['status']} · queue {r['queue']} · agent {r['agent'] or '-'} · skill {r['skill'] or '-'} · review {r['review'] or '-'} {('(' + r['review_note'] + ')') if r['review_note'] else ''}")
                print("\n" + r["text"])
                if r["result"] is not None:
                    print("\n--- delivered ---\n" + r["result"])
                print("\n--- trace ---")
                for e in b.trace.timeline(f"task:{r['id']}"):
                    print(f"  {e['source']:<10} {e['kind']:<11} {e['name'] or '-':<20} {e['status'] or '-':<13} {e['reason'] or ''}")
            else:
                raise app.ConfigError("usage: task add|list|show")
            return 0
        if cmd == "run":
            only = rest[rest.index("--agent") + 1] if "--agent" in rest else None
            res = app.run_pending(p, only)
            for r in res:
                print(f"task {r['id']} -> {r['agent']}: " + ("delivered, waiting for review" if r["ok"] else r["reason"]))
            if not res:
                print("nothing to send")
            return 0 if all(r["ok"] for r in res) else 1
        if cmd == "review":
            if len(rest) < 2:
                raise app.ConfigError("usage: review <id> ok|redo|verify|superseded [note]")
            ok = b.review(int(rest[0]), rest[1], " ".join(rest[2:]))
            print(f"task {rest[0]}: {rest[1]}" if ok else f"task {rest[0]}: not in a state that accepts '{rest[1]}'")
            return 0 if ok else 1
        if cmd == "discard":
            ok = bool(rest) and b.discard(int(rest[0]))
            print("discarded" if ok else "only a pending task can be discarded")
            return 0 if ok else 1
        if cmd == "status":
            st = b.stats()
            if "--json" in rest or not sys.stdout.isatty():
                print(json.dumps(st, indent=2))
                return 0
            from . import style
            print(style.banner())
            print(f"\n{st['tasks']} tasks · {st['returned_at_least_once']} returned at least once\n")
            for label, n in sorted(st["by_status"].items(), key=lambda kv: -kv[1]):
                print(f"  {style.state(label)} {n}")
            for label, n in sorted(st["review"].items(), key=lambda kv: -kv[1]):
                print(f"  {style.paint('review · ' + label, style.GRIS):<30} {n}")
            return 0
        if cmd == "chat":
            import threading
            import time
            from .engines.workstation import Run
            model = rest[rest.index("--model") + 1] if "--model" in rest and rest.index("--model") + 1 < len(rest) else "qwen3.5:4b"
            prompt_parts = [arg for i, arg in enumerate(rest) if arg not in ("--act", "--model") and (i == 0 or rest[i-1] != "--model")]
            if not prompt_parts:
                raise app.ConfigError('usage: chat --model NAME [--act] "task"')
            run = Run(p.root, " ".join(prompt_parts), model, "act" if "--act" in rest else "plan", "coder")
            threading.Thread(target=run.execute, daemon=True).start()
            seen = -1
            while True:
                snap = run.snapshot()
                if snap["status"] == "awaiting_approval" and len(snap["steps"]) - 1 != seen:
                    seen = len(snap["steps"]) - 1
                    print(f"\nCommand in {snap['workspace']}:\n{snap['steps'][seen]['input']}")
                    if not sys.stdin.isatty():
                        run.decide(seen, False)
                        print("Rejected: interactive terminal required.")
                    else:
                        run.decide(seen, input("Run with your OS permissions? [y/N] ").strip().lower() == "y")
                if snap["status"] in ("finishing", "failed"):
                    for step in snap["steps"]:
                        print(f"\n{step['status']}: {step.get('output', '')}")
                    print(snap["answer"] or snap["error"])
                    return 1 if snap["error"] else 0
                time.sleep(.2)
        if cmd == "serve":
            from .web.server import serve
            return serve(p, int(rest[rest.index("--port") + 1]) if "--port" in rest else 8791)
    except (app.ConfigError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 2


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(usage())
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "skills":
        from .skills import load_all
        for s in load_all().values():
            print(f"{s.name}: {s.description}")
        return 0
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
