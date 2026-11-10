"""Métricas con incertidumbre: Wilson, confusión, calibración (ECE) y riesgo-cobertura."""
from __future__ import annotations

import math
from collections import Counter


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, c - h), 3), round(min(1.0, c + h), 3))


def confusion(pairs: list[tuple[str, str]]) -> dict[str, dict[str, int]]:
    out: dict[str, Counter] = {}
    for truth, pred in pairs:
        out.setdefault(truth, Counter())[pred] += 1
    return {t: dict(c) for t, c in sorted(out.items())}


def ece(items: list[tuple[float, bool]], bins: int = 5) -> float:
    """Error de calibración esperado: |confianza media - acierto| ponderado por bin."""
    if not items:
        return 0.0
    total = len(items)
    err = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        sel = [(c, ok) for c, ok in items if (lo <= c < hi) or (b == bins - 1 and c == 1.0)]
        if sel:
            err += len(sel) / total * abs(sum(c for c, _ in sel) / len(sel) - sum(ok for _, ok in sel) / len(sel))
    return round(err, 3)


def risk_coverage(items: list[tuple[float, bool]], points: int = 5) -> list[dict]:
    """Si solo respondes los casos más seguros: cobertura y precisión en cada umbral."""
    if not items:
        return []
    srt = sorted(items, key=lambda x: -x[0])
    out = []
    for i in range(1, points + 1):
        k = max(1, round(len(srt) * i / points))
        top = srt[:k]
        out.append({"coverage": round(k / len(srt), 2), "precision": round(sum(ok for _, ok in top) / k, 3),
                    "min_conf": top[-1][0]})
    return out


def percentile(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    i = min(len(s) - 1, max(0, math.ceil(q * len(s)) - 1))
    return round(s[i], 3)
