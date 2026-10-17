"""Throwaway probe #24: are jidiyouxi pan links in VISIBLE DOM or only JSON-LD?

probe #23 showed pan links sitting in escaped-JSON text (\\n) — likely a
<script type="application/ld+json"> blob, which the earlier "external anchors"
query would legitimately miss. Decide where the extractor must read from.
"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = Path(r"D:\K\deepseek\_gf_dl_probe")
PROXY = "http://127.0.0.1:6234"
URL = "https://www.jidiyouxi.com/topic/detail/20093940"
HERE = Path(__file__).parent


def main() -> None:
    out: dict = {}
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
        for _ in range(4):
            page.mouse.wheel(0, 5000)
            page.wait_for_timeout(1200)

        out["visible_text_has_pan"] = page.evaluate(
            "() => /pan\\.(baidu|xunlei|quark)/.test(document.body.innerText)"
        )
        out["innertext_len"] = page.evaluate("() => document.body.innerText.length")
        out["innertext"] = page.evaluate("() => document.body.innerText")
        out["anchor_count"] = page.evaluate(
            "() => document.querySelectorAll('a[href]').length"
        )
        out["pan_in_anchors"] = page.evaluate(
            """() => Array.from(document.querySelectorAll('a[href]'))
                .map(a=>a.href).filter(h=>/pan\\.|magnet:|quark|123pan|lanzou/.test(h))"""
        )
        # count scripts and find which one holds the pan links
        out["script_info"] = page.evaluate(
            """() => Array.from(document.querySelectorAll('script'))
                .map((s,i)=>({i, type:s.type||'', len:(s.textContent||'').length,
                              has_pan:/pan\\.baidu/.test(s.textContent||'')}))
                .filter(x=>x.has_pan || x.len>2000).slice(0,15)"""
        )
        # the JSON-LD blob specifically
        out["ldjson_pan"] = page.evaluate(
            """() => {
                const els = document.querySelectorAll('script[type="application/ld+json"]');
                let hits = [];
                els.forEach((s,i)=>{
                    const t = s.textContent||'';
                    if (/pan\\.baidu/.test(t)) hits.push({i, len:t.length, head:t.slice(0,120)});
                });
                return hits;
            }"""
        )
        # the rendered article body element (the one with the game intro)
        out["content_candidates"] = page.evaluate(
            """() => Array.from(document.querySelectorAll('div,article,section'))
                .filter(e => /游戏介绍|下载链接|使用方法|配置要求/.test(e.innerText||''))
                .map(e=>({cls:(e.className||'').toString().slice(0,80),
                          len:(e.innerText||'').length,
                          has_pan:/pan\\./.test(e.innerHTML||''),
                          sample:(e.innerText||'').slice(0,300)}))
                .slice(0,6)"""
        )
        ctx.close()
    (HERE / "probe_visible.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("visible_text_has_pan:", out["visible_text_has_pan"])
    print("innertext_len:", out["innertext_len"])
    print("anchor_count:", out["anchor_count"])
    print("pan_in_anchors:", out["pan_in_anchors"])
    print("ldjson_pan:", out["ldjson_pan"])
    print("scripts:", json.dumps(out["script_info"], ensure_ascii=False))
    print("content_candidates:")
    for c in out["content_candidates"]:
        print("   cls=", c["cls"][:60], "len=", c["len"], "has_pan=", c["has_pan"])
        print("      ", c["sample"][:200].replace("\n", " | "))


if __name__ == "__main__":
    main()
