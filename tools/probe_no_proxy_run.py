"""一次性探针：**不开代理**跑完整 pipeline（run()），看哪些站真能出结果。

用法:
  python tools/probe_no_proxy_run.py zh "终焉之莉莉"
  python tools/probe_no_proxy_run.py en "enderlilies"

只读 config.yaml 做内存副本（proxy.enabled=False），不写回。
stdout 只打 ASCII；完整结果写 UTF-8 JSON。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from finder.lang import detect_lang  # noqa: E402
from finder.pipeline import run  # noqa: E402
from finder.sites import filter_sites_by_lang, load_sites  # noqa: E402

HERE = Path(__file__).parent


def ascii_safe(text: object, limit: int = 160) -> str:
    s = str(text).encode("ascii", "backslashreplace").decode("ascii")
    return " ".join(s.split())[:limit]


def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else "\u7ec8\u7109\u4e4b\u8389\u8389"
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    cfg["proxy"] = {"enabled": False, "server": ""}
    cfg["browser"]["headless"] = True
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 3

    sites = load_sites(ROOT / "sites.yaml")
    lang = detect_lang(query)
    part, skipped = filter_sites_by_lang(sites, lang)
    print(f"query={ascii_safe(query)} lang={lang} participating={len(part)} "
          f"skipped={len(skipped)} workers={workers} proxy=off")

    t0 = time.time()
    results = run(cfg, part, query, ROOT, store=None, use_cache=False, workers=workers)
    total_ms = int((time.time() - t0) * 1000)

    rows = []
    for d in results:
        row = {
            "site": d.site_id,
            "error": d.error,
            "title": d.title,
            "url": d.url,
            "downloads": [{"kind": x.kind, "url": x.url} for x in d.downloads],
            "extra": {
                k: v
                for k, v in (d.extra or {}).items()
                if k in {"hits", "best_url", "evidence", "evidence_found",
                         "evidence_required", "query_used", "match",
                         "galgamex_clicks", "galgamex_errors", "cached"}
            },
        }
        rows.append(row)
        print(f"  {d.site_id:14s} err={ascii_safe(str(d.error or '-'), 40):42s} "
              f"dl={len(d.downloads)} hits={(d.extra or {}).get('hits')}")

    ok = sum(1 for r in rows if r["error"] is None)
    withdl = sum(1 for r in rows if r["downloads"])
    print(f"total {total_ms}ms ok={ok}/{len(rows)} with_downloads={withdl}")

    out = {"query": query, "lang": lang, "workers": workers,
           "proxy": "off", "total_ms": total_ms, "rows": rows}
    path = HERE / "probe_no_proxy_run.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"written {path}")


if __name__ == "__main__":
    main()
