"""The CLI's voice: the CAOS palette in the terminal. Colour only on a real terminal, never when NO_COLOR is set or
the output is piped, so scripts and tests read plain text."""
from __future__ import annotations

import os
import sys

HUESO, GRIS, TENUE, AMBAR, CHAMPAN, PLATA = (237, 234, 229), (147, 147, 143), (122, 120, 116), (201, 151, 92), (235, 211, 187), (145, 144, 141)


def enabled(stream=None) -> bool:
    """Colour only on a real terminal; NO_COLOR (any value) always wins, as does TERM=dumb."""
    stream = stream or sys.stdout
    return stream.isatty() and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"


def paint(text: str, rgb: tuple, bold: bool = False, stream=None) -> str:
    if not enabled(stream):
        return text
    return f"\x1b[{'1;' if bold else ''}38;2;{rgb[0]};{rgb[1]};{rgb[2]}m{text}\x1b[0m"


def banner() -> str:
    """One line and a hairline: the name, what it is, and a rule the width of the text. Plain when piped."""
    name, what = "caos · harness", "agents you can check"
    line = f"{paint(name, HUESO, True)}  {paint(what, GRIS)}"
    return f"{line}\n{paint('─' * (len(name) + 2 + len(what)), PLATA)}"


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
TONE = {"to_review": AMBAR, "verify": AMBAR, "person": AMBAR, "sending": CHAMPAN, "pending": HUESO, "returned": HUESO, "sent": HUESO,
        "ok": TENUE, "superseded": TENUE, "discarded": TENUE}


def state(key: str, width: int = 15) -> str:
    return paint(f"{LABEL.get(key, key):<{width}}", TONE.get(key, GRIS))
