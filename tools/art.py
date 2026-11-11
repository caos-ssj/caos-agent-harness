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


def models():
    """Orbits: three rings, a few beads on each. The warm bead is the one the router would pick."""
    n = "models"
    beads = [(30, -40, 8), (58, 70, 11), (58, 200, 7), (86, 20, 9), (86, 135, 12), (86, 255, 7)]
    pos = [(120 + r * math.cos(math.radians(a)), 120 + r * math.sin(math.radians(a)), b) for r, a, b in beads]
    clips = {f"b{i}": f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{b}"/>' for i, (x, y, b) in enumerate(pos)}
    body = rays(120, 120, 96, 116, 96, stroke=DIM, w=0.5)
    body += outline("".join(f'<circle cx="120" cy="120" r="{r}"/>' for r in (30, 58, 86)), DIM, 0.8)
    body += "".join(hatch(f"{n}-b{i}", 45 if i % 2 else -45, 2.6) for i in range(len(pos)))
    body += outline("".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{b}"/>' for x, y, b in pos))
    x, y, b = pos[1]
    body += f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{b}" stroke="{WARM}" stroke-width="1.6"/>'
    body += outline('<circle cx="120" cy="120" r="3"/>', BRIGHT, 1)
    return plate(n, clips, body)


def workspace():
    """A cabinet of drawers: one folder per project. The warm line is the drawer in use."""
    n = "workspace"
    drawers = [(64, 54 + i * 48, 112, 42) for i in range(3)]
    clips = {f"d{i}": f'<rect x="{x}" y="{y}" width="{w}" height="{h}"/>' for i, (x, y, w, h) in enumerate(drawers)}
    body = rays(120, 126, 92, 114, 72, lambda i: 22 < i < 50, stroke=DIM, w=0.5)
    body += "".join(hatch(f"{n}-d{i}", 90 if i % 2 else 0, 4.5, DIM, 0.5) for i in range(3))
    frame = "".join(f'<rect x="{x}" y="{y}" width="{w}" height="{h}"/>' for x, y, w, h in drawers)
    handles = "".join(f'<rect x="{x + 40}" y="{y + 26}" width="32" height="6"/>' for x, y, w, h in drawers)
    labels = "".join(f'<rect x="{x + 36}" y="{y + 8}" width="40" height="12"/>' for x, y, w, h in drawers)
    body += outline(frame) + outline(handles, SILVER, 0.9) + outline(labels, SILVER, 0.8)
    body += outline('<path d="M58 54 V198 M182 54 V198 M58 198 H182"/>', SILVER, 0.8)
    x, y, w, h = drawers[1]
    body += f'<rect x="{x + 36}" y="{y + 8}" width="40" height="12" stroke="{WARM}" stroke-width="1.6"/>'
    return plate(n, clips, body)


def local():
    """A machine on a desk: the model that runs here, on this computer."""
    n = "local"
    screen = '<rect x="58" y="62" width="124" height="86" rx="4"/>'
    inner = '<rect x="68" y="72" width="104" height="66"/>'
    clips = {"s": screen, "i": inner}
    body = rays(120, 105, 84, 112, 80, lambda i: 14 < i < 66, stroke=DIM, w=0.5)
    body += hatch(f"{n}-s", 60, 3.2) + f'<g clip-path="url(#{n}-i)"><rect width="{S}" height="{S}" fill="#060607"/></g>'
    lines = "".join(f'<line x1="78" y1="{y}" x2="{x}" y2="{y}"/>' for y, x in ((88, 140), (100, 154), (112, 128), (124, 146)))
    body += f'<g stroke="{SILVER}" stroke-width="0.9">{lines}</g>'
    body += outline(screen + inner + '<path d="M104 148 V166 M136 148 V166 M84 172 H156"/>')
    body += f'<line x1="78" y1="112" x2="128" y2="112" stroke="{WARM}" stroke-width="1.6"/>'
    return plate(n, clips, body)


def cloud():
    """A cloud drawn in contour lines: a provider that lives somewhere else. The key line is the key in the environment."""
    n = "cloud"
    cl = '<path d="M72 150 a28 28 0 0 1 6 -55 a40 40 0 0 1 76 -8 a30 30 0 0 1 14 63 z"/>'
    clips = {"c": cl}
    body = rays(120, 118, 84, 112, 72, lambda i: 30 < i < 44, stroke=DIM, w=0.5)
    body += hatch(f"{n}-c", 0, 4.2, DIM, 0.55) + hatch(f"{n}-c", 90, 12, DIM, 0.4)
    body += outline(cl) + outline('<path d="M104 176 H136 M112 188 H128"/>', SILVER, 0.8)
    body += f'<path d="M112 150 V172 M128 150 V172 M112 172 H128" stroke="{WARM}" stroke-width="1.6" fill="none"/>'
    return plate(n, clips, body)


def empty():
    """An empty tray: nothing is waiting here."""
    n = "empty"
    tray = '<path d="M46 132 H194 L178 176 H62 z"/>'
    clips = {"t": tray}
    body = rays(120, 120, 84, 112, 80, lambda i: i % 2, stroke=DIM, w=0.5)
    body += hatch(f"{n}-t", 70, 3.4)
    body += outline(tray + '<path d="M46 132 L62 96 H178 L194 132"/><path d="M96 112 H144" stroke-dasharray="2 4"/>')
    body += f'<path d="M58 132 H182" stroke="{WARM}" stroke-width="1.5"/>'
    return plate(n, clips, body)


def hourglass():
    """Waiting for a run: sand falling through the neck."""
    n = "hourglass"
    top = '<path d="M86 52 H154 L124 112 H116 z"/>'
    bot = '<path d="M116 128 H124 L154 188 H86 z"/>'
    clips = {"t": top, "b": bot}
    body = rays(120, 120, 78, 110, 80, lambda i: i % 3 == 0, stroke=DIM, w=0.5)
    body += hatch(f"{n}-t", 0, 8, DIM, 0.6) + hatch(f"{n}-b", 0, 3.2)
    body += outline(top + bot + '<path d="M78 52 H162 M78 188 H162"/>')
    body += f'<path d="M120 112 V128" stroke="{WARM}" stroke-width="1.6"/>'
    return plate(n, clips, body)


def cover():
    """The panel's cover plate, wide: lanes on the left, the mark in the middle, a trace climbing on the right."""
    W, H = 720, 240
    n = "cover"
    cx, cy = 360, 124
    defs, body = [], ""
    # the burst
    body += "".join(f'<line x1="{cx + 70 * math.cos(2 * math.pi * i / 180):.1f}" y1="{cy + 70 * math.sin(2 * math.pi * i / 180):.1f}" x2="{cx + (118 + (i % 7) * 4) * math.cos(2 * math.pi * i / 180):.1f}" y2="{cy + (118 + (i % 7) * 4) * math.sin(2 * math.pi * i / 180):.1f}"/>' for i in range(180) if i % 15)
    body = f'<g stroke="{SILVER}" stroke-width="0.45">{body}</g>'
    body += f'<g stroke="{DIM}" stroke-width="0.5">' + "".join(f'<line x1="{cx + 52 * math.cos(2 * math.pi * i / 72):.1f}" y1="{cy + 52 * math.sin(2 * math.pi * i / 72):.1f}" x2="{cx + 66 * math.cos(2 * math.pi * i / 72):.1f}" y2="{cy + 66 * math.sin(2 * math.pi * i / 72):.1f}"/>' for i in range(72)) + "</g>"
    body += f'<g stroke="{SILVER}" stroke-width="0.8"><circle cx="{cx}" cy="{cy}" r="70" fill="none"/></g><g stroke="{BRIGHT}" stroke-width="1.1"><circle cx="{cx}" cy="{cy}" r="50" fill="none"/></g>'
    body += f'<path d="M{cx} 0 V26" stroke="{WARM}" stroke-width="1.4"/>'
    # lanes on the left
    lanes = [(40, 78, 44, 110), (96, 58, 44, 130), (152, 92, 44, 96)]
    for i, (x, y, w, h) in enumerate(lanes):
        defs.append(f'<clipPath id="{n}-l{i}"><rect x="{x}" y="{y}" width="{w}" height="{h}"/></clipPath>')
        body += f'<g clip-path="url(#{n}-l{i})" stroke="{DIM}" stroke-width="0.5">' + "".join(f'<line x1="{x + k * 5}" y1="{y}" x2="{x + k * 5}" y2="{y + h}"/>' for k in range(int(w / 5) + 1)) + "</g>"
        for j in range(int(h // 34)):
            ty = y + 8 + j * 34
            body += f'<rect x="{x + 6}" y="{ty}" width="{w - 12}" height="24" fill="none" stroke="{BRIGHT}" stroke-width="1.1"/>'
        body += f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="none" stroke="{SILVER}" stroke-width="0.8"/>'
    body += f'<rect x="102" y="66" width="32" height="24" fill="none" stroke="{WARM}" stroke-width="1.4"/>'
    # trace on the right
    beads = [(540, 176, 8), (586, 134, 11), (628, 154, 7), (664, 96, 12), (700, 70, 7)]
    body += f'<g stroke="{DIM}" stroke-width="0.4">' + "".join(f'<line x1="520" y1="{y}" x2="716" y2="{y}"/>' for y in range(60, 206, 12)) + "</g>"
    body += f'<path d="M{" L".join(f"{x} {y}" for x, y, _ in beads)}" fill="none" stroke="{BRIGHT}" stroke-width="1.1"/>'
    body += "".join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="#060607" stroke="{BRIGHT}" stroke-width="1.1"/>' for x, y, r in beads)
    body += f'<circle cx="664" cy="96" r="12" fill="none" stroke="{WARM}" stroke-width="1.6"/>'
    body += f'<line x1="24" y1="218" x2="696" y2="218" stroke="{DIM}" stroke-width="0.6"/>'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" fill="none" stroke-linecap="round" role="img" aria-label="caos-agent-harness"><defs>{"".join(defs)}</defs>{body}</svg>')


EMBLEMS = {"mark": mark, "board": board, "router": router, "policy": policy, "memory": memory, "review": review, "traces": traces, "person": person, "models": models, "workspace": workspace,
           "local": local, "cloud": cloud, "empty": empty, "hourglass": hourglass, "cover": cover}

if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "web/public/art")
    out.mkdir(parents=True, exist_ok=True)
    for name, fn in EMBLEMS.items():
        (out / f"{name}.svg").write_text(fn(), encoding="utf-8")
    print("drew", ", ".join(EMBLEMS), "->", out)
