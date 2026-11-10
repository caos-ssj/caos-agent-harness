"""Pruebas de mutación del pipeline: se rompe el código a propósito y se mide cuántas roturas detectan los tests."""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
MUTATIONS = [
    ("umbral de confianza a 0", "MIN_CONFIDENCE = 0.6", "MIN_CONFIDENCE = 0.0"),
    ("un solo reintento", "MAX_RETRIES = 3", "MAX_RETRIES = 1"),
    ("sin espera entre reintentos", "            sleep(wait)\n", "            pass\n"),
    ("cambio de esquema solo mira label", 'if "label" not in out or "confidence" not in out:', 'if "label" not in out:'),
    ("sin validar etiqueta", 'if out["label"] not in VALID_LABELS:', "if False:"),
    ("calidad de datos desactivada", "len(text.strip()) < 5", "len(text.strip()) < 0"),
    ("backoff constante", "0.5 * 2 ** (attempt - 1)\n        except RateLimited", "0.5 * 1 ** (attempt - 1)\n        except RateLimited"),
    ("ignora retry_after", "wait = max(e.retry_after, 0.5 * 2 ** (attempt - 1))", "wait = 0.5 * 2 ** (attempt - 1)"),
    ("agotado marca rejected", 'return Outcome(rid, "escalated", None, "retries_exhausted"', 'return Outcome(rid, "rejected", None, "retries_exhausted"'),
    ("acepta cualquier confianza", "or not 0.0 <= conf <= 1.0", "or False"),
    ("confianza baja responde igual", 'if out["confidence"] < MIN_CONFIDENCE:', 'if False:'),
]


BOARD = "caos_harness/board/core.py"
BOARD_MUTATIONS = [
    ("tablero: envía a un agente ocupado", "if not dispatcher.is_idle(agent):", "if False:", BOARD),
    ("tablero: reclamación sin condición (dos envíos del mismo encargo)", "WHERE id=? AND status='pending'\",\n                                        (agent", "WHERE id=?\",\n                                        (agent", BOARD),
    ("tablero: un envío fallido pierde el encargo", "UPDATE tasks SET status='pending', agent=NULL WHERE id=? AND status='sending'", "UPDATE tasks SET status='lost' WHERE id=? AND status='sending'", BOARD),
    ("tablero: un envío sin confirmar se da por enviado", 'return Assigned(False, "dispatch_unconfirmed")', "pass", BOARD),
    ("tablero: caracteres de control llegan al agente", 'text = " ".join(CONTROL_RE.sub(" ", text).split())', "text = text.strip()", BOARD),
    ("tablero: se revisa lo que aún no se entregó", "AND result IS NOT NULL AND", "AND", BOARD),
    ("tablero: una entrega devuelta sigue contando", "review=NULL, result=NULL WHERE", "review=NULL WHERE", BOARD),
    ("tablero: la devolución no lleva la nota del revisor", 'if row["review"] == "redo" and row["review_note"]:', "if False:", BOARD),
]
ROUTER = "caos_harness/router/route.py"
ROUTER_MUTATIONS = [
    ("router: usa la precisión puntual en vez del límite inferior", "elif p.precision_lo < min_precision_lo:", "elif p.precision < min_precision_lo:", ROUTER),
    ("router: elige el más caro", "best = min(ok", "best = max(ok", ROUTER),
    ("router: si nadie cumple, elige igualmente", "    if not ok:\n", "    if not ok and profiles:\n        ok = list(profiles)\n    if not ok:\n", ROUTER),
    ("router: acepta un sistema que no responde nada", "if p.n_answered == 0:", "if False:", ROUTER),
    ("router: ignora la cobertura mínima", "elif p.coverage < min_coverage:", "elif False:", ROUTER),
    ("router: se queda con la medición más vieja", "p.measured >= latest[system].measured", "p.measured < latest[system].measured", ROUTER),
    ("router: ignora el límite de latencia", "elif max_p95_s is not None and p.p95_s > max_p95_s:", "elif False:", ROUTER),
]
PIPELINE = "caos_harness/validation/pipeline.py"


def run() -> list[dict]:
    res = []
    for name, old, new, target in [(*m, PIPELINE) for m in MUTATIONS] + BOARD_MUTATIONS + ROUTER_MUTATIONS:
        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "p"
            shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".venv", "traces.db", "node_modules", "dist", ".harness"))
            f = dst / target
            src = f.read_text()
            if old not in src:
                res.append({"mutation": name, "status": "INVÁLIDA (patrón no encontrado)"})
                continue
            f.write_text(src.replace(old, new, 1))
            r = subprocess.run([sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider"], cwd=dst, capture_output=True, text=True)
            res.append({"mutation": name, "status": "detectada" if r.returncode != 0 else "SOBREVIVE"})
    return res


def main() -> int:
    res = run()
    valid = [r for r in res if not r["status"].startswith("INV")]
    killed = sum(r["status"] == "detectada" for r in valid)
    md = ["# Pruebas de mutación (pipeline de validación, tablero y router)", "", f"Detectadas: **{killed}/{len(valid)}**", "", "| Mutación | Resultado |", "|---|---|"]
    md += [f"| {r['mutation']} | {r['status']} |" for r in res]
    (ROOT / "reports" / "validation").mkdir(parents=True, exist_ok=True)
    (ROOT / "reports" / "validation" / "mutation.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    return 0 if killed == len(valid) else 1


if __name__ == "__main__":
    sys.exit(main())
