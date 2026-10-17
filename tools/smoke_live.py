"""真站冒烟：对指定站点跑一次完整抓取，输出 ASCII 摘要。

用法：
  python tools/smoke_live.py 终焉之莉莉
  python tools/smoke_live.py 终焉之莉莉 --sites jidiyouxi gamer520 flysheep
  python tools/smoke_live.py enderlilies --sites gamer520 --out tools/_my.json

约定：
  - stdout 只打印 ASCII（Windows 控制台是 GBK，打中文会乱码）；
    完整结果（含中文标题/URL）写 UTF-8 JSON。
  - 走的是 finder.pipeline.search_one —— 冒烟验证的就是要交付的那条链路。
  - 浏览器版本用 finder.browser.read_chrome_version()，绝不跑 chrome.exe --version
    （Windows 上它不打印版本，而是激活已有窗口并输出 GBK 文本）。
  - 每站一个 BrowserSession.for_site 会话，site.force_headful 才真的生效。
  - 退出前一定关掉浏览器，不留 Chrome 进程。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from finder.browser import (  # noqa: E402
    DEFAULT_CHROME,
    BrowserSession,
    read_chrome_version,
)
from finder.lang import detect_lang  # noqa: E402
from finder.pipeline import search_one  # noqa: E402
from finder.sites import filter_sites_by_lang, load_sites  # noqa: E402

DEFAULT_OUT = ROOT / "tools" / "smoke_result.json"


def ascii_safe(text: object, limit: int = 200) -> str:
    """把任意文本压成 ASCII 单行，用于 GBK 控制台。"""
    s = str(text).encode("ascii", "backslashreplace").decode("ascii")
    return " ".join(s.split())[:limit]


def result_row(card) -> dict:
    """GameDetail → 只有 ASCII 键、中文值原样保留的 dict（写 JSON 用）。"""
    extra = dict(getattr(card, "extra", {}) or {})
    if card.error is None and card.downloads:
        status = "ok"
    elif card.error in (None, "NO_DOWNLOADS"):
        status = "no_downloads"
    else:
        status = "error"
    return {
        "site": card.site_id,
        "status": status,
        "error": card.error,
        "detail_url": card.url,
        "title": card.title,
        "title_len": len(card.title or ""),
        "cover": bool(card.cover_url),
        "cover_url": card.cover_url,
        "version": card.version,
        "size": card.size,
        "updated_at": card.updated_at,
        "downloads": len(card.downloads),
        "kinds": sorted({d.kind for d in card.downloads}),
        "download_urls": [d.url for d in card.downloads],
        "diagnostics": extra,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--sites", nargs="*", default=None)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    all_sites = load_sites(ROOT / "sites.yaml")
    lang = detect_lang(args.query)
    participating, skipped = filter_sites_by_lang(all_sites, lang)
    total_participating = len(participating)

    unknown: list[str] = []
    if args.sites:
        known = {s.id for s in participating}
        unknown = [sid for sid in args.sites if sid not in known]
        participating = [s for s in participating if s.id in set(args.sites)]

    form_only = [s.id for s in participating if s.search.mode != "url"]
    participating = [s for s in participating if s.search.mode == "url"]  # 只测 url 模式

    chrome_version = ascii_safe(read_chrome_version(str(DEFAULT_CHROME)), 40)
    print(
        f"lang={lang} participating={total_participating} "
        f"smoke_sites={len(participating)} skipped={len(skipped)} "
        f"form_only_skipped={len(form_only)} chrome={chrome_version} "
        f"query_len={len(args.query)}"
    )
    if unknown:
        print(f"WARN not_participating_or_unknown: {','.join(sorted(unknown))}")
    if form_only:
        print(f"NOTE form_mode_not_smoked: {','.join(form_only)}")

    results: list[dict] = []
    for site in participating:
        t0 = time.time()
        page = None
        try:
            with BrowserSession.for_site(cfg, ROOT, site) as sess:
                page = sess.new_page()
                card = search_one(page, site, args.query)
            row = result_row(card)
        except Exception as exc:  # noqa: BLE001
            row = {
                "site": site.id,
                "status": "error",
                "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                "downloads": 0,
            }
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:  # noqa: BLE001
                    pass
        row["ms"] = int((time.time() - t0) * 1000)
        results.append(row)

        diag = row.get("diagnostics") or {}
        gates = diag.get("gate_links") or []
        print(
            f"{row['status']:<13} {row['site']:<14} "
            f"hits={diag.get('hits')} dl={row.get('downloads')} "
            f"body={diag.get('search_body_len')} match={diag.get('match')} "
            f"gates={len(gates)} {row['ms']}ms "
            f"{ascii_safe(row.get('error') or '', 160)}"
        )

    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "query": args.query,
                "lang": lang,
                "chrome_version": chrome_version,
                "participating_for_lang": total_participating,
                "skipped_by_lang": [s.id for s in skipped],
                "form_only_skipped": form_only,
                "unknown_requested": unknown,
                "results": results,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    ok = sum(1 for r in results if r["status"] == "ok")
    with_dl = sum(1 for r in results if (r.get("downloads") or 0) > 0)
    print(f"SUMMARY ok={ok}/{len(results)} with_downloads={with_dl} out={ascii_safe(out.name)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
