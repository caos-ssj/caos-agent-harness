"""Shared layout primitives, Unicode CAOS frames, terminal lifecycle watch, and workspace metadata helpers."""
from __future__ import annotations

import json
import select
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .. import app, workspaces

Row = list
SPIN = "|/-\\"
FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


@dataclass
class Item:
    key: str
    label: str
    hint: str = ""


def _agent_desc(a: app.Agent) -> str:
    if a.system:
        return a.system
    if a.provider and a.model:
        return f"{a.provider} · {a.model}"
    return " ".join(a.command)


def _popup_window(items: list, pick_i: int, max_items: int) -> tuple[int, list]:
    if len(items) <= max_items:
        return 0, items
    start = max(0, min(pick_i - max_items // 2, len(items) - max_items))
    return start, items[start : start + max_items]


def wrap(text: str, width: int) -> list[str]:
    width = max(12, width)
    out = []
    for raw in (text or "").splitlines() or [""]:
        while len(raw) > width:
            cut = raw.rfind(" ", 0, width)
            cut = cut if cut > width // 3 else width
            out.append(raw[:cut])
            raw = raw[cut:].lstrip()
        out.append(raw)
    return out


def skill_rows(names: list[str], width: int, lines: int = 3) -> list[Row]:
    if not names:
        return [[("  none", "dim")]]
    width = max(12, width)
    rows: list[Row] = []
    i = 0
    while i < len(names) and len(rows) < lines:
        last = len(rows) == lines - 1
        line = ""
        while i < len(names):
            name = names[i]
            cand = f"{line}, {name}" if line else name
            reserve = len(f", +{len(names) - (i + 1)} more · /skills") if (last and i + 1 < len(names)) else 0
            if len(cand) + reserve > width:
                break
            line = cand
            i += 1
        if i < len(names) and last:
            suffix = f"+{len(names) - i} more · /skills"
            line = f"{line}, {suffix}" if line else suffix
        elif not line and i < len(names):
            line = clip(names[i], width)
            i += 1
        rows.append([("  " + line, "dim")])
    return rows


def clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[: max(1, n - 1)] + "…"


def pad(runs: Row, width: int) -> Row:
    n = sum(len(t) for t, _ in runs)
    if n < width:
        return runs + [(" " * (width - n), "")]
    out, left = [], width
    for t, s in runs:
        if left <= 0:
            break
        out.append((t[:left], s))
        left -= len(t[:left])
    return out


def git_touched(p: app.Project, limit: int = 6) -> list[str] | None:
    try:
        r = subprocess.run(["git", "-C", str(p.root), "status", "--porcelain"], capture_output=True, text=True, timeout=0.6)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    files = [line[3:].strip() for line in r.stdout.splitlines() if len(line) > 3]
    return files[:limit] + ([f"+{len(files) - limit} more"] if len(files) > limit else [])


def git_branch(p: app.Project) -> str:
    try:
        r = subprocess.run(["git", "-C", str(p.root), "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, timeout=0.5)
        if r.returncode == 0:
            return r.stdout.strip() or "HEAD"
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "local"


def box_rows(title: str, body_rows: list[Row], w: int, border: str = "silver", title_style: str = "bone", pad_x: int = 1) -> list[Row]:
    """Draws a crisp CAOS Unicode card `╭─ Title ─╮` around composed body rows."""
    inner_w = max(8, w - 2 - pad_x * 2)
    t_str = f" {clip(title, max(4, w - 6))} " if title else ""
    top_fill = max(0, w - 3 - len(t_str))
    rows: list[Row] = [[("╭─", border), (t_str, title_style), ("─" * top_fill + "╮", border)]]
    sp = " " * pad_x
    for r in body_rows:
        rows.append([("│" + sp, border)] + pad(r, inner_w) + [(sp + "│", border)])
    rows.append([("╰" + "─" * max(0, w - 2) + "╯", border)])
    return rows


def sessions_dir(p: app.Project) -> Path:
    return p.root / ".harness" / "tui"


def new_id() -> str:
    t = time.time()
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(t)) + f"-{int(t * 1000) % 1000:03d}"


def settings_path() -> Path:
    return workspaces.home() / "tui.json"


def load_settings() -> dict:
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(d: dict) -> None:
    try:
        settings_path().parent.mkdir(parents=True, exist_ok=True)
        settings_path().write_text(json.dumps(d, indent=2), encoding="utf-8")
    except OSError:
        pass


def hung_up(fd: int = 0) -> bool:
    if not hasattr(select, "poll"):
        return False
    try:
        p = select.poll()
        p.register(fd, select.POLLERR | select.POLLHUP | select.POLLNVAL)
        return any(ev & (select.POLLERR | select.POLLHUP | select.POLLNVAL) for _, ev in p.poll(0))
    except OSError:
        return False


class TerminalWatch:
    """Reads keys cleanly and detects detached terminals or interrupts."""
    FAST_READS = 8

    def __init__(self, timeout_ms: int, fd: int = 0):
        self.timeout, self.fd = timeout_ms / 1000, fd
        self.fast = 0
        self.gone = False
        self.interrupts = 0
        self._old: dict = {}

    def __enter__(self):
        def leave(signum, frame):
            self.gone = True

        def interrupt(signum, frame):
            self.interrupts += 1

        for name, handler in (("SIGHUP", leave), ("SIGTERM", leave), ("SIGINT", interrupt)):
            sig = getattr(signal, name, None)
            if sig is None:
                continue
            try:
                self._old[sig] = signal.signal(sig, handler)
            except (ValueError, OSError):
                pass
        return self

    def __exit__(self, *exc):
        for sig, old in self._old.items():
            try:
                signal.signal(sig, old)
            except (ValueError, OSError, TypeError):
                pass
        self._old = {}
        return False

    def read(self, scr) -> int:
        t0 = time.monotonic()
        try:
            c = scr.getch()
        except KeyboardInterrupt:
            c = 3
        if self.interrupts:
            self.interrupts = 0
            self.fast = 0
            return 3
        if c != -1:
            self.fast = 0
            return c
        self.fast = self.fast + 1 if time.monotonic() - t0 < self.timeout / 4 else 0
        return -1

    def lost(self) -> bool:
        if not self.gone and (self.fast >= self.FAST_READS or hung_up(self.fd)):
            self.gone = True
        return self.gone


def _too_small(scr, w: int) -> None:
    import curses
    try:
        scr.addstr(0, 0, "caos · harness needs a window of at least 72 x 20"[: max(0, w - 1)])
    except curses.error:
        pass


def _wrapper(main, watch: TerminalWatch) -> None:
    import curses
    try:
        curses.wrapper(main)
    except curses.error:
        if not watch.gone:
            raise
