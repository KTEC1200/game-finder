"""Throwaway probe #16: nail selectors + capture fixtures for the plan.

Known so far:
  gamer520  : ?s=AI -> 68 links, detail like /124105.html   (URL mode)
  jidiyouxi : form search -> /search/detail/AI              (URL pattern!)
  catcat    : Alist netdisk (/api/fs/list, /api/fs/get), Ctrl+K palette

Goal: concrete, verified selectors + one real detail page per site so the
plan's adapter tasks are grounded in evidence, not guesses.

Also captures HTML fixtures into tests/fixtures/<site_id>/.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = Path(r"D:\K\deepseek\_gf_sel_probe")
PROXY = "http://127.0.0.1:6234"
QUERY = "AI"
FIX = Path(r"C:\Users\27025\Desktop\game-finder\tests\fixtures")


def launch(p):
    return p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE),
        channel="chrome",
        executable_path=CHROME,
        headless=True,
        timeout=60_000,
        proxy={"server": PROXY},
    )


def save_fixture(site: str, name: str, html: str) -> str:
    d = FIX / site
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(html, encoding="utf-8")
    return str(p)


def probe_jidiyouxi_url(ctx) -> dict:
    """Does the URL pattern /search/detail/{q} work directly?"""
    out: dict = {}
    page = ctx.new_page()
    url = f"https://www.jidiyouxi.com/search/detail/{quote(QUERY)}"
    page.goto(url, timeout=45000, wait_until="load")
    page.wait_for_timeout(6000)
    out["url"] = url
    out["final"] = page.url
    out["title"] = (page.title() or "")[:90]
    # find repeated card-like structures
    out["candidates"] = page.evaluate(
        """() => {
        const sels = ['article','.card','.item','.list-item','[class*=item]','[class*=card]','li','tr'];
        const res = {};
        for (const s of sels) {
            const n = document.querySelectorAll(s).length;
            if (n) res[s] = n;
        }
        return res;
    }"""
    )
    # harvest links that look like detail pages
    links = page.eval_on_selector_all("a[href]", "e=>e.map(x=>x.href)")
    detail = [
        l for l in links
        if "jidiyouxi.com" in l and any(k in l for k in ("/game/", "/detail/", "/topic/detail/", ".html"))
    ]
    out["detail_links"] = len(detail)
    out["detail_sample"] = detail[:6]
    out["fixture"] = save_fixture("jidiyouxi", "search_ai.html", page.content())
    page.close()
    return out


def probe_catcat_search(ctx) -> dict:
    """catcat is Alist: try the Ctrl+K palette and the Alist search API."""
    out: dict = {}
    page = ctx.new_page()
    reqs: list[str] = []
    page.on("response", lambda r: reqs.append(f"{r.status} {r.url}"))
    page.goto("https://catcat.cloud/", timeout=45000, wait_until="load")
    page.wait_for_timeout(9000)

    # Alist exposes /api/fs/search (POST). Try it directly in-page.
    api = page.evaluate(
        """async (q) => {
        const tries = [
            {url:'/api/fs/search', body:{parent:'/', keywords:q, scope:0, page:1, per_page:20}},
        ];
        const out = [];
        for (const t of tries) {
            try {
                const r = await fetch(t.url, {
                    method:'POST',
                    headers:{'Content-Type':'application/json'},
                    body: JSON.stringify(t.body),
                });
                const txt = await r.text();
                out.push({url:t.url, status:r.status, head:txt.slice(0,400)});
            } catch (e) { out.push({url:t.url, err:String(e).slice(0,150)}); }
        }
        return out;
    }""",
        QUERY,
    )
    out["alist_api"] = api

    # also try opening the palette
    try:
        page.keyboard.press("Control+k")
        page.wait_for_timeout(1500)
        out["palette_inputs"] = page.locator("input").count()
        out["palette_visible"] = page.locator("input").first.is_visible() if page.locator("input").count() else False
    except Exception as exc:  # noqa: BLE001
        out["palette_err"] = f"{type(exc).__name__}: {str(exc)[:120]}"

    out["responses_tail"] = reqs[-12:]
    out["fixture"] = save_fixture("catcat", "home.html", page.content())
    page.close()
    return out


def probe_gamer520_detail(ctx) -> dict:
    """gamer520: find a result link then extract detail-page structure."""
    out: dict = {}
    page = ctx.new_page()
    page.goto(f"https://www.gamer520.com/?s={quote(QUERY)}", timeout=45000, wait_until="load")
    page.wait_for_timeout(3000)
    links = page.eval_on_selector_all("a[href]", "e=>e.map(x=>x.href)")
    details = [
        l for l in links
        if "gamer520.com" in l and l.rstrip("/").endswith(".html")
    ]
    out["detail_links"] = len(details)
    out["detail_sample"] = details[:5]
    out["search_fixture"] = save_fixture("gamer520", "search_ai.html", page.content())

    if details:
        d = ctx.new_page()
        d.goto(details[0], timeout=45000, wait_until="load")
        d.wait_for_timeout(3000)
        out["detail_url"] = details[0]
        out["detail_title"] = (d.title() or "")[:100]
        out["og"] = d.evaluate(
            """() => {
            const g = s => (document.querySelector(s)||{}).content || null;
            return {
                og_image: g('meta[property="og:image"]'),
                og_desc: (g('meta[property="og:description"]')||'').slice(0,200),
                desc: (g('meta[name="description"]')||'').slice(0,200),
            };
        }"""
        )
        out["content_containers"] = d.evaluate(
            """() => {
            const sels = ['article','.content','.post-content','.entry-content','.markdown-body','.entry','main'];
            const r = {};
            for (const s of sels) { const n=document.querySelectorAll(s).length; if(n) r[s]=n; }
            return r;
        }"""
        )
        # download-ish links
        out["download_links"] = d.evaluate(
            """() => Array.from(document.querySelectorAll('a[href]'))
                .map(a=>({t:(a.textContent||'').trim().slice(0,30), h:a.href}))
                .filter(x=>/pan\\.|magnet:|download|dl\\.|\\/down|quark|baidu|123pan|lanzou|aliyundrive|alipan|115\\.com|pikpak|mega\\.nz/i.test(x.h))
                .slice(0,15)"""
        )
        out["detail_fixture"] = save_fixture("gamer520", "detail_sample.html", d.content())
        d.close()
    page.close()
    return out


if __name__ == "__main__":
    results = {}
    with sync_playwright() as p:
        ctx = launch(p)
        for name, fn in (
            ("jidiyouxi", probe_jidiyouxi_url),
            ("gamer520", probe_gamer520_detail),
            ("catcat", probe_catcat_search),
        ):
            try:
                results[name] = fn(ctx)
            except Exception as exc:  # noqa: BLE001
                results[name] = {"fatal": f"{type(exc).__name__}: {str(exc)[:250]}"}
        ctx.close()
    dest = Path(__file__).with_name("probe_selectors.json")
    dest.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[wrote {dest}]")
