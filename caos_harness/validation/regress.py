"""Compuerta de regresión: compara la ejecución actual con reports/baseline.json.

  python -m caos_harness.validation.regress --write   guarda la línea base (sistema simulado, determinista)
  python -m caos_harness.validation.regress           falla (código 1) si baja la precisión o la cobertura más allá de la tolerancia
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from .benchmark import evaluate_client, load
from .sut import FlakyClient

ROOT = Path(__file__).resolve().parent.parent.parent
TOL = {"precision": 0.02, "coverage": 0.03}


def current() -> dict:
    rows = load()
    c = FlakyClient(seed=7)
    m = evaluate_client(c.call, rows)
    return {"precision": m["precision"], "coverage": m["coverage"], "n": m["n"]}


def compare(base: dict, cur: dict, tol: dict = TOL) -> list[str]:
    bad = []
    for k, t in tol.items():
        if cur[k] < base[k] - t:
            bad.append(f"{k}: {cur[k]} < base {base[k]} - tolerancia {t}")
    return bad


def main() -> int:
    path = ROOT / "reports" / "validation" / "baseline.json"
    cur = current()
    if "--write" in sys.argv:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cur, indent=2))
        print("línea base guardada:", cur)
        return 0
    base = json.loads(path.read_text())
    bad = compare(base, cur)
    print("actual:", cur)
    for b in bad:
        print("REGRESIÓN", b)
    # What the dashboard's "repo gates" reads: a verdict from a real run, never a guess.
    (path.parent / "regress.json").write_text(json.dumps({"ok": not bad, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "current": cur, "baseline": base, "regressions": bad}, indent=2))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
