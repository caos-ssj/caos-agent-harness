"""Render what the CLI prints on a real terminal as a PNG: `python3 tools/cli_shot.py <folder> <out.png> <command...>`.

Runs the command in a pty (so colour is on, exactly as in a terminal), turns the ANSI colours into HTML and
takes a screenshot of it. Needs playwright. Example:
    python3 tools/cli_shot.py /tmp/harness-demo docs/cli.png "caos-harness task list" "caos-harness status"
"""
import html
import os
import pty
import re
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
folder, out, commands = Path(sys.argv[1]), sys.argv[2], sys.argv[3:]
ANSI = re.compile(r"\x1b\[([0-9;]*)m")


CLEAN = re.compile(r"\x1b\[\?[0-9;]*[a-zA-Z]|\x1b\[[0-9;]*[A-HJKSTfn]|\x1b[=>]|\r")


def run(cmd: str) -> str:
    """`command` runs it; `command::text` also types `text` into it (use \\n for Enter), the way a person would in a session."""
    cmd, _, typed = cmd.partition("::")
    argv = [sys.executable, "-m", "caos_harness", *cmd.split()[1:]] if cmd.startswith("caos-harness") else cmd.split()
    env = {**os.environ, "PYTHONPATH": str(ROOT), "TERM": "xterm-256color", "COLUMNS": "100", "CAOS_TUI": "0"}
    env.pop("NO_COLOR", None)
    master, slave = pty.openpty()
    proc = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, cwd=folder, env=env, close_fds=True)
    os.close(slave)
    if typed:
        import time
        time.sleep(1.2)
        for ch in typed.replace("\\n", "\n"):
            os.write(master, ch.encode())
            time.sleep(0.01 if ch != "\n" else 0.6)
    chunks = b""
    while True:
        try:
            data = os.read(master, 4096)
        except OSError:
            break
        if not data:
            break
        chunks += data
    proc.wait()
    return CLEAN.sub("", chunks.decode().replace("\r\n", "\n"))


def to_html(text: str) -> str:
    out, open_span = [], False
    pos = 0
    for m in ANSI.finditer(text):
        out.append(html.escape(text[pos:m.start()]))
        pos = m.end()
        if open_span:
            out.append("</span>")
            open_span = False
        codes = m.group(1).split(";")
        if codes[0] in ("", "0"):
            continue
        style = "font-weight:700;" if codes[0] == "1" else ""
        if "38" in codes:  # 38;2;R;G;B
            r, g, bl = codes[codes.index("38") + 2:codes.index("38") + 5]
            style += f"color:rgb({r},{g},{bl});"
        out.append(f'<span style="{style}">')
        open_span = True
    out.append(html.escape(text[pos:]))
    if open_span:
        out.append("</span>")
    return "".join(out)


blocks = []
for cmd in commands:
    blocks.append(f'<div class="p"><span class="d">$</span> {html.escape(cmd.partition("::")[0])}</div><pre>{to_html(run(cmd)).rstrip()}</pre>')
page = f"""<body style="margin:0;background:#060607"><div style="width:820px;padding:22px 26px 24px;background:#060607;color:#A9A8A3;font:14px/1.55 'JetBrains Mono',ui-monospace,monospace">
<style>pre{{margin:2px 0 18px;font:inherit;white-space:pre}} .p{{color:#EDEAE5}} .d{{color:#8B8A86}}</style>{''.join(blocks)}</div></body>"""
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 872, "height": 400}, device_scale_factor=2)
    pg.set_content(page)
    pg.wait_for_timeout(300)
    h = pg.evaluate("document.body.firstElementChild.getBoundingClientRect().height")
    pg.set_viewport_size({"width": 872, "height": int(h)})
    pg.screenshot(path=out, clip={"x": 0, "y": 0, "width": 872, "height": h})
    b.close()
print("wrote", out)
