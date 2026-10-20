"""End-to-end live run: `search_one` on galgamex, search page → detail → popup flow.

Covers the whole shipped chain (search → parse → pick_best → evidence gate →
popup_redirect download flow), not just the download helper.

The local proxy (127.0.0.1:6234) is DOWN, so this uses a config copy with
`proxy.enabled: false` and the real Chrome UA. Nothing is written back to
config.yaml.
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
from finder.pipeline import search_one  # noqa: E402
from finder.sites import filter_sites_by_lang, load_sites  # noqa: E402

HERE = Path(__file__).parent
QUERIES = ["\u590f\u8272\u56db\u53f6\u8349", "summer clover"]


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    cfg["proxy"] = {"enabled": False, "server": ""}
    cfg["browser"]["headless"] = True

    sites = load_sites(ROOT / "sites.yaml")
    gal = [s for s in sites if s.id == "galgamex"]
    assert gal, "galgamex missing from sites.yaml"
    site = gal[0]

    out = {"site": site.id, "selector": site.search.download_open_selector, "runs": []}
    for q in QUERIES:
        participating, _skipped = filter_sites_by_lang(sites, "zh" if q == QUERIES[0] else "en")
        in_lang = any(s.id == "galgamex" for s in participating)
        t0 = time.time()
        row: dict = {"query": q, "participates_for_lang": in_lang}
        page = None
        try:
            with BrowserSession.for_site(cfg, ROOT, site) as sess:
                page = sess.new_page()
                card = search_one(page, site, q)
            row["error"] = card.error
            row["title"] = card.title
            row["detail_url"] = card.url
            row["downloads"] = [{"kind": d.kind, "url": d.url} for d in card.downloads]
            row["extra"] = {
                k: v
                for k, v in (card.extra or {}).items()
                if k
                in {
                    "hits",
                    "best_url",
                    "evidence",
                    "evidence_found",
                    "evidence_required",
                    "query_used",
                    "galgamex_clicks",
                    "galgamex_errors",
                    "match",
                }
            }
        except Exception as exc:  # noqa: BLE001
            row["exception"] = f"{type(exc).__name__}: {exc}"[:400]
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:  # noqa: BLE001
                    pass
        row["ms"] = int((time.time() - t0) * 1000)
        out["runs"].append(row)
        print(
            f"query={q!r} err={str(row.get('error'))[:40]!r} "
            f"dl={len(row.get('downloads') or [])} ms={row['ms']}"
        )

    (HERE / "probe_e2e_galgamex.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("wrote probe_e2e_galgamex.json")


if __name__ == "__main__":
    main()
