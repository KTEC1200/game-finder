"""Verify the user-supplied URL templates (2026-10-17 update list).

The user hand-tested which sites accept address-bar search and gave templates.
This probe checks each template actually loads and returns plausible results,
so the adapter table in the spec is grounded in a second observation.

Writes UTF-8 JSON only (GBK console rule).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = Path(r"D:\K\deepseek\_gf_verify_probe")
PROXY = "http://127.0.0.1:6234"
HERE = Path(__file__).parent

ZH = "终焉之莉莉"
EN = "enderlilies"

# (id, template, lang_to_test)
CASES = [
    ("jidiyouxi", "https://www.jidiyouxi.com/search/detail/{q}", ZH),
    ("playzip", "https://playzip.com/?keywords={q}", EN),
    ("byrutgame", "https://byrutgame.org/index.php?do=search&subaction=search&search_start=0&full_search=0&story={q}", EN),
    ("gamer520", "https://www.gamer520.com/?s={q}", ZH),
    ("ankergames", "https://ankergames.net/search/{q}", EN),
    ("flysheep", "https://www.flysheep6.com/?s={q}", ZH),
    ("nyaa", "https://sukebei.nyaa.si/?f=0&c=1_3&q={q}", EN),
    ("nysoure", "https://nysoure.com/search?keyword={q}&sort=8", ZH),
    ("iacg", "https://iacg.love/?s={q}&type=post&trem=4", ZH),
    ("inarigal", "https://inarigal.com/?search={q}", ZH),
    ("lzacg", "https://lzacg.cc/?s={q}", ZH),
    ("acggw", "https://www.acggw.me/?post_type=post&s={q}", ZH),
    ("nekogal", "https://www.nekogal.com/?s={q}", ZH),
    ("ggbases", "https://ggbases.dlgal.com/search.so?p=0&title={q}", EN),
    ("galgamex", "https://www.galgamex.net/search?q={q}", ZH),
    ("kungal", "https://www.kungal.com/search?keywords={q}", ZH),
    ("galgame.dev", "https://galgame.dev/search?term={q}&in=titles", ZH),
    ("shinnku", "https://www.shinnku.com/search?q={q}", ZH),
]

BLOCK_HINTS = ["cloudflare", "just a moment", "attention required",
               "access denied", "captcha", "人机验证", "安全验证", "请稍候"]


def main() -> None:
    results: list[dict] = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE), channel="chrome", executable_path=CHROME,
            headless=True, timeout=60_000, proxy={"server": PROXY},
        )
        for sid, tpl, q in CASES:
            url = tpl.format(q=quote(q))
            rec: dict = {"id": sid, "url": url, "query": q}
            page = ctx.new_page()
            t0 = time.time()
            try:
                resp = page.goto(url, timeout=35000, wait_until="domcontentloaded")
                page.wait_for_timeout(3500)
                title = (page.title() or "")[:120]
                body = page.evaluate("() => document.body.innerText || ''")
                rec["status"] = resp.status if resp else None
                rec["title"] = title
                rec["body_len"] = len(body)
                rec["final_url"] = page.url
                low = (title + body[:1500]).lower()
                hit = next((h for h in BLOCK_HINTS if h in low), None)
                if hit:
                    rec["blocked"] = hit
                # does the query text actually appear in results?
                rec["query_in_body"] = (q.lower() in body.lower())
                rec["ok"] = bool(resp and resp.status < 400 and not hit and len(body) > 200)
            except Exception as exc:  # noqa: BLE001
                rec["ok"] = False
                rec["error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
            rec["ms"] = int((time.time() - t0) * 1000)
            results.append(rec)
            page.close()
        ctx.close()

    dest = HERE / "verify_templates.json"
    dest.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    ok = sum(1 for r in results if r.get("ok"))
    print(f"OK {ok}/{len(results)}")
    for r in results:
        flag = "OK  " if r.get("ok") else "FAIL"
        extra = r.get("blocked") or r.get("error") or ""
        print(f"{flag} {r['id']:<12} st={r.get('status')} {r.get('ms')}ms "
              f"body={r.get('body_len')} qin={r.get('query_in_body')} {extra}")


if __name__ == "__main__":
    main()
