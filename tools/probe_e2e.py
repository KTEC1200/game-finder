"""Throwaway probe #38: END-TO-END extraction dry-run for the P2 sites.

Purpose: with a REAL game name, run the exact pipeline the app will run
(search -> pick top detail links -> extract card fields) and dump what a
generic extractor recovers. The output of this probe becomes the extraction
rules encoded in finder/detail.py and the site adapters in sites.yaml.

Sites: jidiyouxi (url mode /search/detail/{q}), gamer520 (url mode /?s={q}).
Query: a real game name (see QUERY below).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = Path(r"D:\K\deepseek\_gf_e2e_probe")
PROXY = "http://127.0.0.1:6234"
HERE = Path(__file__).parent
QUERY = "剑星"

PAN_RE = (r"https?://[^\s\"'<>\\]*(?:pan\.baidu\.com|pan\.quark\.cn|pan\.xunlei\.com|"
          r"aliyundrive\.com|alipan\.com|123pan\.com|lanzou[a-z]?\.com|"
          r"magnet:\?xt=urn:btih:[a-fA-F0-9]{6,40})[^\s\"'<>\\]*")
CODE_RE = r"(?:提取码|密码|pwd)\s*[:：=]?\s*([a-zA-Z0-9]{4})"


def clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def extract(page) -> dict:
    """The generic card extractor under test."""
    meta = page.evaluate(
        """() => {
            const g = (p) => { const e = document.querySelector(`meta[property="${p}"]`) || document.querySelector(`meta[name="${p}"]`); return e ? e.getAttribute('content') : null; };
            return {og_title: g('og:title'), og_image: g('og:image'),
                    og_desc: g('og:description'), desc: g('description'),
                    title: document.title};
        }"""
    )
    html = page.evaluate("() => document.documentElement.outerHTML")
    pans = sorted(set(re.findall(PAN_RE, html)))
    codes = sorted(set(re.findall(CODE_RE, html)))
    text = page.evaluate("() => document.body.innerText || ''")

    def find(label: str) -> str | None:
        m = re.search(re.escape(label) + r"\s*\n\s*([^\n]{1,60})", text)
        return clean(m.group(1)) if m else None

    return {
        "title": clean(meta["og_title"] or meta["title"]),
        "cover": meta["og_image"],
        "intro": clean(meta["og_desc"] or meta["desc"])[:400],
        "size": (re.search(r"\b\d+(?:\.\d+)?\s?(?:GB|MB)\b", text) or [None])[0]
        if re.search(r"\b\d+(?:\.\d+)?\s?(?:GB|MB)\b", text) else None,
        "version": (re.search(r"\bV?\d+\.\d+(?:\.\d+)*(?:\.[A-Za-z]+\d+)?\b", text) or [None])[0],
        "date": (re.search(r"20\d{2}[-/年.]\d{1,2}[-/月.]\d{1,2}", text) or [None])[0],
        "pan_links": pans[:12],
        "pan_total": len(pans),
        "codes": codes[:8],
        "label_date": find("游戏发行日期"),
        "label_size": find("游戏类型"),
    }


def run_site(page, name: str, search_url: str, link_re: str) -> dict:
    res: dict = {"site": name, "search_url": search_url}
    page.goto(search_url, timeout=45000, wait_until="load")
    page.wait_for_timeout(6000)
    links = page.evaluate(
        r"""(pat) => {
            const re = new RegExp(pat);
            return Array.from(new Set(Array.from(document.querySelectorAll('a[href]'))
                .map(a => a.href).filter(h => re.test(h))));
        }""",
        link_re,
    )
    res["detail_links"] = links[:12]
    res["detail_total"] = len(links)

    cards = []
    for u in links[:3]:
        try:
            page.goto(u, timeout=45000, wait_until="load")
            page.wait_for_timeout(6000)
            c = extract(page)
            c["url"] = u
            cards.append(c)
        except Exception as e:  # noqa: BLE001
            cards.append({"url": u, "error": str(e)[:160]})
    res["cards"] = cards
    return res


def main() -> None:
    out: dict = {"query": QUERY, "sites": []}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE), channel="chrome", executable_path=CHROME,
            headless=True, timeout=60_000, proxy={"server": PROXY},
        )
        page = ctx.new_page()
        q = quote(QUERY)
        out["sites"].append(run_site(
            page, "jidiyouxi",
            f"https://www.jidiyouxi.com/search/detail/{q}",
            r"jidiyouxi\.com/topic/detail/\d+",
        ))
        out["sites"].append(run_site(
            page, "gamer520",
            f"https://www.gamer520.com/?s={q}",
            r"gamer520\.com/\d+\.html",
        ))
        ctx.close()

    (HERE / "probe_e2e.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [f"QUERY = {QUERY}"]
    for s in out["sites"]:
        lines.append(f"\n=== {s['site']} === search={s['search_url']}")
        lines.append(f"detail_total={s['detail_total']}")
        for c in s["cards"]:
            lines.append(f"  URL {c.get('url')}")
            if "error" in c:
                lines.append(f"    ERROR {c['error']}")
                continue
            lines.append(f"    title={c['title']!r}")
            lines.append(f"    cover={c['cover']!r}")
            lines.append(f"    intro={c['intro'][:200]!r}")
            lines.append(f"    size={c['size']!r} version={c['version']!r} date={c['date']!r}")
            lines.append(f"    label_date={c['label_date']!r} label_size={c['label_size']!r}")
            lines.append(f"    pan_total={c['pan_total']} codes={c['codes']}")
            for x in c["pan_links"][:6]:
                lines.append(f"      PAN {x[:120]}")
    (HERE / "_e2e.txt").write_text("\n".join(lines), encoding="utf-8")
    print("ok -> _e2e.txt")
    for s in out["sites"]:
        print(f"{s['site']}: detail_total={s['detail_total']} cards={len(s['cards'])}")
        for c in s["cards"]:
            if "error" in c:
                print("   ERR", c["error"][:100])
            else:
                print(f"   pans={c['pan_total']} size={c['size']} title_len={len(c['title'] or '')}")


if __name__ == "__main__":
    main()
