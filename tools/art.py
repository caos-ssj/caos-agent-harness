"""Draws the harness emblems as SVG engravings: every form is built from hairlines, shading is line density.

    python tools/art.py web/public/art        # one <name>.svg per emblem

One emblem per part of the harness. They are generated, so the set stays consistent and anyone can redraw it;
replace a file with a hand-made one of the same name and viewBox (240 x 240) to use your own.
Palette from the CAOS brand note: silver hairlines on black, one warm line per emblem.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

S = 240
SILVER, BRIGHT, DIM, WARM = "#91908D", "#E7E3DE", "#4E4C4A", "#C9975C"


def rays(cx, cy, r0, r1, n, skip=lambda i: False, stroke=DIM, w=0.5):
    out = []
    for i in range(n):
        if skip(i):
            continue
        a = 2 * math.pi * i / n
        out.append(f'<line x1="{cx + r0 * math.cos(a):.1f}" y1="{cy + r0 * math.sin(a):.1f}" x2="{cx + r1 * math.cos(a):.1f}" y2="{cy + r1 * math.sin(a):.1f}"/>')
    return f'<g stroke="{stroke}" stroke-width="{w}">{"".join(out)}</g>'


def hatch(cid, angle, gap, stroke=SILVER, w=0.7):
    """Parallel hairlines across the whole plate, shown only inside clip `cid`."""
    a = math.radians(angle)
    dx, dy = math.cos(a), math.sin(a)
    out, n = [], int(S * 1.5 / gap)
    for i in range(-n, n + 1):
        ox, oy = S / 2 - dy * i * gap, S / 2 + dx * i * gap
        out.append(f'<line x1="{ox - dx * S:.1f}" y1="{oy - dy * S:.1f}" x2="{ox + dx * S:.1f}" y2="{oy + dy * S:.1f}"/>')
    return f'<g clip-path="url(#{cid})" stroke="{stroke}" stroke-width="{w}">{"".join(out)}</g>'


def plate(name, clips, body):
    defs = "".join(f'<clipPath id="{name}-{k}">{v}</clipPath>' for k, v in clips.items())
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} {S}" fill="none" stroke-linecap="round" role="img" aria-label="{name}">'
            f"<defs>{defs}</defs>{body}</svg>")


def outline(d, stroke=BRIGHT, w=1.1):
    return f'<g stroke="{stroke}" stroke-width="{w}">{d}</g>'


def board():
    n = "board"
    lanes = [(46, 60, 40, 132), (100, 44, 40, 148), (154, 76, 40, 116)]
    clips, body = {}, rays(120, 120, 96, 118, 96)
    tiles = ""
    for i, (x, y, w, h) in enumerate(lanes):
        clips[f"l{i}"] = f'<rect x="{x}" y="{y}" width="{w}" height="{h}"/>'
        body += hatch(f"{n}-l{i}", 90, 5, DIM, 0.5)
        for j in range(int(h // 34)):
            ty = y + 8 + j * 34
            clips[f"t{i}{j}"] = f'<rect x="{x + 5}" y="{ty}" width="{w - 10}" height="24"/>'
            body += hatch(f"{n}-t{i}{j}", 35 if (i + j) % 2 else -35, 3.2)
            tiles += f'<rect x="{x + 5}" y="{ty}" width="{w - 10}" height="24"/>'
    body += outline(tiles) + outline("".join(f'<rect x="{x}" y="{y}" width="{w}" height="{h}"/>' for x, y, w, h in lanes), SILVER, 0.8)
    body += f'<rect x="105" y="52" width="30" height="24" stroke="{WARM}" stroke-width="1.4"/>'
    return plate(n, clips, body)


def router():
    n = "router"
    clips = {"l": '<path d="M38 128 a34 34 0 0 0 68 0 z"/>', "r": '<path d="M134 150 a34 34 0 0 0 68 0 z"/>', "p": '<rect x="116" y="52" width="8" height="140"/>',
             "b": '<path d="M84 200 h72 l-10 -12 h-52 z"/>'}
    body = rays(120, 62, 14, 44, 48, lambda i: 6 < i < 18)
    body += hatch(f"{n}-l", 0, 3) + hatch(f"{n}-r", 0, 3) + hatch(f"{n}-p", 90, 2.2, DIM) + hatch(f"{n}-b", 45, 3)
    body += outline('<path d="M38 128 a34 34 0 0 0 68 0 z"/><path d="M134 150 a34 34 0 0 0 68 0 z"/><path d="M84 200 h72 l-10 -12 h-52 z"/>'
                    '<path d="M72 78 L168 100"/><path d="M72 78 L44 128 M72 78 L100 128"/><path d="M168 100 L140 150 M168 100 L196 150"/><circle cx="120" cy="62" r="7"/>')
    body += f'<path d="M72 78 L168 100" stroke="{WARM}" stroke-width="1.6"/>'
    return plate(n, clips, body)


def policy():
    n = "policy"
    arch = '<path d="M62 204 V112 a58 58 0 0 1 116 0 V204 z"/>'
    inner = '<path d="M82 204 V114 a38 38 0 0 1 76 0 V204 z"/>'
    clips = {"a": arch, "i": inner}
    body = rays(120, 112, 66, 104, 72, lambda i: 2 < i < 34)
    body += hatch(f"{n}-a", 62, 3.4) + f'<g clip-path="url(#{n}-i)"><rect width="{S}" height="{S}" fill="#060607"/></g>'
    bars = "".join(f'<line x1="{x}" y1="78" x2="{x}" y2="204"/>' for x in range(90, 156, 11)) + "".join(f'<line x1="82" y1="{y}" x2="158" y2="{y}"/>' for y in range(124, 204, 16))
    body += f'<g clip-path="url(#{n}-i)" stroke="{SILVER}" stroke-width="0.9">{bars}</g>'
    body += outline(arch + inner) + f'<line x1="82" y1="172" x2="158" y2="172" stroke="{WARM}" stroke-width="1.6"/>'
    return plate(n, clips, body)


def memory():
    n = "memory"
    left = '<path d="M120 76 C96 60 62 60 40 70 V178 C62 168 96 168 120 184 z"/>'
    right = '<path d="M120 76 C144 60 178 60 200 70 V178 C178 168 144 168 120 184 z"/>'
    clips = {"l": left, "r": right}
    body = rays(120, 76, 30, 62, 60, lambda i: i < 31 or i > 59)
    body += hatch(f"{n}-l", 8, 6.5) + hatch(f"{n}-r", -8, 6.5) + hatch(f"{n}-l", 78, 9, DIM, 0.5)
    body += outline(left + right + '<path d="M120 76 V184"/><path d="M34 80 V190 C60 180 96 180 120 196 C144 180 180 180 206 190 V80"/>')
    body += f'<path d="M140 104 C156 96 176 96 190 100" stroke="{WARM}" stroke-width="1.6"/>'
    return plate(n, clips, body)


def review():
    n = "review"
    pts = lambda r, k, off=0: " ".join(f"{120 + r * (1 + 0.07 * math.cos(k * a)) * math.cos(a + off):.1f},{120 + r * (1 + 0.07 * math.cos(k * a)) * math.sin(a + off):.1f}" for a in [2 * math.pi * i / 180 for i in range(180)])
    seal = f'<polygon points="{pts(74, 11)}"/>'
    clips = {"s": seal, "c": '<circle cx="120" cy="120" r="46"/>'}
    body = rays(120, 120, 86, 112, 120)
    body += hatch(f"{n}-s", 45, 3) + f'<circle cx="120" cy="120" r="46" fill="#060607"/>' + hatch(f"{n}-c", -45, 7, DIM, 0.5)
    body += outline(seal + '<circle cx="120" cy="120" r="46"/><circle cx="120" cy="120" r="52" stroke-dasharray="1 5"/>')
    body += f'<path d="M96 122 L113 139 L146 102" stroke="{WARM}" stroke-width="2.2" stroke-linejoin="round"/>'
    return plate(n, clips, body)


def traces():
    n = "traces"
    beads = [(44, 168, 9), (84, 120, 12), (124, 142, 8), (160, 86, 13), (198, 64, 8)]
    clips = {f"b{i}": f'<circle cx="{x}" cy="{y}" r="{r}"/>' for i, (x, y, r) in enumerate(beads)}
    body = "".join(rays(x, y, r + 5, r + 16, 28, stroke=DIM) for x, y, r in beads[1::2])
    grid = "".join(f'<line x1="28" y1="{y}" x2="212" y2="{y}"/>' for y in range(52, 200, 12))
    body += f'<g stroke="{DIM}" stroke-width="0.4">{grid}</g>'
    body += "".join(hatch(f"{n}-b{i}", 45 if i % 2 else -45, 2.6) for i in range(len(beads)))
    path = "M" + " L".join(f"{x} {y}" for x, y, _ in beads)
    body += outline(f'<path d="{path}"/>' + "".join(f'<circle cx="{x}" cy="{y}" r="{r}"/>' for x, y, r in beads))
    body += f'<circle cx="160" cy="86" r="13" stroke="{WARM}" stroke-width="1.6"/>'
    return plate(n, clips, body)


def person():
    n = "person"
    body_p = '<path d="M92 92 h56 l12 84 h-80 z"/>'
    clips = {"g": body_p, "t": '<path d="M100 92 a20 20 0 0 1 40 0 z"/>', "f": '<path d="M112 150 q8 -34 8 -34 q8 34 8 34 a8 8 0 0 1 -16 0 z"/>'}
    body = rays(120, 134, 50, 112, 90, lambda i: i % 3 == 0)
    body += hatch(f"{n}-g", 90, 7, DIM, 0.5) + hatch(f"{n}-t", 0, 3) + hatch(f"{n}-f", 60, 2.2, WARM, 0.9)
    body += outline(body_p + '<path d="M100 92 a20 20 0 0 1 40 0"/><path d="M120 72 V54 M108 54 h24"/><path d="M74 176 h92 M84 188 h72"/>')
    body += f'<path d="M112 150 q8 -34 8 -34 q8 34 8 34 a8 8 0 0 1 -16 0 z" stroke="{WARM}" stroke-width="1.3"/>'
    return plate(n, clips, body)


def mark():
    """The house emblem: a burst of hairlines around an empty disc. The wordmark is set over it in the brand's blackletter."""
    n = "mark"
    body = rays(120, 120, 58, 116, 180, lambda i: i % 15 == 0, SILVER, 0.45) + rays(120, 120, 44, 56, 60, stroke=DIM)
    body += outline('<circle cx="120" cy="120" r="58"/>', SILVER, 0.8) + outline('<circle cx="120" cy="120" r="40"/>')
    body += f'<path d="M120 4 V30" stroke="{WARM}" stroke-width="1.4"/>'
    return plate(n, {}, body)


EMBLEMS = {"mark": mark, "board": board, "router": router, "policy": policy, "memory": memory, "review": review, "traces": traces, "person": person}

if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "web/public/art")
    out.mkdir(parents=True, exist_ok=True)
    for name, fn in EMBLEMS.items():
        (out / f"{name}.svg").write_text(fn(), encoding="utf-8")
    print("drew", ", ".join(EMBLEMS), "->", out)
