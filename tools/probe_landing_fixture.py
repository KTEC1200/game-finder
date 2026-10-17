"""Fixture capture: save gamer520's /go landing page HTML for offline tests.

The two-step download flow (detail -> /go?post_id= -> 520.gamers520.com/{id}.html)
is the most complex extractor path. Save the landing page so detail.py can be
tested offline against it.
"""

from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = Path(r"D:\K\deepseek\_gf_e2e_probe")
PROXY = "http://127.0.0.1:6234"
HERE = Path(__file__).parent
OUT = HERE.parent / "tests" / "fixtures" / "gamer520"

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE), channel="chrome", executable_path=CHROME,
        headless=True, timeout=60_000, proxy={"server": PROXY},
    )
    page = ctx.new_page()
    page.goto("https://www.gamer520.com/go?post_id=123857", timeout=45000,
              wait_until="load")
    page.wait_for_timeout(7000)
    html = page.content()
    (OUT / "go_landing_sample.html").write_text(html, encoding="utf-8")
    print("saved go_landing_sample.html len=", len(html), "url=", page.url[:80])
    ctx.close()
