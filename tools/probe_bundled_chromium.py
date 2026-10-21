"""一次性探针：打包版能不能用 **Playwright 自带 Chromium** 代替系统 Chrome。

如果自带 Chromium 也能过 Cloudflare 系站点，便携版就不必要求用户装 Chrome，
体积换独立性；如果过不了，就必须优先用系统 Chrome。

输出写 JSON 再读（GBK 控制台会把 CJK 打成乱码）。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

HERE = Path(__file__).parent
OUT = HERE / "probe_bundled_chromium.json"

# 用真 UA（Chrome 155），与 shipped 代码一致；这里刻意不继承系统 Chrome
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/155.0.0.0 Safari/537.36"
)

TARGETS = [
    ("galgamex", "https://www.galgamex.net/search?q=%E5%A4%8F%E8%89%B2%E5%9B%9B%E5%8F%B6%E8%8D%89"),
    ("touchgal", "https://www.touchgal.ink/"),
    ("gamer520", "https://www.gamer520.com/"),
    ("ankergames", "https://ankergames.net/"),
    ("iacg", "https://iacg.love/"),
    ("anime-sharing", "https://www.anime-sharing.com/"),
]


def main() -> None:
    from playwright.sync_api import sync_playwright

    profile = HERE / "_probe_chromium_profile"
    out: dict = {"ua": UA, "profile": str(profile), "rows": {}}
    with sync_playwright() as pw:
        for label, url in TARGETS:
            row: dict = {"url": url}
            t0 = time.time()
            ctx = None
            try:
                ctx = pw.chromium.launch_persistent_context(
                    user_data_dir=str(profile / label),
                    headless=True,
                    user_agent=UA,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                page = ctx.new_page()
                resp = page.goto(url, timeout=45000, wait_until="domcontentloaded")
                row["status"] = resp.status if resp else None
                row["title"] = (page.title() or "")[:100]
                html = page.content() or ""
                low = html.lower()
                row["bytes"] = len(html.encode("utf-8", "replace"))
                row["cf_challenge"] = (
                    "just a moment" in low
                    or "cf-error-details" in low
                    or "challenge-platform" in low
                )
                row["anchors"] = page.evaluate(
                    "() => document.querySelectorAll('a[href]').length"
                )
            except Exception as exc:  # noqa: BLE001
                row["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
            finally:
                if ctx is not None:
                    try:
                        ctx.close()
                    except Exception:  # noqa: BLE001
                        pass
            row["ms"] = int((time.time() - t0) * 1000)
            out["rows"][label] = row
            print(f"{label:14s} {row.get('status')} {row['ms']}ms "
                  f"a={row.get('anchors')} cf={row.get('cf_challenge')} "
                  f"{row.get('error', '')}")

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"written {OUT}")


if __name__ == "__main__":
    main()
