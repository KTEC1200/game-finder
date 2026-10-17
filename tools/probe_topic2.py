"""Throwaway probe #22: dump jidiyouxi topic-detail FULL html + all attrs.

Earlier probes guessed at selectors. This one saves the entire rendered DOM to
disk so the download-link shape can be grepped offline instead of re-fetching.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = Path(r"D:\K\deepseek\_gf_dl_probe")
PROXY = "http://127.0.0.1:6234"
URL = "https://www.jidiyouxi.com/topic/detail/20093940"
HERE = Path(__file__).parent


def main() -> None:
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE),
            channel="chrome",
            executable_path=CHROME,
            headless=True,
            timeout=60_000,
            proxy={"server": PROXY},
        )
        page = ctx.new_page()
        page.goto(URL, timeout=45000, wait_until="load")
        page.wait_for_timeout(8000)
        for _ in range(3):
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(1500)

        html = page.content()
        (HERE / "_topic_full.html").write_text(html, encoding="utf-8")

        # every clickable with a data-* or onclick attribute
        clicks = page.evaluate(
            """() => Array.from(document.querySelectorAll('[onclick],[data-url],[data-href],[data-link]'))
                .map(e=>({tag:e.tagName, cls:(e.className||'').toString().slice(0,60),
                          txt:(e.textContent||'').trim().slice(0,40),
                          onclick:e.getAttribute('onclick'),
                          data:JSON.stringify(e.dataset).slice(0,200)}))
                .slice(0,25)"""
        )
        # buttons, with their bounding boxes (to spot the real 下载 button)
        btns = page.evaluate(
            """() => Array.from(document.querySelectorAll('button'))
                .map(b=>({t:(b.textContent||'').trim().slice(0,30),
                          cls:(b.className||'').toString().slice(0,80),
                          vis:b.offsetParent!==null}))"""
        )
        ctx.close()

    pan = re.findall(
        r"https?://[^\s\"'<>\\]*(?:pan\.|quark|123pan|lanzou|aliyundrive|alipan|"
        r"xunlei|pikpak|baidu|115\.com|mypikpak|catbox|mediafire|mega\.nz)[^\s\"'<>\\]*",
        html,
    )
    kw = re.findall(r".{60}(?:提取码|网盘|磁力链接|下载地址|立即下载|点击下载).{60}", html)
    report = {
        "html_len": len(html),
        "pan_links": sorted(set(pan))[:20],
        "kw_context": kw[:15],
        "onclick_clicks": clicks,
        "buttons": btns,
    }
    (HERE / "probe_topic2.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("[html_len]", len(html))
    print("[pan_links]", report["pan_links"])
    print("[buttons]")
    for b in btns:
        print("   ", b["vis"], "|", b["t"], "|", b["cls"][:60])
    print("[onclick]")
    for c in clicks:
        print("   ", c["tag"], "|", c["txt"][:30], "|", (c["onclick"] or "")[:60], "|", c["data"][:120])


if __name__ == "__main__":
    main()
