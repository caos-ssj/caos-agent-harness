"""Sistema bajo prueba (simulado): clasifica tickets de soporte.

No usa ningún modelo real: es un clasificador por palabras clave con confianza, para poder
probar el *arnés* (reintentos, escalamiento, cambio de esquema, umbrales) de forma
determinista. En un proyecto real se sustituye `classify` por la llamada al LLM.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

LABELS = {
    "billing": ("factura", "cobro", "pago", "reembolso", "invoice", "refund", "charge"),
    "bug": ("error", "falla", "no funciona", "se cuelga", "crash", "bug", "timeout"),
    "access": ("contraseña", "acceso", "login", "cuenta bloqueada", "password", "locked"),
}


class RateLimited(Exception):
    def __init__(self, retry_after: float = 1.0):
        super().__init__("429")
        self.retry_after = retry_after


def classify(text: str) -> dict:
    t = text.lower()
    scores = {label: sum(k in t for k in kws) for label, kws in LABELS.items()}
    best = max(scores, key=scores.get)
    hits = scores[best]
    if hits == 0:
        return {"label": "other", "confidence": 0.3}
    ties = sum(1 for v in scores.values() if v == hits)
    conf = min(0.95, 0.55 + 0.2 * hits) - (0.25 if ties > 1 else 0)
    return {"label": best, "confidence": round(conf, 2)}


@dataclass
class FlakyClient:
    """Envuelve `classify` e inyecta fallos con una semilla fija."""
    seed: int = 0
    p_timeout: float = 0.0
    p_rate_limit: float = 0.0
    p_drift: float = 0.0

    def __post_init__(self):
        self._rng = random.Random(self.seed)
        self.calls = 0

    def call(self, text: str) -> dict:
        self.calls += 1
        r = self._rng.random()
        if r < self.p_timeout:
            raise TimeoutError("simulated timeout")
        if r < self.p_timeout + self.p_rate_limit:
            raise RateLimited(retry_after=0.5)
        out = classify(text)
        if r < self.p_timeout + self.p_rate_limit + self.p_drift:
            # el proveedor renombra un campo: cambio de esquema
            out = {"category": out["label"], "score": out["confidence"]}
        return out
