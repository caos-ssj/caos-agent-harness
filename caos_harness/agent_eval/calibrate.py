"""Calibra el umbral de relevancia SOLO con recuperación (sin modelo) y sin tocar las tareas de la evaluación.

  python -m caos_harness.agent_eval.calibrate [--seed 5] [--n-test 20]
Respondibles: las de consultas.jsonl que NO están en la muestra de evaluación. Fuera de alcance: CALIB_OOS, ajenas a las 4 de evaluate.py.
Escribe reports/calibracion-umbral.json con la curva. La regla inicial (conservar el 95 % de las respondibles) daba 1,0 y rechazaba
solo 6/30 fuera de alcance porque muchas sacan exactamente 1,0. Regla usada: el menor umbral de la curva que rechaza al menos el 80 %.
"""
from __future__ import annotations

import asyncio
import json
import random
import sys
from pathlib import Path

from ..memory.server import search
from .evaluate import CEREBRO, KB, norm

ROOT = Path(__file__).resolve().parent.parent.parent
CALIB_OOS = [
    "¿Cuál es la distancia entre la Tierra y la Luna?", "¿Cómo se prepara un ajiaco santafereño?", "¿Quién escribió Cien años de soledad?",
    "¿Cuántos huesos tiene el cuerpo humano adulto?", "¿Cuál es el río más largo de África?", "¿Cómo se cambia la llanta de una bicicleta?",
    "¿En qué año cayó el Muro de Berlín?", "¿Qué temperatura hace falta para hervir agua en Bogotá?", "¿Cómo se poda un rosal en invierno?",
    "¿Qué dosis de ibuprofeno toma un adulto?", "¿Cuáles son las reglas del ajedrez para el enroque?", "¿Cómo se tramita el pasaporte en Perú?",
    "¿Cuál es la capital de Australia?", "¿Qué planetas tienen anillos?", "¿Cómo se afina una guitarra acústica?",
    "¿Qué comen los pingüinos emperador?", "¿Quién pintó la Capilla Sixtina?", "¿Cómo se hace pan de masa madre en casa?",
    "¿Cuántos jugadores tiene un equipo de rugby?", "¿Cuál es la fórmula química de la sal común?", "¿Qué vacunas necesita un cachorro?",
    "¿Cómo se quita una mancha de vino de un mantel?", "¿Qué país ganó más medallas en Tokio 2020?", "¿Cómo funciona un motor de combustión de cuatro tiempos?",
    "¿Cuál es la velocidad máxima de un guepardo?", "¿Cuándo se independizó Brasil de Portugal?", "¿Qué requisitos pide una visa de turista para Japón?",
    "¿Cómo se teje una bufanda a dos agujas?", "¿Cuál es el océano más profundo?", "¿Qué significa la palabra alemana Schadenfreude?",
]


async def top(session, q):
    return await search(session, q, 3)


async def main(seed: int, n_test: int) -> dict:
    rows = [json.loads(l) for l in (CEREBRO / "evals" / "consultas.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    random.Random(seed).shuffle(rows)
    calib = rows[n_test:]
    async with KB.connect() as s:
        if True:
            ok, oos = [], []
            for row in calib:
                res = await top(s, row["pregunta"])
                if res and norm(res[0]["ruta"]) == norm(row["nota"]):
                    ok.append(res[0]["puntos"])
            for q in CALIB_OOS:
                res = await top(s, q)
                oos.append(res[0]["puntos"] if res else 0.0)
    ok.sort()
    curve = [{"threshold": t, "kept_answerable": f"{sum(x >= t for x in ok)}/{len(ok)}", "rejected_oos": f"{sum(x < t for x in oos)}/{len(oos)}"}
             for t in (1.0, 1.01, 1.05, 1.1, 1.15, 1.2, 1.3)]
    thr = next(t for t in (1.0, 1.01, 1.05, 1.1, 1.15, 1.2, 1.3) if sum(x < t for x in oos) >= 0.8 * len(oos))
    summary = {"n_answerable_calib": len(calib), "n_top1_ok": len(ok), "n_oos_calib": len(oos), "threshold": thr, "curve": curve}
    (ROOT / "reports" / "agent" / "calibracion-umbral.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    a = sys.argv[1:]
    get = lambda k, d: a[a.index(k) + 1] if k in a else d
    asyncio.run(main(int(get("--seed", 5)), int(get("--n-test", 20))))
