"""Throwaway probe #42: pick P2's third site from the galgame candidates.

probe #16/#17 showed catcat (猫盘) is an Alist/OpenList netdisk whose own search
API returns 500 (meilisearch 403), so it cannot serve as a P2 search site.
Test the galgame-side candidates for a working search + detail mechanism:
touchgal.ink, ggbases.dlgal.com, nekogal.com, lzacg.cc.

For each: try URL search patterns, count detail links, extract one card.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = Path(r"D:\K\deepseek\_gf_gal_probe")
PROXY = "http://127.0.0.1:6234"
HERE = Path(__file__).parent
QUERY = "千恋万花"

CANDIDATES = [
    ("touchgal", "https://touchgal.ink/", ["/?q={q}", "/search?q={q}", "/?s={q}"]),
    ("ggbases", "https://ggbases.dlgal.com/", ["/search?q={q}", "/?q={q}", "/search.html?q={q}"]),
    ("nekogal", "https://nekogal.com/", ["/search?q={q}", "/?s={q}", "/search/{q}"]),
    ("lzacg", "https://lzacg.cc/", ["/?s={q}", "/search?q={q}", "/search/{q}"]),
]


def main() -> None:
    out: list[dict] = []
    q = quote(QUERY)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE), channel="chrome", executable_path=CHROME,
            headless=True, timeout=60_000, proxy={"server": PROXY},
        )
        for name, base, patterns in CANDIDATES:
            rec: dict = {"site": name, "base": base, "attempts": []}
            page = ctx.new_page()
            for pat in patterns:
                url = base.rstrip("/") + pat.format(q=q)
                att: dict = {"url": url}
                try:
                    page.goto(url, timeout=40000, wait_until="load")
                    page.wait_for_timeout(5000)
                    info = page.evaluate(
                        """() => {
                            const anchors = Array.from(document.querySelectorAll('a[href]')).map(a=>a.href);
                            const same = anchors.filter(h => h.startsWith(location.origin));
                            const uniq = Array.from(new Set(same));
                            // "detail-like" = same-origin path with an id-ish segment
                            const detail = uniq.filter(h => /\\/\\d{2,}|\\/game\\/|\\/detail|\\/post\\/|\\/topic\\/|\\/subject\\/|\\/entry\\//.test(h));
                            return {title: document.title, origin: location.origin,
                                    total_links: uniq.length, detail_links: detail.slice(0,10),
                                    detail_total: detail.length,
                                    text: (document.body.innerText||'').replace(/\\s+/g,' ').slice(0,300)};
                        }"""
                    )
                    att.update(info)
                    att["ok"] = True
                except Exception as e:  # noqa: BLE001
                    att["ok"] = False
                    att["error"] = str(e)[:120]
                rec["attempts"].append(att)
                # keep the best attempt (most detail links)
                if att.get("detail_total", 0) >= 5:
                    break
            # extract one card from the best attempt
            best = max(rec["attempts"], key=lambda a: a.get("detail_total", 0))
            if best.get("detail_total", 0) > 0:
                try:
                    page.goto(best["detail_links"][0], timeout=40000, wait_until="load")
                    page.wait_for_timeout(5000)
                    html = page.content()
                    rec["card"] = {
                        "url": page.url,
                        "title": page.title(),
                        "meta": page.evaluate(
                            """() => { const g=(p)=>{const e=document.querySelector(`meta[property="${p}"]`)||document.querySelector(`meta[name="${p}"]`); return e?e.getAttribute('content'):null;};
                                 return {og_title:g('og:title'), og_image:g('og:image'), og_desc:g('og:description'), desc:g('description')}; }"""
                        ),
                        "pans": sorted(set(re.findall(
                            r"https?://[^\s\"'<>]*(?:pan\.baidu\.com|pan\.quark\.cn|pan\.xunlei\.com|"
                            r"aliyundrive\.com|alipan\.com|123pan\.com|lanzou[a-z]?\.com|magnet:\?xt=)[^\s\"'<>]*",
                            html)))[:8],
                        "magnet_total": len(re.findall(r"magnet:\?xt=urn:btih:", html)),
                        "text_head": re.sub(r"\s+", " ", page.evaluate(
                            "() => document.body.innerText||''"))[:400],
                    }
                except Exception as e:  # noqa: BLE001
                    rec["card"] = {"error": str(e)[:140]}
            page.close()
            out.append(rec)
            print(f"{name}: best_detail={best.get('detail_total',0)} url={best.get('url','')[:80]}")
        ctx.close()

    (HERE / "probe_gal.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = []
    for r in out:
        lines.append(f"\n=== {r['site']} {r['base']} ===")
        for a in r["attempts"]:
            if not a.get("ok"):
                lines.append(f"  {a['url']} ERROR {a['error']}")
                continue
            lines.append(f"  {a['url']}")
            lines.append(f"    title={a['title']!r} links={a['total_links']} detail={a['detail_total']}")
            for d in a["detail_links"][:4]:
                lines.append(f"      {d[:120]}")
            lines.append(f"    text={a['text'][:180]!r}")
        c = r.get("card")
        if c:
            lines.append("  CARD " + json.dumps(c, ensure_ascii=False)[:900])
    (HERE / "_gal.txt").write_text("\n".join(lines), encoding="utf-8")
    print("ok -> _gal.txt")


if __name__ == "__main__":
    main()
