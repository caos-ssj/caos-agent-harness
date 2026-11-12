"""Layout for the terminal, standard library only: rounded panels, aligned tables, a spinner and a redraw loop.

Everything here is a pure function of its input, or writes only to the stream it is given. Boxes and colour appear on
a real terminal (`style.fancy`); piped, the same data prints as the plain lines scripts have always read.
"""
from __future__ import annotations

import io
import re
import shutil
import sys
import threading
import time
from contextlib import redirect_stdout

from . import style

ANSI = re.compile(r"\x1b\[[0-9;]*m")
FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def strip_ansi(text: str) -> str:
    return ANSI.sub("", text)


def vlen(text: str) -> int:
    """Width on screen: colour codes take no room."""
    return len(strip_ansi(text))


def width(default: int = 100, lo: int = 48, hi: int = 140) -> int:
    return max(lo, min(hi, shutil.get_terminal_size((default, 24)).columns))


def clip(text: str, n: int) -> str:
    """Cut to `n` columns with an ellipsis. Colour is dropped from a cut cell; callers colour after clipping."""
    if vlen(text) <= n:
        return text
    return strip_ansi(text)[: max(1, n - 1)] + "…"


def pad(text: str, n: int, align: str = "<") -> str:
    gap = max(0, n - vlen(text))
    return " " * gap + text if align == ">" else text + " " * gap


def panel(title: str, lines: list[str], w: int | None = None, tone: tuple = style.PLATA, badge: str = "") -> list[str]:
    """A rounded box: `╭─ title ───── badge ─╮`. Plain (no box) when the output is not a terminal."""
    if not style.fancy():
        head = [f"{strip_ansi(title)}" + (f"  [{strip_ansi(badge)}]" if badge else "")] if title else []
        return head + [f"  {ln}" for ln in lines]
    w = w or width()
    inner = w - 4
    body = [clip(ln, inner) for ln in lines]
    t = f" {title} " if title else ""
    b = f" {badge} " if badge else ""
    fill = max(1, w - 4 - vlen(t) - vlen(b))
    top = style.paint("╭─", tone) + style.paint(t, style.CHAMPAN, True) + style.paint("─" * fill, tone) + b + style.paint("─╮", tone)
    out = [top]
    for ln in body:
        out.append(style.paint("│", tone) + " " + pad(ln, inner) + " " + style.paint("│", tone))
    out.append(style.paint("╰" + "─" * (w - 2) + "╯", tone))
    return out


def table(headers: list[str], rows: list[list[str]], aligns: str = "", widths: list[int] | None = None, w: int | None = None,
          header: bool = True, tone: tuple = style.PLATA, title: str = "") -> list[str]:
    """Columns sized to their content, the widest shrunk to fit. Boxed on a terminal, two-space columns when piped.

    `aligns` is one character per column, `<` or `>`. Cells may carry colour; widths are measured without it.
    """
    n = len(headers)
    aligns = (aligns + "<" * n)[:n]
    fancy = style.fancy()
    avail = (w or width()) - (4 + 3 * (n - 1) if fancy else 2 * (n - 1))
    cols = [max([vlen(headers[i])] + [vlen(r[i]) for r in rows]) if header or rows else 0 for i in range(n)]
    if widths:
        cols = [min(c, widths[i]) if widths[i] else c for i, c in enumerate(cols)]
    while sum(cols) > avail and max(cols) > 8:
        cols[cols.index(max(cols))] -= 1
    cell = lambda text, i: pad(clip(text, cols[i]), cols[i], aligns[i])
    if not fancy:
        out = []
        if header:
            out.append("  ".join(cell(h, i) for i, h in enumerate(headers)).rstrip())
        out += ["  ".join(cell(r[i], i) for i in range(n)).rstrip() for r in rows]
        return out
    bar = lambda l, m, r: style.paint(l + m.join("─" * (c + 2) for c in cols) + r, tone)
    side = style.paint("│", tone)
    line = lambda cells: side + (" " + (" " + side + " ").join(cells) + " ") + side
    out = [bar("╭", "┬", "╮")]
    if title:
        total = sum(c + 2 for c in cols) + (n - 1)
        out = [style.paint("╭" + "─" * total + "╮", tone), side + " " + pad(style.paint(title, style.CHAMPAN, True), total - 1) + side, bar("├", "┬", "┤")]
    if header:
        out.append(line([style.paint(pad(clip(h, cols[i]), cols[i], aligns[i]), style.TENUE) for i, h in enumerate(headers)]))
        out.append(bar("├", "┼", "┤"))
    out += [line([cell(r[i], i) for i in range(n)]) for r in rows]
    out.append(bar("╰", "┴", "╯"))
    return out


