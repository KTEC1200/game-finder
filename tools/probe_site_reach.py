"""Throwaway probe #10: network reachability for the P2 target sites.

The spec assumes:
  - a local proxy at 127.0.0.1:7890 for "@" sites
  - P2 sites (机地 / Gamer520 / 猫盘) work WITHOUT proxy

probe #7/#8 showed nothing listens on 7890. So before writing the plan I
need to know, per site, whether DIRECT access works. If the non-@ sites
need a proxy too, P2's "no-magic sites first" staging is wrong.

Direct only (no proxy configured). Reports status, final URL, title, and
whether the body looks like a real page vs an error/interstitial.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
TMP_PROFILE = Path(r"D:\K\deepseek\_gf_reach_profile")

SITES = {
    "jidiyouxi": "https://www.jidiyouxi.com/",
    "gamer520": "https://www.gamer520.com/",
    "catcat": "https://catcat.cloud/",
    "kungal": "https://www.kungal.com/",
    "touchgal": "https://www.touchgal.ink/",
    "anime-sharing": "https://www.anime-sharing.com/",
    "zi0": "https://zi0.cc/",
    "nyaa": "https://sukebei.nyaa.si/",
}

BLOCK_HINTS = [
    "cloudflare", "just a moment", "checking your browser", "attention required",
    "access denied", "403 forbidden", "人机验证", "安全验证", "无法访问此网站",
    "err_", "captcha", "请开启 javascript", "请稍候",
]


def looks_blocked(title: str, body: str) -> str | None:
    t = (title or "").lower()
    b = (body or "")[:3000].lower()
    for hint in BLOCK_HINTS:
        if hint in t or hint in b:
            return hint
    return None


def main() -> None:
    TMP_PROFILE.mkdir(parents=True, exist_ok=True)
    results = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(TMP_PROFILE),
            channel="chrome",
            executable_path=CHROME,
            headless=True,
            timeout=60_000,
        )
        for site_id, url in SITES.items():
            page = ctx.new_page()
            entry = {"site": site_id, "url": url}
            t0 = time.time()
            try:
                resp = page.goto(url, timeout=30_000, wait_until="domcontentloaded")
                entry["status"] = resp.status if resp else None
                entry["final_url"] = page.url
                entry["title"] = (page.title() or "")[:120]
                body = page.inner_text("body")[:3000] if page.locator("body").count() else ""
                entry["body_len"] = len(body)
                blocked = looks_blocked(entry["title"], body)
                if blocked:
                    entry["blocked_hint"] = blocked
                entry["ok"] = bool(entry["status"] and entry["status"] < 400 and not blocked)
            except Exception as exc:  # noqa: BLE001
                entry["error"] = f"{type(exc).__name__}: {str(exc)[:140]}"
                entry["ok"] = False
            entry["ms"] = int((time.time() - t0) * 1000)
            results.append(entry)
            page.close()
        ctx.close()
    # write UTF-8 to a file: the GBK console cannot encode emoji found in
    # page titles (e.g. U+1F433), which crashed a plain print() before.
    out = Path(__file__).with_name("probe_site_reach.json")
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    for r in results:
        status = r.get("status")
        flag = "OK  " if r.get("ok") else "FAIL"
        note = r.get("error") or r.get("blocked_hint") or ""
        print(
            f"{flag} {r['site']:<14} status={status} {r.get('ms')}ms "
            f"body={r.get('body_len')} {note}"
        )
    print(f"[wrote {out}]")


if __name__ == "__main__":
    main()
