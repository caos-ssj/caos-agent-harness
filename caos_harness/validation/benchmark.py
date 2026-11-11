"""Compara modelos locales sobre el conjunto de referencia v2 y escribe reports/benchmark-<fecha>.md/json.

Uso: python -m caos_harness.validation.benchmark llama3.2:3b qwen2.5:7b [--hybrid]
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

from .llm import HybridClient, OllamaClient
from .metrics import confusion, ece, percentile, risk_coverage, wilson
from .pipeline import process

ROOT = Path(__file__).resolve().parent.parent.parent
PKG = ROOT / "caos_harness"


def load(path="golden_v2.jsonl"):
    return [json.loads(l) for l in (PKG / "data" / path).read_text(encoding="utf-8").splitlines() if l.strip()]


def evaluate_client(call, rows, client=None) -> dict:
    outs = []
    confs = {}
    for r in rows:
        # capturamos la confianza declarada para la calibración
        def spy(text, _c=call, _id=r["id"]):
            out = _c(text)
            confs[_id] = out.get("confidence") if isinstance(out, dict) else None
            return out
        outs.append((r, process({"id": r["id"], "text": r["text"]}, spy)))
    ans = [(r, o) for r, o in outs if r["expect"] != "reject"]
    answered = [(r, o) for r, o in ans if o.status == "ok"]
    correct = [(r, o) for r, o in answered if o.label == r["label"]]
    esc = [(r, o) for r, o in ans if o.status == "escalated"]
    # escalar un caso que el modelo habría fallado es un acierto del sistema; escalar uno correcto es costo
    items = [(confs.get(r["id"]) or 0.0, o.label == r["label"]) for r, o in answered]
    n_rej = sum(1 for r, _ in outs if r["expect"] == "reject")
    lat = list(getattr(client, "latencies", []))
    return {
        "n": len(rows), "n_answerable": len(ans), "answered": len(answered),
        "coverage": round(len(answered) / len(ans), 3),
        "precision": round(len(correct) / max(1, len(answered)), 3),
        "precision_ci95": wilson(len(correct), len(answered)),
        "coverage_ci95": wilson(len(answered), len(ans)),
        "escalated": len(esc),
        "rejects_caught": f"{sum(1 for r, o in outs if r['expect']=='reject' and o.status=='rejected')}/{n_rej}",
        "ece": ece(items),
        "risk_coverage": risk_coverage(items),
        "confusion": confusion([(r["label"], o.label) for r, o in answered]),
        "by_kind": {k: {"n": sum(1 for r, o in answered if r["kind"] == k),
                        "correct": sum(1 for r, o in correct if r["kind"] == k)} for k in sorted({r["kind"] for r, _ in ans})},
        "wrong": [{"id": r["id"], "text": r["text"][:60], "truth": r["label"], "pred": o.label, "conf": confs.get(r["id"])}
                  for r, o in answered if o.label != r["label"]],
        "latency_p50_s": percentile(lat, 0.5), "latency_p95_s": percentile(lat, 0.95),
        # coste: llamadas reales (incluye reintentos), segundos y tokens; por 1.000 registros para comparar sistemas
        "calls": len(lat), "seconds_per_1000": round(1000 * sum(lat) / max(1, len(rows)), 1),
        "tokens_in_per_1000": round(1000 * getattr(client, "tokens_in", 0) / max(1, len(rows))),
        "tokens_out_per_1000": round(1000 * getattr(client, "tokens_out", 0) / max(1, len(rows))),
    }


def main(argv):
    models = [a for a in argv if not a.startswith("--")]
    hybrid = "--hybrid" in argv
    rows = load()
    res = {}
    for m in models:
        for split in ("test", "all"):
            sub = [r for r in rows if split == "all" or r["split"] == split]
            cli = OllamaClient(model=m, timeout=120)
            t0 = time.time()
            res[f"{m}|{split}"] = evaluate_client(cli.call, sub, cli)
            print(m, split, "plain", res[f"{m}|{split}"]["precision"], res[f"{m}|{split}"]["coverage"], f"{time.time()-t0:.0f}s", flush=True)
            if hybrid:
                cli2 = OllamaClient(model=m, timeout=120)
                h = HybridClient(cli2.call)
                res[f"{m}+rules|{split}"] = evaluate_client(h.call, sub, cli2)
                print(m, split, "hybrid", res[f"{m}+rules|{split}"]["precision"], res[f"{m}+rules|{split}"]["coverage"], flush=True)
    d = date.today().isoformat() + "-" + "-".join(m.replace(":", "_") for m in models)
    out = ROOT / "reports" / "validation"
    out.mkdir(exist_ok=True)
    (out / f"benchmark-{d}.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
    lines = [f"# Benchmark de modelos locales — {d}", "", "Conjunto v2 (74 casos sintéticos; 25 en `test`, reservados). Intervalos de Wilson 95 %.", "",
             "| Sistema | Partición | n responde | Cobertura | Precisión (IC95) | ECE | p50 s | p95 s | Rechazos |", "|---|---|---|---|---|---|---|---|---|"]
    for k, v in res.items():
        name, split = k.split("|")
        lines.append(f"| `{name}` | {split} | {v['answered']}/{v['n_answerable']} | {v['coverage']} | {v['precision']} {v['precision_ci95']} | {v['ece']} | {v['latency_p50_s']} | {v['latency_p95_s']} | {v['rejects_caught']} |")
    (out / f"benchmark-{d}.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1:])
