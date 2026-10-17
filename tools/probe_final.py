"""Throwaway probe #18: close the last three gaps.

probe #17 results:
  catcat Ctrl+K: input exists but searching "GalGame" -> "暂无结果" (search
    BROKEN). Palette does list top dirs (Book/CosAV/GalGame/comic).
  jidiyouxi detail: rich content (title, 发行日期/类型/大小/厂商/Steam好评率,
    full 游戏介绍, 修改器 list) BUT my pan/magnet regex found 0 download links.
  relevance: gamer520 real query works great (found 赛博朋克2077 终极典藏版);
    jidiyouxi real query -> 0 titles, but that is likely my TITLE SELECTOR
    being wrong (the "AI" run found 41 detail links via a[href] harvest).

Q1 jidiyouxi: does /search/detail/<real game> return RELEVANT detail links?
   Harvest links + titles, no fancy selectors.
Q2 jidiyouxi: where is the download link on a detail page? Find elements whose
   text contains 下载/网盘/提取码 and dump their HTML.
Q3 catcat: does Alist POST /api/fs/list work for browsing? (fallback if search
   is truly dead)
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote, urlparse

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = Path(r"D:\K\deepseek\_gf_final_probe")
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


def q1_jidi_relevance(ctx) -> dict:
    out: dict = {}
    page = ctx.new_page()
    url = f"https://www.jidiyouxi.com/search/detail/{quote(REAL_GAME)}"
    page.goto(url, timeout=45000, wait_until="load")
    page.wait_for_timeout(6000)
    out["url"] = url
    # harvest ALL same-domain links, then look at anchor TEXT (title)
    pairs = page.evaluate(
        """() => Array.from(document.querySelectorAll('a[href]'))
            .map(a=>({t:(a.textContent||'').trim().slice(0,80), h:a.href}))"""
    )
    topics = [
        x for x in pairs
        if "/topic/detail/" in x["h"] and x["t"]
    ]
    out["n_topic_links"] = len(topics)
    out["topic_titles"] = [x["t"] for x in topics[:12]]
    # body text preview to see if results rendered at all
    out["body_head"] = page.inner_text("body")[:400]
    page.close()
    return out


def q2_jidi_download(ctx) -> dict:
    out: dict = {}
    page = ctx.new_page()
    url = "https://www.jidiyouxi.com/topic/detail/20093940"
    page.goto(url, timeout=45000, wait_until="load")
    page.wait_for_timeout(5000)
    out["url"] = url
    # every element whose own text mentions download-ish words
    out["dl_elements"] = page.evaluate(
        """() => {
        const kw = /下载|网盘|提取码|秒传|磁力|BT|种子/;
        const hits = [];
        document.querySelectorAll('a,button,div,span,li').forEach(el => {
            const own = (el.textContent||'').trim();
            if (!own || own.length > 40) return;
            if (!kw.test(own)) return;
            // only leaf-ish nodes
            if (el.querySelector('a,button')) return;
            hits.push({
                tag: el.tagName,
                cls: (el.className||'').toString().slice(0,70),
                text: own.slice(0,40),
                href: el.tagName === 'A' ? el.href : null,
            });
        });
        return hits.slice(0, 25);
    }"""
    )
    # all anchors pointing off-site or to pan domains
    out["external_anchors"] = page.evaluate(
        """() => Array.from(document.querySelectorAll('a[href]'))
            .map(a=>({t:(a.textContent||'').trim().slice(0,30), h:a.href}))
            .filter(x=>/^https?:/.test(x.h) && !/jidiyouxi\\.com/.test(x.h))
            .slice(0,20)"""
    )
    page.close()
    return out


def q3_catcat_browse(ctx) -> dict:
    out: dict = {}
    page = ctx.new_page()
    page.goto("https://catcat.cloud/", timeout=45000, wait_until="load")
    page.wait_for_timeout(8000)
    res = page.evaluate(
        """async () => {
        const call = async (path) => {
            try {
                const r = await fetch('/api/fs/list', {
                    method:'POST',
                    headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({path, password:'', page:1, per_page:30, refresh:false}),
                });
                const j = await r.json();
                return {status:r.status, code:j.code, msg:j.message,
                        n:(j.data&&j.data.content||[]).length,
                        names:(j.data&&j.data.content||[]).map(f=>f.name).slice(0,15)};
            } catch(e) { return {err:String(e).slice(0,120)}; }
        };
        return {root: await call('/'), galgame: await call('/GalGame')};
    }"""
    )
    out["alist_list"] = res
    page.close()
    return out


if __name__ == "__main__":
    results = {}
    with sync_playwright() as p:
        ctx = launch(p)
        for name, fn in (
            ("jidi_relevance", q1_jidi_relevance),
            ("jidi_download", q2_jidi_download),
            ("catcat_browse", q3_catcat_browse),
        ):
            try:
                results[name] = fn(ctx)
            except Exception as exc:  # noqa: BLE001
                results[name] = {"fatal": f"{type(exc).__name__}: {str(exc)[:250]}"}
        ctx.close()
    dest = Path(__file__).with_name("probe_final.json")
    dest.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[wrote {dest}]")
