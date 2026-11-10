"""Draws docs/agent-results.svg from reports/agent/*.json (standard library only)."""
import json, sys
from pathlib import Path
R = Path(sys.argv[1])
def frac(s): a, b = s.split("/"); return int(a), int(b)
rows = []
base = json.load(open(R/"agent-qwen2.5_7b-sin-umbral.json"))
rows.append(("Plain retrieval (no model)", frac(base["direct_retrieval_top1"]), None))
for f, name in [("agent-llama3.2_3b-sin-umbral.json","Agent · llama3.2:3b"),
                ("agent-qwen2.5_7b-sin-umbral.json","Agent · qwen2.5:7b"),
                ("agent-qwen2.5_7b-2026-11-04.json","Agent · qwen2.5:7b + relevance threshold")]:
    d = json.load(open(R/f)); rows.append((name, frac(d["answerable_correct"]), frac(d["out_of_scope_abstained"])))
W, LBL, BAR, ROW = 760, 300, 360, 46
H = 90 + ROW*len(rows) + 40
c = {"bg":"#ffffff","fg":"#1f2328","mut":"#59636e","a":"#2f6feb","b":"#8c959f","g":"#d0d7de"}
o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="Inter,Segoe UI,Helvetica,Arial,sans-serif">',
     f'<rect width="{W}" height="{H}" fill="{c["bg"]}"/>',
     f'<text x="24" y="34" font-size="18" font-weight="600" fill="{c["fg"]}">Does the agent beat plain retrieval?</text>',
     f'<text x="24" y="58" font-size="13" fill="{c["mut"]}">Correct answers on 20 answerable questions · out-of-scope abstention on 4 · local CPU models</text>']
for i,(name,(ok,n),oos) in enumerate(rows):
    y = 90 + i*ROW
    col = c["b"] if oos is None else c["a"]
    o.append(f'<text x="24" y="{y+19}" font-size="13" fill="{c["fg"]}">{name}</text>')
    o.append(f'<rect x="{LBL}" y="{y+4}" width="{BAR}" height="22" fill="{c["g"]}" rx="3"/>')
    o.append(f'<rect x="{LBL}" y="{y+4}" width="{BAR*ok/n:.1f}" height="22" fill="{col}" rx="3"/>')
    o.append(f'<text x="{LBL+BAR+10}" y="{y+20}" font-size="13" font-weight="600" fill="{c["fg"]}">{ok}/{n}</text>')
    if oos: o.append(f'<text x="{LBL}" y="{y+42}" font-size="11" fill="{c["mut"]}">abstains on out-of-scope: {oos[0]}/{oos[1]}</text>')
o.append(f'<text x="24" y="{H-14}" font-size="11" fill="{c["mut"]}">Source: reports/agent/*.json in this repository</text></svg>')
Path(sys.argv[2]).write_text("\n".join(o)); print("ok", rows)
