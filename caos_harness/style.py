"""The CLI's voice: the CAOS palette in the terminal. Colour only on a real terminal, never when NO_COLOR is set or
the output is piped, so scripts and tests read plain text."""
from __future__ import annotations

import os
import sys

HUESO, GRIS, TENUE, AMBAR, CHAMPAN, PLATA = (237, 234, 229), (147, 147, 143), (122, 120, 116), (201, 151, 92), (235, 211, 187), (145, 144, 141)


def enabled(stream=None) -> bool:
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


# What each state asks of the operator decides its colour: amber is "this needs you", bone is in motion, dim is closed.
STATE = {"delivered, to review": AMBAR, "verify": AMBAR, "pending@person": AMBAR, "sending": CHAMPAN, "pending": HUESO, "sent": HUESO,
         "ok": TENUE, "superseded": TENUE, "discarded": TENUE}


def state(label: str, width: int = 22, person: bool = False) -> str:
    return paint(f"{label:<{width}}", STATE.get("pending@person" if person and label == "pending" else label, GRIS))
