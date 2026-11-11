"""Regenerate docs/board.png from a running demo server: `python3 tools/shot.py [url] [out]` (needs playwright)."""
import sys
from playwright.sync_api import sync_playwright

url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8794/?tab=board&task=6"
out = sys.argv[2] if len(sys.argv) > 2 else "docs/board.png"
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5)
    pg.goto(url)
    pg.wait_for_timeout(1500)
    pg.screenshot(path=out)
    b.close()
