"""Regenerate the dashboard screenshots in docs/ from running servers (needs playwright and chromium).

    python3 tools/seed_demo.py /tmp/harness-demo --force
    (cd /tmp/harness-demo && python3 -m caos_harness serve --port 8794) &
    python3 tools/shot.py http://127.0.0.1:8794 docs http://127.0.0.1:8795

Screenshots are taken with reduced motion on, so nothing is caught mid-animation.
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

demo = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8794").rstrip("/")
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

    pg = page(); pg.goto(f"{demo}/?view=board"); pg.wait_for_selector(".board-row-main"); pg.locator(".board-row-main").first.click(); pg.wait_for_selector(".split-detail"); shot(pg, "board.png")
    pg.keyboard.press("Control+k"); pg.wait_for_selector(".palette"); pg.keyboard.type("refund"); shot(pg, "palette.png"); pg.close()

    pg = page(); pg.goto(f"{demo}/?view=board"); pg.wait_for_selector(".board-row-main"); pg.locator(".board-row-main").first.click(); pg.wait_for_selector(".split-detail"); pg.wait_for_timeout(500)
    pg.locator(".split-detail").screenshot(path=str(out / "board-verdict.png")); print("wrote", out / "board-verdict.png"); pg.close()

    pg = page(); pg.goto(f"{demo}/?view=board"); pg.click("button[aria-label=Preferencias]"); pg.click("button:has-text('Compacta')"); pg.keyboard.press("Escape")
    pg.mouse.click(700, 120); shot(pg, "board-compact.png"); pg.close()

    pg = page(); pg.goto(f"{demo}/?view=board"); pg.click(".sb-ws-btn"); pg.wait_for_selector(".sb-ws-pop"); shot(pg, "workspaces.png"); pg.close()
    pg = page(); pg.goto(f"{demo}/?view=console"); pg.click(".engine-btn"); pg.wait_for_selector(".engine-pop"); shot(pg, "models.png"); pg.close()
    pg = page(); pg.goto(f"{demo}/?view=console"); pg.click(".orch-btn"); shot(pg, "orchestrate.png"); pg.close()

    for tab in ("console", "providers", "metrics", "skills", "share"):
        pg = page(); pg.goto(f"{demo}/?view={tab}")
        fname = "measured.png" if tab == "metrics" else f"{tab}.png"
        shot(pg, fname)
        if tab == "metrics":
            pg.wait_for_selector(".chart-card"); pg.locator(".chart-card").screenshot(path=str(out / "measured-chart.png")); print("wrote", out / "measured-chart.png")
        if tab == "providers":
            pg.wait_for_selector("section.card:has(table.prov-models)"); pg.locator("section.card:has(table.prov-models)").first.screenshot(path=str(out / "providers-models.png")); print("wrote", out / "providers-models.png")
            cloud = pg.locator('section[aria-label="Nube y free tiers"]')
            if cloud.count():
                cloud.first.scroll_into_view_if_needed()
                pg.wait_for_timeout(300)
                cloud.first.screenshot(path=str(out / "providers-accounts.png")); print("wrote", out / "providers-accounts.png")
        pg.close()

    pg = page({"width": 1024, "height": 768}); pg.goto(f"{demo}/?view=board"); shot(pg, "board-1024.png"); pg.close()
    pg = page({"width": 390, "height": 844}, 2); pg.goto(f"{demo}/?view=board"); shot(pg, "board-mobile.png"); pg.close()
    pg = page({"width": 390, "height": 844}, 2); pg.goto(f"{demo}/?view=metrics"); shot(pg, "measured-mobile.png")
    pg.wait_for_selector(".chart-card"); pg.locator(".chart-card").scroll_into_view_if_needed(); shot(pg, "measured-chart-mobile.png"); pg.close()
    if empty:
        pg = page(); pg.goto(f"{empty}/?view=board"); shot(pg, "first-run.png"); pg.close()
    b.close()
