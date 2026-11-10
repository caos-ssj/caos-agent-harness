"""Evaluación contra datos de referencia con umbrales de aceptación.

Dos pasadas con la misma semilla:
  1. limpia: cobertura (cuántos responde solo) y precisión al responder; el resto se escala a una persona.
  2. con fallos inyectados: invariantes (nada perdido, nada silencioso, reintentos acotados).
Sale con código distinto de 0 si no se cumple un umbral.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .pipeline import MAX_RETRIES, process
from .sut import FlakyClient

ROOT = Path(__file__).resolve().parent.parent.parent


def load_golden(path: Path | None = None) -> list[dict]:
    path = path or ROOT / "data" / "golden.jsonl"
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def run(seed: int = 7, thresholds: dict | None = None, backend: str = "sim") -> dict:
    thresholds = thresholds or json.loads((ROOT / "thresholds.json").read_text())
    golden = load_golden()

    if backend in ("ollama", "hybrid"):
        from .llm import HybridClient, OllamaClient
        clean = OllamaClient()
        if backend == "hybrid":
            clean = HybridClient(clean.call)
    else:
        clean = FlakyClient(seed=seed)
    outs = [process(r, clean.call) for r in golden]
    scored = [(o, r) for o, r in zip(outs, golden) if r["expect"] != "reject"]
    answered = [x for x in scored if x[0].status == "ok"]
    rejects_ok = sum(1 for o, r in zip(outs, golden) if r["expect"] == "reject" and o.status == "rejected")
    n_reject = sum(1 for r in golden if r["expect"] == "reject")

    faulty = FlakyClient(seed=seed, p_timeout=0.25, p_rate_limit=0.15, p_drift=0.10)
    f_outs = [process(r, faulty.call) for r in golden]
    lost = len(golden) - len({o.id for o in f_outs})
    silent = sum(1 for o in f_outs if o.status != "ok" and not o.reason)
    max_attempts = max(o.attempts for o in f_outs)
    esc = sum(1 for o in f_outs if o.status == "escalated")

    metrics = {
        "n_golden": len(golden),
        "coverage_on_answerable": round(len(answered) / len(scored), 3),
        "precision_when_answering": round(sum(1 for o, r in answered if o.label == r["label"]) / max(1, len(answered)), 3),
        "rejects_caught": f"{rejects_ok}/{n_reject}",
        "faulty_lost_records": lost,
        "faulty_silent_failures": silent,
        "faulty_max_attempts": max_attempts,
        "faulty_escalation_rate": round(esc / len(golden), 3),
        "seed": seed,
        "backend": backend,
        "model": getattr(clean, "model", "keyword-sim"),
        "escalation_reasons_clean": {k: sum(1 for o in outs if o.reason == k) for k in sorted({o.reason for o in outs})},
    }
    checks = {
        "coverage_on_answerable >= min": metrics["coverage_on_answerable"] >= thresholds["min_coverage"],
        "precision_when_answering >= min": metrics["precision_when_answering"] >= thresholds["min_precision"],
        "all rejects caught": rejects_ok == n_reject,
        "no lost records": lost == 0,
        "no silent failures": silent == 0,
        f"attempts <= {MAX_RETRIES}": max_attempts <= MAX_RETRIES,
    }
    return {"metrics": metrics, "checks": checks, "passed": all(checks.values())}


def main() -> int:
    backend = next((a.split("=")[1] for a in sys.argv if a.startswith("--backend=")), "sim")
    res = run(backend=backend)
    print(json.dumps(res["metrics"], indent=2, ensure_ascii=False))
    for name, ok in res["checks"].items():
        print(("PASS " if ok else "FAIL ") + name)
    return 0 if res["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
