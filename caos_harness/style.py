"""The CLI's voice: the CAOS palette in the terminal. Colour only on a real terminal, never when NO_COLOR is set or
the output is piped, so scripts and tests read plain text.

The palette is the dashboard's: copper obsidian. Champagne and copper carry the mark and the headings, and the four state
colours are used only to say what state something is in:

    steel   plan, reading, inspecting        amber   act, waiting for a person
    sage    pass, ready, key present         coral   failure, blocked, a leak
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager

# Neutrals: ivory for what you read, stone for what supports it, ash for what recedes, bronze for hairlines.
HUESO, GRIS, TENUE, PLATA = (245, 242, 236), (187, 179, 168), (154, 146, 135), (110, 88, 66)
# The mark: champagne for titles, copper for the `◈`. And the four states.
CHAMPAN, COBRE = (235, 211, 187), (226, 176, 118)
AMBAR, ACERO, SALVIA, CORAL = (238, 154, 62), (127, 166, 214), (107, 199, 142), (232, 112, 102)

_FORCE: bool | None = None   # set while a screen is redrawn into a buffer (--watch): the buffer is not a terminal, the destination is


@contextmanager
def force(value: bool | None):
    """Decide colour and boxes for what is drawn inside the block, whatever `sys.stdout` is at that moment."""
    global _FORCE
    before, _FORCE = _FORCE, value
    try:
        yield
    finally:
        _FORCE = before


def enabled(stream=None) -> bool:
    """Colour only on a real terminal; NO_COLOR (any value) always wins, as does TERM=dumb."""
    if "NO_COLOR" in os.environ or os.environ.get("TERM") == "dumb":
        return False
    if _FORCE is not None:
        return _FORCE
    stream = stream or sys.stdout
    return stream.isatty()


def fancy(stream=None) -> bool:
    """Boxes and tables on a real terminal. NO_COLOR removes colour, not structure; a dumb terminal or a pipe gets plain lines."""
    if os.environ.get("TERM") == "dumb":
        return False
    if _FORCE is not None:
        return _FORCE
    stream = stream or sys.stdout
    return stream.isatty()


def paint(text: str, rgb: tuple, bold: bool = False, stream=None) -> str:
    if not enabled(stream):
        return text
    return f"\x1b[{'1;' if bold else ''}38;2;{rgb[0]};{rgb[1]};{rgb[2]}m{text}\x1b[0m"


def banner() -> str:
    """One line and a hairline: the name, what it is, and a rule the width of the text. Plain when piped."""
    name, what = "caos · harness", "agents you can check"
    line = f"{paint('◈', COBRE)} {paint(name, HUESO, True)}  {paint(what, GRIS)}"
    return f"{line}\n{paint('─' * (len(name) + 4 + len(what)), PLATA)}"


def heading(text: str) -> str:
    return paint(text, CHAMPAN)


def dim(text: str) -> str:
    return paint(text, TENUE)


def command(name: str, what: str, width: int = 36) -> str:
    """A line of help: the command in bone, what it does in grey. Padded on the plain text, so colour never shifts a column."""
    return f"  {paint(name, HUESO)}{' ' * max(2, width - len(name))}{paint(what, GRIS)}"


# The words the desk uses for each state, so the CLI and the dashboard say the same thing.
# Amber is "this needs you", bone is in motion, dim is closed.
LABEL = {"to_review": "to review", "verify": "verify", "person": "with a person", "sending": "sending", "pending": "pending", "returned": "returned",
         "sent": "sent, no delivery", "ok": "accepted", "superseded": "superseded", "discarded": "discarded"}
TONE = {"to_review": AMBAR, "verify": AMBAR, "person": AMBAR, "sending": ACERO, "pending": HUESO, "returned": CHAMPAN, "sent": HUESO,
        "ok": SALVIA, "superseded": TENUE, "discarded": TENUE}


def state(key: str, width: int = 15) -> str:
    return paint(f"{LABEL.get(key, key):<{width}}", TONE.get(key, GRIS))


# Verdicts of the preflight, and the marks beside each line of it.
VERDICT_TONE = {"ready": SALVIA, "warning": AMBAR, "blocked": CORAL}
LEVEL_MARK = {"ok": ("✓", SALVIA), "info": ("·", TENUE), "warning": ("▲", AMBAR), "blocked": ("✗", CORAL)}
