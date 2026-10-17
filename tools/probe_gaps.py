"""Throwaway probe #17: last gaps before writing the plan.

Open questions:
  Q1 catcat's /api/fs/search returned HTTP 500 (meilisearch error). Does the
     Ctrl+K palette search actually work end-to-end? If not, catcat is NOT
     searchable and must not be promised as a P2 site.
  Q2 jidiyouxi detail page (/topic/detail/NNN): what does it contain?
     Does it expose download links (pan/magnet)?
  Q3 Does a REAL game name (not "AI") return relevant results on jidiyouxi
     and gamer520? "AI" is the health-probe word; relevance matters for the
     matching logic.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = Path(r"D:\K\deepseek\_gf_gap_probe")
PROXY = "http://127.0.0.1:6234"
REAL_GAME = "赛博朋克2077"


def launch(p):
    return p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE),
        channel="chrome",
        executable_path=CHROME,
        headless=True,
        timeout=60_000,
        proxy={"server": PROXY},
    )


def q1_catcat_palette(ctx) -> dict:
    out: dict = {}
    page = ctx.new_page()
    page.goto("https://catcat.cloud/", timeout=45000, wait_until="load")
    page.wait_for_timeout(9000)
    page.keyboard.press("Control+k")
    page.wait_for_timeout(2000)
    n = page.locator("input").count()
    out["inputs"] = n
    if n:
        inp = page.locator("input").first
        inp.fill("GalGame")
        page.wait_for_timeout(4000)
        # capture what the palette shows
        out["dialog_text"] = page.evaluate(
            """() => {
            const d = document.querySelector('[role=dialog],.modal,.overlay,[class*=dialog],[class*=command]');
            return d ? d.innerText.slice(0,800) : (document.body.innerText.slice(0,500));
        }"""
        )
        out["links_after"] = page.evaluate(
            """() => Array.from(document.querySelectorAll('a[href]'))
                .map(a=>({t:(a.textContent||'').trim().slice(0,40),h:a.href}))
                .filter(x=>/\\/GalGame|\\/Book|\\/comic|\\/CosAV/i.test(x.h)).slice(0,10)"""
        )
    page.close()
    return out


def q2_jidiyouxi_detail(ctx) -> dict:
    out: dict = {}
    page = ctx.new_page()
    url = "https://www.jidiyouxi.com/topic/detail/20093940"
    page.goto(url, timeout=45000, wait_until="load")
    page.wait_for_timeout(5000)
    out["url"] = url
    out["title"] = (page.title() or "")[:100]
    out["text_head"] = page.inner_text("body")[:700]
    out["download_links"] = page.evaluate(
        """() => Array.from(document.querySelectorAll('a[href]'))
            .map(a=>({t:(a.textContent||'').trim().slice(0,30),h:a.href}))
            .filter(x=>/pan\\.|magnet:|quark|baidu|123pan|lanzou|aliyundrive|alipan|115\\.com|pikpak|mega\\.nz|xunlei|\\/down/i.test(x.h))
            .slice(0,15)"""
    )
    out["og"] = page.evaluate(
        """() => ({
        img: (document.querySelector('meta[property="og:image"]')||{}).content||null,
        desc: ((document.querySelector('meta[name=description]')||{}).content||'').slice(0,200)
    })"""
    )
    page.close()
    return out


def q3_relevance(ctx) -> dict:
    out: dict = {}
    for site, tpl in (
        ("jidiyouxi", "https://www.jidiyouxi.com/search/detail/{q}"),
        ("gamer520", "https://www.gamer520.com/?s={q}"),
    ):
        page = ctx.new_page()
        url = tpl.format(q=quote(REAL_GAME))
        entry: dict = {"url": url}
        try:
            page.goto(url, timeout=45000, wait_until="load")
            page.wait_for_timeout(5000)
            titles = page.evaluate(
                """() => Array.from(document.querySelectorAll('h2 a,h3 a,.entry-title a,article a,[class*=title] a'))
                    .map(a=>(a.textContent||'').trim()).filter(t=>t.length>3).slice(0,10)"""
            )
            entry["titles"] = titles
            entry["n_titles"] = len(titles)
        except Exception as exc:  # noqa: BLE001
            entry["err"] = f"{type(exc).__name__}: {str(exc)[:150]}"
        out[site] = entry
        page.close()
    return out


if __name__ == "__main__":
    results = {}
    with sync_playwright() as p:
        ctx = launch(p)
        for name, fn in (
            ("catcat_palette", q1_catcat_palette),
            ("jidiyouxi_detail", q2_jidiyouxi_detail),
            ("relevance", q3_relevance),
        ):
            try:
                results[name] = fn(ctx)
            except Exception as exc:  # noqa: BLE001
                results[name] = {"fatal": f"{type(exc).__name__}: {str(exc)[:250]}"}
        ctx.close()
    dest = Path(__file__).with_name("probe_gaps.json")
    dest.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[wrote {dest}]")
