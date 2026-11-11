"""Regenerate the dashboard screenshots in docs/ from running servers (needs playwright and chromium).

    python3 tools/seed_demo.py /tmp/harness-demo --force
    (cd /tmp/harness-demo && python3 -m caos_harness serve --port 8794) &
    python3 tools/shot.py                          # sample project on :8794  ->  docs/*.png

    python3 tools/shot.py http://localhost:8794 out_dir [http://localhost:8795]
        the second URL is an empty project (`caos-harness init`), used for the first-run screen

Screenshots are taken with reduced motion on, so nothing is caught mid-animation.
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

demo = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8794").rstrip("/")
out = Path(sys.argv[2] if len(sys.argv) > 2 else Path(__file__).resolve().parent.parent / "docs")
empty = sys.argv[3].rstrip("/") if len(sys.argv) > 3 else None
out.mkdir(parents=True, exist_ok=True)

DESKTOP = {"width": 1440, "height": 900}
with sync_playwright() as p:
    b = p.chromium.launch()

    def page(viewport=DESKTOP, scale=1.5):
        return b.new_context(viewport=viewport, device_scale_factor=scale, reduced_motion="reduce").new_page()

    def shot(pg, name):
        pg.wait_for_timeout(700)
        pg.screenshot(path=str(out / name))
        print("wrote", out / name)

    pg = page(); pg.goto(f"{demo}/?tab=desk&task=6"); shot(pg, "board.png")
    pg.keyboard.press("Control+k"); pg.keyboard.type("refund"); shot(pg, "palette.png"); pg.close()

    pg = page(); pg.goto(f"{demo}/?tab=desk"); pg.click("button[aria-label=Preferences]"); pg.click("text=Compact"); pg.keyboard.press("Escape")
    pg.mouse.click(700, 500); shot(pg, "board-compact.png"); pg.close()

    pg = page({"width": 1024, "height": 768}); pg.goto(f"{demo}/?tab=desk&task=6"); shot(pg, "board-1024.png"); pg.close()
    pg = page(); pg.goto(f"{demo}/?tab=library"); shot(pg, "library.png"); pg.close()
    pg = page(); pg.goto(f"{demo}/?tab=console"); shot(pg, "console.png"); pg.close()
    pg = page({"width": 390, "height": 844}, 2); pg.goto(f"{demo}/?tab=desk&task=6"); shot(pg, "board-mobile.png"); pg.close()
    if empty:
        pg = page(); pg.goto(f"{empty}/?tab=desk"); shot(pg, "first-run.png"); pg.close()
    b.close()
