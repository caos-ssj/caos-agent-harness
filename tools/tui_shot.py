"""Photograph the full-screen interface without a terminal: `python3 tools/tui_shot.py <folder> <out.png> [keys] [--w 124 --h 34] [--board] [--skin night]`.

It composes the screen exactly as the curses drawer would (`caos_harness.tui`), after pressing the given keys, and draws
the rows as styled text. The default is the conversation screen: `"/agent summarizer\nSummarise ...\n"` types a command and a
prompt (`\\n` is Enter, `\\x10` is Ctrl-P) and waits for the real agent to answer. `--board` shows the board view's keys
instead (`"jj"` moves down twice). Needs playwright.
"""
import html
import os
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from caos_harness import app, tui  # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith("--")]
folder, out = Path(args[0]), args[1]
keys = args[2] if len(args) > 2 else ""
opt = lambda k, d: int(sys.argv[sys.argv.index(k) + 1]) if k in sys.argv else d
w, h = opt("--w", 124), opt("--h", 34)

os.environ["CAOS_HARNESS_HOME"] = tempfile.mkdtemp()   # photographing must not change anyone's settings
p = app.load(folder / "harness.toml")
skin = sys.argv[sys.argv.index("--skin") + 1] if "--skin" in sys.argv else "night"
if "--board" in sys.argv:
    st = tui.State(p)
    for k in keys:
        st.key(k)
    rows, cursor = tui.compose(st, w, h)
else:
    import time
    ui = tui.ChatUI(p, models=["qwen2.5:7b", "llama3.2:3b", "gemma4:e2b-it-q4_K_M"])
    ui.skin = skin
    ui.session_id = "20261111-104500"
    keys = keys.replace("\\n", "\n").replace("\\x10", "\x10")
    for k in keys:
        ui.key({"\n": "enter", "\x10": "ctrl-p"}.get(k, k))
        end = time.time() + 8
        while ui.conv.busy() and time.time() < end:
            time.sleep(0.05)
    rows, cursor = ui.compose(w, h, 3)
SK = tui.SKINS.get(skin)
bone, dim, amber = (SK["bone"][1], SK["dim"][1], SK["amber"][1]) if SK else ("#EDEAE5", "#8D8C88", "#EDEAE5")
STYLE = {"": f"color:{bone}", "bone": f"color:{bone};font-weight:700", "bold": f"color:{bone};font-weight:700", "dim": f"color:{dim}", "amber": f"color:{amber}" + ("" if SK else ";text-decoration:underline"), "amberb": f"color:{amber};font-weight:700", "rev": f"background:{bone};color:#060607"}
lines = "\n".join("".join(f'<span style="{STYLE.get(s, "")}">{html.escape(t)}</span>' for t, s in r) for r in rows)
page = f'<body style="margin:0;background:#060607"><pre style="margin:0;padding:16px 18px;font:14px/1.35 \'JetBrains Mono\',ui-monospace,monospace;color:#EDEAE5;width:{w}ch">{lines}</pre></body>'
with sync_playwright() as pw:
    b = pw.chromium.launch()
    pg = b.new_page(viewport={"width": 1200, "height": 300}, device_scale_factor=2)
    pg.set_content(page)
    pg.wait_for_timeout(300)
    box = pg.evaluate("(() => { const r = document.querySelector('pre').getBoundingClientRect(); return [r.width, r.height]; })()")
    pg.set_viewport_size({"width": int(box[0]), "height": int(box[1])})
    pg.screenshot(path=out, clip={"x": 0, "y": 0, "width": box[0], "height": box[1]})
    b.close()
print("wrote", out)
