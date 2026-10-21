"""一次性探针：真浏览器（无代理）逐个访问站点，看谁直连能通。

urllib 的结论不可靠（Cloudflare 会因 TLS 指纹/UA 差异给 403），必须用真 Chrome。
输出写 JSON 再读（GBK 控制台会把 CJK 打成乱码）。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from finder.browser import BrowserSession  # noqa: E402

HERE = Path(__file__).parent
OUT = HERE / "probe_direct_browser.json"


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    cfg["proxy"] = {"enabled": False, "server": ""}
    cfg["browser"]["headless"] = True

    raw = yaml.safe_load((ROOT / "sites.yaml").read_text(encoding="utf-8"))
    targets = [(i["id"], i["homepage"]) for i in raw["sites"]]
    only = sys.argv[1:]
    if only:
        targets = [t for t in targets if t[0] in only]

    results: dict = {}
    for sid, home in targets:
        row: dict = {"homepage": home}
        t0 = time.time()
        page = None
        try:
            with BrowserSession(cfg, ROOT) as sess:
                page = sess.new_page()
                resp = page.goto(home, timeout=30000, wait_until="domcontentloaded")
                row["status"] = resp.status if resp else None
                row["title"] = (page.title() or "")[:120]
                row["url"] = page.url
                row["anchors"] = page.evaluate(
                    "() => document.querySelectorAll('a[href]').length"
                )
                html = page.content() or ""
                row["html_bytes"] = len(html.encode("utf-8", "replace"))
                low = html.lower()
                row["cf_challenge"] = ("just a moment" in low
                                       or "cf-error-details" in low
                                       or "challenge-platform" in low)
        except Exception as exc:  # noqa: BLE001
            row["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:  # noqa: BLE001
                    pass
        row["ms"] = int((time.time() - t0) * 1000)
        results[sid] = row
        print(f"{sid:14s} {row.get('status')} {row['ms']}ms "
              f"a={row.get('anchors')} cf={row.get('cf_challenge')} "
              f"{row.get('error', '')}")

    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"written {OUT}")


if __name__ == "__main__":
    main()
