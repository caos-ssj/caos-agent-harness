"""The interactive session: `caos-harness` on a terminal opens it, `caos-harness repl` runs it on any input.

    caos-harness                      # banner, what waits for you, a prompt
    /task add "…" --queue echo        # slash commands mirror the CLI; Tab completes them, ↑ recalls history
    /run   /review 5 ok "why"   /status   /skills   /serve   /help   /quit

Standard library only (`readline` where the platform has it). The scripts keep working: `status`, `task list`,
`run` and friends are unchanged, and with no terminal nothing here draws colour or asks a question.
The structure (a banner with the project's tools, a status line above the prompt, `/` commands with completion) is
the common shape of terminal agents; the emblem and the words are CAOS's own.
"""
from __future__ import annotations

import io
import shlex
import shutil
import sys
import threading
import time
from contextlib import redirect_stdout
from importlib import metadata
from pathlib import Path

from . import app, style

# The mark, drawn in text: a ring inside a ring, rays between, and the single amber tick at twelve o'clock.
EMBLEM = [
    "           ╷           ",
    "   ·       ╷       ·   ",
    "     ╲           ╱     ",
    "       ╭───────╮       ",
    "       │ ╭───╮ │       ",
    " ─ ─   │ │   │ │   ─ ─ ",
    "       │ ╰───╯ │       ",
    "       ╰───────╯       ",
    "     ╱           ╲     ",
    "   ·       ╵       ·   ",
    "           ╵           ",
]
EMBLEM_WIDTH = 23

COMMANDS = {
    "/task": 'add "<text>" (--queue <agent> | --tier <tier>) · list [--all] · show <id>',
    "/run": "send what is pending to its agents [--agent <name>]",
    "/review": "<id> ok|redo|verify|superseded [note]: nothing closes without a verdict",
    "/discard": "<id>: drop a task that is still pending",
    "/status": "what waits for you, and the queues",
    "/skills": "the skills an agent can be told to read first",
    "/serve": "start the dashboard here [port], then keep working",
    "/clear": "clear the screen",
    "/help": "this list",
    "/quit": "leave (Ctrl-D does the same)",
}
ALIASES = {"/t": "/task", "/tasks": "/task", "/r": "/review", "/s": "/status", "/q": "/quit", "/exit": "/quit", "/?": "/help", "/h": "/help"}
VERDICTS = ["ok", "redo", "verify", "superseded"]


def version() -> str:
    try:
        return metadata.version("caos-agent-harness")
    except metadata.PackageNotFoundError:
        return "dev"


def _short(text: str, n: int) -> str:
    return text if len(text) <= n else text[: max(1, n - 1)] + "…"


def _rows(p: app.Project) -> list:
    order = ["to_review", "verify", "person", "sending", "pending", "returned", "sent", "ok", "superseded", "discarded"]
    rows = p.board.conn.execute("SELECT * FROM tasks ORDER BY id DESC").fetchall()
    return sorted(rows, key=lambda r: order.index(app.task_state(r)))


def queues(p: app.Project) -> list[tuple[str, int]]:
    """Open tasks held by each agent, then the person's queue: the same counts the dashboard's queue column shows."""
    open_ = [(r, app.task_state(r)) for r in p.board.conn.execute("SELECT * FROM tasks").fetchall()]
    open_ = [(r, s) for r, s in open_ if s not in ("ok", "superseded", "discarded")]
    out = [(a, sum(1 for r, _ in open_ if r["queue"] == a)) for a in p.agents]
    return out + [("a person", sum(1 for _, s in open_ if s == "person"))]


def status_line(p: app.Project) -> str:
    s = app.summary(p)
    parts = [style.dim(p.root.name)]
    parts.append(style.paint(f"{s['needs_you']} waiting for you", style.AMBAR) if s["needs_you"] else style.dim("nothing waiting"))
    if s["runnable"]:
        parts.append(style.paint(f"{s['runnable']} ready to run", style.GRIS))
    return style.dim(" · ").join(parts)


def waiting(p: app.Project, limit: int = 5, width: int = 100) -> list[str]:
    rows = [r for r in _rows(p) if app.task_state(r) in ("to_review", "verify", "person")]
    if not rows:
        return []
    lines = [style.heading(f"Waiting for you · {len(rows)}")]
    for r in rows[:limit]:
        key = app.task_state(r)
        lines.append(f"  {style.paint(format(r['id'], '>3'), style.TENUE)}  {style.state(key, 14)} {_short(r['text'], max(20, width - 24))}")
    if len(rows) > limit:
        lines.append(style.dim(f"  … and {len(rows) - limit} more: /task list"))
    return lines


