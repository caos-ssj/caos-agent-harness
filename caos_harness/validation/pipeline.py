"""Pipeline con reintentos acotados, comprobaciones de calidad de datos y escalamiento.

Regla central: cada registro de entrada produce EXACTAMENTE una salida, con un motivo.
Nunca se adivina ni se pierde un registro en silencio.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .sut import RateLimited

MIN_CONFIDENCE = 0.6
MAX_RETRIES = 3
VALID_LABELS = {"billing", "bug", "access", "other"}


@dataclass
class Outcome:
    id: str
    status: str            # "ok" | "escalated" | "rejected"
    label: str | None
    reason: str
    attempts: int = 0
    waits: list[float] = field(default_factory=list)


def dq_check(record: dict) -> str | None:
    text = record.get("text")
    if not isinstance(text, str) or len(text.strip()) < 5:
        return "dq_empty_or_short_text"
    return None


def process(record: dict, call: Callable[[str], dict], sleep: Callable[[float], None] = lambda s: None) -> Outcome:
    rid = str(record.get("id", "?"))
    bad = dq_check(record)
    if bad:
        return Outcome(rid, "rejected", None, bad)

    waits: list[float] = []
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            out = call(record["text"])
        except TimeoutError:
            wait = 0.5 * 2 ** (attempt - 1)
        except RateLimited as e:
            wait = max(e.retry_after, 0.5 * 2 ** (attempt - 1))
        else:
            if "label" not in out or "confidence" not in out:
                return Outcome(rid, "escalated", None, "schema_drift", attempt, waits)
            conf = out["confidence"]
            if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not 0.0 <= conf <= 1.0:
                return Outcome(rid, "escalated", None, "invalid_confidence", attempt, waits)
            if out["label"] not in VALID_LABELS:
                return Outcome(rid, "escalated", None, "invalid_label", attempt, waits)
            if out["confidence"] < MIN_CONFIDENCE:
                return Outcome(rid, "escalated", out["label"], "low_confidence", attempt, waits)
            return Outcome(rid, "ok", out["label"], "classified", attempt, waits)
        if attempt < MAX_RETRIES:
            waits.append(wait)
            sleep(wait)
    return Outcome(rid, "escalated", None, "retries_exhausted", MAX_RETRIES, waits)
