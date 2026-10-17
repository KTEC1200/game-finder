"""Throwaway probe #19: locate the download link on a jidiyouxi detail page.

probe #18 found 0 external anchors on /topic/detail/20093940 and no
pan/magnet links, yet the page is a download site. So the download link is
either behind a click, lazily rendered, or fetched from an API.

Method: dump every button's text, click the download-ish ones, and watch
network + DOM for pan/magnet/xunlei/quark URLs.
"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = Path(r"D:\K\deepseek\_gf_dl_probe")
PROXY = "http://127.0.0.1:6234"
URL = "https://www.jidiyouxi.com/topic/detail/20093940"


def main() -> None:
    out: dict = {"url": URL}
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
        seen: list[str] = []
        page.on("request", lambda r: seen.append(r.url))
        page.goto(URL, timeout=45000, wait_until="load")
        page.wait_for_timeout(6000)

        # 1. every button / clickable text
        out["buttons"] = page.evaluate(
            """() => Array.from(document.querySelectorAll('button,a,[role=button]'))
                .map(e=>({t:(e.textContent||'').trim().slice(0,24), tag:e.tagName,
                          href:e.href||null}))
                .filter(x=>x.t).slice(0,40)"""
        )

        # 2. scroll to bottom to trigger lazy render
        page.mouse.wheel(0, 20000)
        page.wait_for_timeout(4000)
        out["after_scroll_anchors"] = page.evaluate(
            """() => Array.from(document.querySelectorAll('a[href]'))
                .map(a=>a.href)
                .filter(h=>/^https?:/.test(h) && !/jidiyouxi\\.com/.test(h)).slice(0,20)"""
        )
        out["after_scroll_pan"] = page.evaluate(
            """() => Array.from(document.querySelectorAll('*'))
                .map(e=>e.textContent||'')
                .filter(t=>/pan\\.|magnet:|quark|baidu|123pan|lanzou|xunlei|aliyun|提取码/i.test(t) && t.length<200)
                .slice(0,8)"""
        )

        # 3. click the first download-ish button and see what happens
        clicked = None
        for label in ("下载", "网盘", "立即下载", "获取"):
            loc = page.locator(f"button:has-text('{label}'), a:has-text('{label}')")
            if loc.count():
                try:
                    loc.first.click(timeout=4000)
                    clicked = label
                    page.wait_for_timeout(5000)
                    break
                except Exception:  # noqa: BLE001
                    continue
        out["clicked"] = clicked
        if clicked:
            out["post_click_url"] = page.url
            out["post_click_pages"] = len(ctx.pages)
            if len(ctx.pages) > 1:
                out["new_tab_url"] = ctx.pages[-1].url
            out["post_click_pan"] = page.evaluate(
                """() => Array.from(document.querySelectorAll('a[href]'))
                    .map(a=>({t:(a.textContent||'').trim().slice(0,20),h:a.href}))
                    .filter(x=>/pan\\.|magnet:|quark|baidu|123pan|lanzou|xunlei|aliyun|pikpak/i.test(x.h))
                    .slice(0,15)"""
            )
        out["network_pan"] = [
            u for u in seen
            if any(k in u for k in ("pan.", "quark", "baidu", "123pan", "lanzou", "xunlei", "aliyun", "pikpak"))
        ][:15]
        ctx.close()
    dest = Path(__file__).with_name("probe_download.json")
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[wrote {dest}]")


if __name__ == "__main__":
    main()