def banner(p: app.Project, cols: int = 100, emblem: bool = True) -> str:
    """The opening screen: emblem and facts side by side on a wide terminal, stacked on a narrow one, then what waits."""
    from .skills import load_all
    s, st = app.summary(p), p.board.stats()
    skills = list(load_all())
    q = [f"{name} {n}" for name, n in queues(p)]
    wide = emblem and cols >= EMBLEM_WIDTH + 44
    room = max(24, cols - (EMBLEM_WIDTH + 4 if wide else 12))
    label = lambda k: style.dim(format(k, "<9"))
    facts = [
        f"{style.paint('caos · harness', style.HUESO, True)}  {style.dim(version())}",
        style.paint("agents you can check", style.GRIS),
        style.paint("─" * min(room, 38), style.PLATA),
        f"{label('project')}{style.paint(p.root.name, style.HUESO)}",
        f"{label('queues')}{_short(' · '.join(q), room - 9)}",
        f"{label('skills')}{_short(' · '.join(skills[:5]) + (f' · +{len(skills) - 5}' if len(skills) > 5 else ''), room - 9)}",
        f"{label('board')}{st['tasks']} tasks · {st['returned_at_least_once']} returned at least once",
        f"{label('waiting')}" + (style.paint(f"{s['needs_you']} for you", style.AMBAR) if s["needs_you"] else "nothing") + (f" · {s['runnable']} ready to run" if s["runnable"] else ""),
    ]
    if wide:
        art = [style.paint(row, style.AMBAR if i == 0 else style.PLATA) for i, row in enumerate(EMBLEM)]
        body = [f"{art[i]}    {facts[i - 2] if 2 <= i < 2 + len(facts) else ''}".rstrip() for i in range(len(EMBLEM))]
    else:
        body = facts
    lines = body + [""] + waiting(p, width=cols)
    lines += ["", style.dim("/ for commands · Tab completes · ↑ history · Ctrl-D leaves")]
    return "\n".join(lines)


def prompt_text(p: app.Project, tty: bool) -> str:
    """`caos ›`, with the chevron in amber while something waits for you. Escape codes are bracketed for readline."""
    needs = app.summary(p)["needs_you"]
    if not (tty and style.enabled()):
        return "caos › "
    wrap = lambda rgb, bold=False: f"\001\x1b[{'1;' if bold else ''}38;2;{rgb[0]};{rgb[1]};{rgb[2]}m\002"
    reset = "\001\x1b[0m\002"
    return f"{wrap(style.HUESO, True)}caos{reset} {wrap(style.AMBAR if needs else style.GRIS)}›{reset} "


