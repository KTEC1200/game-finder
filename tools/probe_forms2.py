"""Throwaway probe #14: what IS the search UI on jidiyouxi / catcat?

probe #13 found 0 <form> and 0 visible inputs on both. Possibilities:
  - search box is injected by JS after load (needs wait / scroll)
  - search is an icon that opens a modal/overlay
  - search lives on a separate URL/page
  - the page needs more time or a different wait strategy

Dump every input (incl. hidden), every link whose text/href mentions
search/sou, and the outerHTML of any element with a search-ish class/id.
"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = Path(r"D:\K\deepseek\_gf_form_probe2")
PROXY = "http://127.0.0.1:6234"

SITES = {
    "jidiyouxi": "https://www.jidiyouxi.com/",
    "catcat": "https://catcat.cloud/",
}


def launch(p):
    return p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE),
        channel="chrome",
        executable_path=CHROME,
        headless=True,
        timeout=60_000,
        proxy={"server": PROXY},
    )


def dump(page) -> dict:
    return page.evaluate(
        """() => {
        const inputs = Array.from(document.querySelectorAll('input,textarea,select')).map(i => ({
            tag: i.tagName.toLowerCase(),
            type: i.getAttribute('type'),
            name: i.getAttribute('name'),
            id: i.getAttribute('id'),
            placeholder: i.getAttribute('placeholder'),
            cls: (i.getAttribute('class')||'').slice(0,80),
            vis: !!(i.offsetWidth||i.offsetHeight),
        }));
        const searchish = Array.from(document.querySelectorAll('[class*=search i],[id*=search i],[class*=sou i],[id*=sou i]'))
            .slice(0,12)
            .map(e => ({
                tag: e.tagName.toLowerCase(),
                cls: (e.getAttribute('class')||'').slice(0,80),
                id: e.getAttribute('id'),
                html: e.outerHTML.slice(0, 300),
            }));
        const links = Array.from(document.querySelectorAll('a[href]'))
            .filter(a => /search|sou|find|\\?s=|\\?q=|\\?keyword/i.test(a.href + ' ' + a.textContent))
            .slice(0,12)
            .map(a => ({text: (a.textContent||'').trim().slice(0,40), href: a.href}));
        return {
            inputs, searchish, links,
            bodyLen: document.body ? document.body.innerHTML.length : 0,
            scripts: document.querySelectorAll('script').length,
        };
    }"""
    )


if __name__ == "__main__":
    results = {}
    with sync_playwright() as p:
        ctx = launch(p)
        for site_id, url in SITES.items():
            page = ctx.new_page()
            try:
                page.goto(url, timeout=45000, wait_until="load")
                page.wait_for_timeout(6000)  # let JS settle
                # also try scrolling to trigger lazy UI
                page.mouse.wheel(0, 1500)
                page.wait_for_timeout(2000)
                results[site_id] = dump(page)
            except Exception as exc:  # noqa: BLE001
                results[site_id] = {"fatal": f"{type(exc).__name__}: {str(exc)[:200]}"}
            page.close()
        ctx.close()
    dest = Path(__file__).with_name("probe_forms2.json")
    dest.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    for sid, r in results.items():
        print(f"=== {sid} ===")
        if "fatal" in r:
            print("  FATAL", r["fatal"])
            continue
        print("  bodyLen:", r["bodyLen"], "scripts:", r["scripts"])
        print("  inputs:", len(r["inputs"]))
        for i in r["inputs"][:8]:
            print("    ", i)
        print("  searchish elems:", len(r["searchish"]))
        for s in r["searchish"][:5]:
            print("    ", s["tag"], s["cls"], s["id"])
            print("       ", s["html"][:160].replace("\n", " "))
        print("  search links:", len(r["links"]))
        for l in r["links"][:6]:
            print("    ", l["text"], "->", l["href"][:110])
    print(f"[wrote {dest}]")
