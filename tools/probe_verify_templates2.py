"""Re-probe the template cases that looked bad, with proper SPA waiting.

The first pass used domcontentloaded + 3.5s, which is too early for SPA sites
(body_len 89-293 means the shell only). This pass waits for networkidle and
counts REAL result links, which is the only thing that matters.

Also separates genuine blocks (403/cloudflare) from slow renders.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import quote, urlparse

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = Path(r"D:\K\deepseek\_gf_verify2_probe")
PROXY = "http://127.0.0.1:6234"
HERE = Path(__file__).parent

ZH = "终焉之莉莉"
EN = "enderlilies"

CASES = [
    ("jidiyouxi", "https://www.jidiyouxi.com/search/detail/{q}", ZH),
    ("inarigal", "https://inarigal.com/?search={q}", ZH),
    ("ankergames", "https://ankergames.net/search/{q}", EN),
    ("iacg", "https://iacg.love/?s={q}&type=post&trem=4", ZH),
    ("galgame.dev", "https://galgame.dev/search?term={q}&in=titles", ZH),
    ("playzip", "https://playzip.com/?keywords={q}", EN),
    ("gamer520", "https://www.gamer520.com/?s={q}", ZH),
    ("flysheep", "https://www.flysheep6.com/?s={q}", ZH),
    ("nyaa", "https://sukebei.nyaa.si/?f=0&c=1_3&q={q}", EN),
    ("nysoure", "https://nysoure.com/search?keyword={q}&sort=8", ZH),
    ("lzacg", "https://lzacg.cc/?s={q}", ZH),
    ("acggw", "https://www.acggw.me/?post_type=post&s={q}", ZH),
    ("nekogal", "https://www.nekogal.com/?s={q}", ZH),
    ("ggbases", "https://ggbases.dlgal.com/search.so?p=0&title={q}", EN),
    ("galgamex", "https://www.galgamex.net/search?q={q}", ZH),
    ("kungal", "https://www.kungal.com/search?keywords={q}", ZH),
    ("shinnku", "https://www.shinnku.com/search?q={q}", ZH),
    ("byrutgame", "https://byrutgame.org/index.php?do=search&subaction=search&search_start=0&full_search=0&story={q}", EN),
]

BLOCK = ["cloudflare", "just a moment", "attention required", "access denied",
         "captcha", "人机验证", "安全验证"]


def main() -> None:
    out: list[dict] = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE), channel="chrome", executable_path=CHROME,
            headless=True, timeout=60_000, proxy={"server": PROXY},
        )
        for sid, tpl, q in CASES:
            url = tpl.format(q=quote(q))
            rec: dict = {"id": sid, "url": url}
            page = ctx.new_page()
            t0 = time.time()
            try:
                resp = page.goto(url, timeout=45000, wait_until="load")
                # let SPAs settle: try networkidle, tolerate timeout
                try:
                    page.wait_for_load_state("networkidle", timeout=12000)
                except Exception:  # noqa: BLE001
                    pass
                page.wait_for_timeout(2500)

                body = page.evaluate("() => document.body.innerText || ''")
                html = page.content()
                origin = urlparse(page.url).netloc
                links = page.evaluate(
                    "() => Array.from(document.querySelectorAll('a[href]')).map(a=>a.href)"
                )
                # same-origin, non-nav links = candidate results
                nav = re.compile(r"/(login|register|tag|category|page/\d|about|contact|"
                                 r"privacy|terms|feed|rss|user|profile)(/|$|\?)", re.I)
                cand = [l for l in set(links)
                        if urlparse(l).netloc == origin and not nav.search(urlparse(l).path)]
                # links whose text mentions the query
                hit_links = page.evaluate(
                    """(q) => Array.from(document.querySelectorAll('a[href]'))
                        .filter(a => (a.innerText||'').toLowerCase().includes(q.toLowerCase()))
                        .map(a => ({t:(a.innerText||'').trim().slice(0,60), h:a.href}))
                        .slice(0,8)""",
                    q,
                )
                title = (page.title() or "")[:110]
                low = (title + body[:2000]).lower()
                blocked = next((b for b in BLOCK if b in low), None)

                rec.update({
                    "status": resp.status if resp else None,
                    "title": title,
                    "body_len": len(body),
                    "candidate_links": len(cand),
                    "query_links": len(hit_links),
                    "query_links_sample": hit_links[:4],
                    "blocked": blocked,
                    "final_url": page.url,
                })
                # verdict: usable if page loaded AND we found result-ish links
                rec["ok"] = bool(
                    resp and resp.status < 400 and not blocked
                    and (len(cand) >= 3 or len(hit_links) >= 1)
                )
            except Exception as exc:  # noqa: BLE001
                rec["ok"] = False
                rec["error"] = f"{type(exc).__name__}: {str(exc)[:130]}"
            rec["ms"] = int((time.time() - t0) * 1000)
            out.append(rec)
            page.close()
        ctx.close()

    dest = HERE / "verify_templates2.json"
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    ok = sum(1 for r in out if r.get("ok"))
    print(f"OK {ok}/{len(out)}")
    for r in out:
        flag = "OK  " if r.get("ok") else "FAIL"
        note = r.get("blocked") or r.get("error") or ""
        print(f"{flag} {r['id']:<12} st={r.get('status')} {r.get('ms')}ms "
              f"body={r.get('body_len')} cand={r.get('candidate_links')} "
              f"qlinks={r.get('query_links')} {note}")


if __name__ == "__main__":
    main()