class Session:
    def __init__(self, p: app.Project, tty: bool = False, ask=input, out=None):
        self.p, self.tty, self.ask, self.out = p, tty, ask, out or sys.stdout
        self.httpd = None
        self.last_interrupt = 0.0

    # ─ commands ─
    def handle(self, line: str) -> bool:
        """Runs one line. Returns False when the session should end."""
        line = line.strip()
        if not line:
            return True
        if line in ("?", "/"):
            self.help()
            return True
        if not line.startswith("/"):
            self.free_text(line)
            return True
        try:
            parts = shlex.split(line)
        except ValueError as e:
            print(f"error: {e}")
            return True
        cmd = ALIASES.get(parts[0].lower(), parts[0].lower())
        rest = parts[1:]
        if cmd == "/quit":
            return False
        if cmd not in COMMANDS:
            print(f"unknown command {parts[0]}. /help lists them.")
            return True
        getattr(self, "do_" + cmd[1:])(rest)
        return True

    def _work(self, cmd: str, rest: list[str]) -> None:
        from .__main__ import work
        work(cmd, rest, self.p)

    def do_task(self, rest):
        self._work("task", rest or ["list"])

    def do_run(self, rest):
        self._work("run", rest)

    def do_review(self, rest):
        if len(rest) == 2 and rest[1] == "redo":   # the dashboard asks for the same: a returned task says what to fix
            print("A redo needs a note: /review <id> redo \"what to fix\"")
            return
        self._work("review", rest)

    def do_discard(self, rest):
        self._work("discard", rest)

    def do_status(self, rest):
        print("\n".join(waiting(self.p, width=shutil.get_terminal_size((100, 24)).columns) or [style.dim("Nothing is waiting for you.")]))
        print()
        for name, n in queues(self.p):
            print(f"  {style.paint(format(name, '<16'), style.HUESO)} {n:>3} open")
        s = app.summary(self.p)
        print(style.dim(f"\n  {s['tasks']} tasks · {s['runnable']} ready to run"))

    def do_skills(self, rest):
        from .skills import load_all
        for sk in load_all().values():
            print(f"  {style.paint(format(sk.name, '<18'), style.HUESO)} {_short(sk.description, 70)}")

    def do_serve(self, rest):
        from .web.server import make_server
        if self.httpd:
            print(style.dim(f"Already serving at http://127.0.0.1:{self.httpd.server_address[1]}"))
            return
        try:
            port = int(rest[0]) if rest else 8791
            self.httpd = make_server(self.p, port)
        except (ValueError, OSError) as e:
            print(f"error: could not serve: {e}")
            return
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        print(f"The dashboard is up at {style.paint(url, style.HUESO)} (this machine only). It stops when you leave.")

    def do_clear(self, rest):
        if self.tty:
            print("\x1b[2J\x1b[H", end="")

    def do_help(self, rest=None):
        self.help()

    def help(self):
        print(style.heading("Commands"))
        for name, what in COMMANDS.items():
            print(style.command(name, what, 12))
        print(style.dim("\n  Plain text is offered as a new task. Ctrl-C clears the line; twice leaves."))

    def free_text(self, text: str) -> None:
        agent = next(iter(self.p.agents), None)
        if not agent:
            print("There is no agent in harness.toml yet. Add one, or start with /task add \"…\" --queue person.")
            return
        try:
            yes = self.ask(f"Add that as a task for {agent}? [y/N] ").strip().lower() in ("y", "yes")
        except EOFError:
            yes = False
        if yes:
            self._work("task", ["add", text, "--queue", agent])
        else:
            print(style.dim('Not added. Commands start with "/"; /help lists them.'))


def _setup_readline(p: app.Project):
    try:
        import readline
    except ImportError:
        return None
    hist = p.root / ".harness" / "repl_history"
    try:
        readline.read_history_file(hist)
    except (OSError, FileNotFoundError):
        pass
    agents = list(p.agents) + ["person"]

    def complete(text: str, state: int):
        before = readline.get_line_buffer()[: readline.get_begidx()].split()   # the words already finished
        head = ALIASES.get(before[0], before[0]) if before else ""
        if not before:
            opts = [c for c in [*COMMANDS, *ALIASES] if c.startswith(text)]
        elif head == "/review" and len(before) == 2:
            opts = [v for v in VERDICTS if v.startswith(text)]
        elif head == "/task" and len(before) == 1:
            opts = [c for c in ("add", "list", "show") if c.startswith(text)]
        elif before[-1] in ("--queue", "--agent"):
            opts = [a for a in agents if a.startswith(text)]
        elif text.startswith("--"):
            opts = [f for f in ("--queue", "--tier", "--skill", "--all", "--agent") if f.startswith(text)]
        else:
            opts = []
        return (opts + [None])[state]

    readline.set_completer_delims(" \t")
    readline.set_completer(complete)
    readline.parse_and_bind("tab: complete")
    return lambda: (hist.parent.mkdir(parents=True, exist_ok=True), readline.write_history_file(hist))


def run(p: app.Project | None = None, stdin=None, interactive: bool | None = None) -> int:
    """Opens the session. On a terminal it draws the banner and prompts; with piped input it reads one command per line, plain."""
    p = p or app.load()
    stdin = stdin or sys.stdin
    tty = (stdin.isatty() and sys.stdout.isatty()) if interactive is None else interactive
    cols = shutil.get_terminal_size((100, 24)).columns
    sess = Session(p, tty=tty, ask=input if tty else (lambda prompt: ""))   # piped input never gets a question
    save = _setup_readline(p) if tty else None
    print(banner(p, cols, emblem=tty))
    print()
    try:
        while True:
            try:
                if tty:
                    print(status_line(p))
                    line = input(prompt_text(p, tty))
                else:
                    line = stdin.readline()
                    if line == "":
                        break
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                now = time.monotonic()
                print()
                if now - sess.last_interrupt < 2:
                    break
                sess.last_interrupt = now
                print(style.dim("Ctrl-C again, or /quit, to leave."))
                continue
            if not sess.handle(line):
                break
            print()
    finally:
        if sess.httpd:
            sess.httpd.shutdown()
            sess.httpd.server_close()
        if save:
            try:
                save()
            except OSError:
                pass
    return 0
