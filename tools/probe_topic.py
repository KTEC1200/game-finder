"""Throwaway probe #21: jidiyouxi topic-detail content structure.

probe #19/#20 were misled: `a:has-text('下载')` matched a COMMENT whose text
was "下载就一百多兆". So the real download link is still unlocated.

Method: dump the main content container's HTML (not just innerText), find every
occurrence of 下载 / 网盘 / 磁力 / 提取码 with surrounding context, and list
iframes. Also report whether a login wall is present.
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
        page.goto(URL, timeout=45000, wait_until="load")
        page.wait_for_timeout(8000)
        page.mouse.wheel(0, 3000)
        page.wait_for_timeout(3000)

        out["title"] = page.title()
        out["iframes"] = page.evaluate(
            "() => Array.from(document.querySelectorAll('iframe')).map(f=>f.src)"
        )
        out["login_wall"] = page.evaluate(
            """() => /登录|注册|请先登录/.test(document.body.innerText.slice(0,400))"""
        )
        # every element whose own text mentions a download-ish keyword
        out["kw_elements"] = page.evaluate(
            """() => {
                const kw = /下载|网盘|磁力|提取码|百度|夸克|蓝奏|阿里云盘|迅雷|123云盘|pikpak/i;
                const res = [];
                for (const el of document.querySelectorAll('*')) {
                    const own = Array.from(el.childNodes)
                        .filter(n=>n.nodeType===3).map(n=>n.textContent).join('').trim();
                    if (own && kw.test(own) && own.length < 80) {
                        res.push({tag: el.tagName, cls: el.className||'',
                                  txt: own, href: el.href||el.getAttribute('href')||null});
                    }
                }
                return res.slice(0, 30);
            }"""
        )
        # the richest text container = the article body
        out["main_container"] = page.evaluate(
            """() => {
                let best = null, bestLen = 0;
                for (const el of document.querySelectorAll('div,article,section')) {
                    const t = (el.innerText||'');
                    const links = el.querySelectorAll('a[href]').length;
                    if (t.length > bestLen && t.length < 20000) { bestLen = t.length; best = el; }
                }
                if (!best) return null;
                return {cls: best.className||'', tag: best.tagName,
                        len: bestLen, html: best.innerHTML.slice(0, 6000)};
            }"""
        )
        ctx.close()
    dest = Path(__file__).with_name("probe_topic.json")
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[wrote {dest}]")
    print("TITLE:", out["title"])
    print("IFRAMES:", out["iframes"])
    print("LOGIN_WALL:", out["login_wall"])
    print("KW_ELEMENTS:")
    for e in out["kw_elements"]:
        print("   ", e["tag"], "|", e["cls"][:40], "|", e["txt"][:50], "|", e["href"])
    mc = out["main_container"]
    if mc:
        print("MAIN:", mc["tag"], mc["cls"][:60], "len=", mc["len"])


if __name__ == "__main__":
    main()