def kv(pairs: list[tuple[str, str]], key_width: int = 0) -> list[str]:
    """`label  value` lines with the labels aligned and dim."""
    kw = key_width or max((len(k) for k, _ in pairs), default=0)
    return [f"{style.dim(pad(k, kw))}  {v}" for k, v in pairs]


def elapsed(seconds: float) -> str:
    return f"{seconds * 1000:.0f} ms" if seconds < 1 else f"{seconds:.1f} s"


class Spinner:
    """`⠋ label 1.2 s` on stderr while something slow runs; a line `✓ label 1.2 s` (or `✗`) when it ends.

    Silent when stderr is not a terminal, so JSON on stdout and piped logs stay clean.
    """

    def __init__(self, label: str, stream=None, enabled: bool | None = None, interval: float = 0.09, final: bool = True):
        self.label, self.stream, self.interval, self.final = label, stream or sys.stderr, interval, final
        self.enabled = style.fancy(self.stream) if enabled is None else enabled
        self.t0 = 0.0
        self.seconds = 0.0
        self.ok = True
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def update(self, label: str) -> None:
        self.label = label

    def _draw(self) -> None:
        i = 0
        while not self._stop.wait(self.interval):
            self.stream.write(f"\r\x1b[2K{style.paint(FRAMES[i % len(FRAMES)], style.ACERO, stream=self.stream)} {self.label} {style.paint(elapsed(time.monotonic() - self.t0), style.TENUE, stream=self.stream)}")
            self.stream.flush()
            i += 1

    def __enter__(self) -> "Spinner":
        self.t0 = time.monotonic()
        if self.enabled:
            self._thread = threading.Thread(target=self._draw, daemon=True)
            self._thread.start()
        return self

    def fail(self) -> None:
        self.ok = False

    def __exit__(self, exc_type, exc, tb) -> None:
        self.seconds = time.monotonic() - self.t0
        if exc_type is not None:
            self.ok = False
        if self._thread:
            self._stop.set()
            self._thread.join(timeout=1)
            mark, tone = ("✓", style.SALVIA) if self.ok else ("✗", style.CORAL)
            self.stream.write("\r\x1b[2K")
            if self.final:
                self.stream.write(f"{style.paint(mark, tone, stream=self.stream)} {self.label} {style.paint(elapsed(self.seconds), style.TENUE, stream=self.stream)}\n")
            self.stream.flush()


def capture(fn, *args, fancy: bool | None = None, **kw) -> str:
    """What `fn` prints, as text, drawn as if for a terminal when `fancy` says so."""
    buf = io.StringIO()
    with style.force(fancy), redirect_stdout(buf):
        fn(*args, **kw)
    return buf.getvalue()


def watch(render, interval: float = 2.0, out=None, count: int | None = None, sleep=time.sleep) -> int:
    """Redraw `render()` every `interval` seconds until Ctrl-C. `count` stops after that many frames (tests, scripts)."""
    out = out or sys.stdout
    tty = out.isatty()
    n = 0
    try:
        while True:
            text = render()
            if tty:
                out.write("\x1b[H\x1b[2J")
            stamp = time.strftime("%H:%M:%S")
            out.write(text.rstrip("\n") + "\n" + style.dim(f"\nevery {interval:g} s · {stamp} · Ctrl-C stops") + "\n")
            out.flush()
            n += 1
            if count is not None and n >= count:
                return 0
            sleep(interval)
    except KeyboardInterrupt:
        return 0
