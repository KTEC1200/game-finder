"""Diagnose the two 403 sites: ankergames and iacg (爱之列车).

Both returned 403 with headless Chrome. Distinguish:
  - real Cloudflare block (needs login/JS challenge)
  - headless detection (headful or stealth args may pass)
  - wrong URL shape (template still right, but needs a warm-up visit)

Test matrix per site: headless / headful / headless+UA override / warm-up-then-search.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
BASE = Path(r"D:\K\deepseek\_gf_403_probe")
PROXY = "http://127.0.0.1:6234"
HERE = Path(__file__).parent
EN = "enderlilies"
ZH = "终焉之莉莉"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36")

TARGETS = {
    "ankergames": f"https://ankergames.net/search/{quote(EN)}",
    "iacg": f"https://iacg.love/?s={quote(ZH)}&type=post&trem=4",
}
HOMES = {
    "ankergames": "https://ankergames.net/",
    "iacg": "https://iacg.love/",
}


def attempt(label: str, sid: str, url: str, headless: bool,
            ua: str | None, warm: bool) -> dict:
    prof = BASE / f"{sid}_{label}"
    prof.mkdir(parents=True, exist_ok=True)
    rec = {"site": sid, "variant": label}
    try:
        with sync_playwright() as p:
            kw = dict(user_data_dir=str(prof), channel="chrome",
                      executable_path=CHROME, headless=headless,
                      timeout=60000, proxy={"server": PROXY})
            if ua:
                kw["user_agent"] = ua
            ctx = p.chromium.launch_persistent_context(**kw)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            if warm:
                try:
                    page.goto(HOMES[sid], timeout=35000, wait_until="load")
                    page.wait_for_timeout(4000)
                except Exception:  # noqa: BLE001
                    pass
            resp = page.goto(url, timeout=40000, wait_until="load")
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(2500)
            body = page.evaluate("() => document.body.innerText || ''")
            links = page.evaluate(
                "() => Array.from(document.querySelectorAll('a[href]')).length")
            rec.update({
                "status": resp.status if resp else None,
                "title": (page.title() or "")[:100],
                "body_len": len(body),
                "links": links,
                "body_head": body[:200].replace("\n", " "),
                "ok": bool(resp and resp.status < 400 and len(body) > 300),
            })
            ctx.close()
    except Exception as exc:  # noqa: BLE001
        rec["error"] = f"{type(exc).__name__}: {str(exc)[:130]}"
        rec["ok"] = False
    return rec


if __name__ == "__main__":
    results = []
    for sid, url in TARGETS.items():
        results.append(attempt("headless", sid, url, True, None, False))
        results.append(attempt("headful", sid, url, False, None, False))
        results.append(attempt("headless_ua", sid, url, True, UA, False))
        results.append(attempt("warm_then_search", sid, url, True, None, True))

    (HERE / "probe_403.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    for r in results:
        flag = "OK  " if r.get("ok") else "FAIL"
        print(f"{flag} {r['site']:<12} {r['variant']:<18} st={r.get('status')} "
              f"body={r.get('body_len')} links={r.get('links')} "
              f"{r.get('error','')} {r.get('title','')[:50]}")
