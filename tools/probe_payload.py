"""Throwaway probe #25: does jidiyouxi's SSR payload hold THIS game's links?

probe #24 proved the pan links are NOT in visible DOM: they live in a 7584-char
JSON-LD blob (related 修改器 posts) and a 538456-char inline script. Need to know
whether the CURRENT game's own download URLs are in that payload, and under what
key — that decides whether detail extraction is DOM-only or payload-based.
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

        scripts = page.evaluate(
            """() => Array.from(document.querySelectorAll('script'))
                .map((s,i)=>({i, type:s.type||'', id:s.id||'', len:(s.textContent||'').length}))
                .filter(x=>x.len>1000)"""
        )
        out["scripts"] = scripts

        # the big one
        big = page.evaluate(
            """() => {
                let best=null,bl=0;
                for (const s of document.querySelectorAll('script')) {
                    const t=s.textContent||'';
                    if (t.length>bl && t.length<2_000_000) {bl=t.length;best=t;}
                }
                return {len:bl, head:best.slice(0,400)};
            }"""
        )
        out["big_script_head"] = big

        # JSON keys that look download-ish anywhere in any script
        keys = page.evaluate(
            """() => {
                const found = new Set();
                for (const s of document.querySelectorAll('script')) {
                    const t = s.textContent||'';
                    for (const m of t.matchAll(/"(\\w*(?:down|link|url|pan|netdisk|share|href|resource)\\w*)"\\s*:/gi)) {
                        found.add(m[1]);
                    }
                }
                return Array.from(found).slice(0,60);
            }"""
        )
        out["downloadish_keys"] = keys

        # does the payload mention THIS topic id next to a url?
        ctx_js = page.evaluate(
            """() => {
                const res=[];
                for (const s of document.querySelectorAll('script')) {
                    const t=s.textContent||'';
                    if (!t.includes('20093940')) continue;
                    let i=-1;
                    while ((i = t.indexOf('20093940', i+1)) !== -1 && res.length<6) {
                        res.push(t.slice(Math.max(0,i-300), i+300));
                    }
                }
                return res;
            }"""
        )
        out["topic_id_context"] = ctx_js

        # is there a "download" API endpoint referenced?
        out["api_endpoints"] = page.evaluate(
            """() => {
                const s = new Set();
                for (const sc of document.querySelectorAll('script')) {
                    for (const m of (sc.textContent||'').matchAll(/["'`](\\/api\\/[\\w\\/\\-{}.]+)["'`]/g)) s.add(m[1]);
                }
                return Array.from(s).slice(0,40);
            }"""
        )
        ctx.close()
    (HERE / "probe_payload.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("scripts:", json.dumps(scripts, ensure_ascii=False))
    print("downloadish_keys:", keys)
    print("api_endpoints:", out["api_endpoints"])
    print("topic_id_context count:", len(ctx_js))
    for c in ctx_js[:3]:
        print("---", c[:400].replace("\n", " "))


if __name__ == "__main__":
    main()
