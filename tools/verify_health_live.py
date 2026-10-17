"""真站验证 check_site：只读探测，不写 data/finder.db，stdout 只打 ASCII。

用法： python tools/verify_health_live.py flysheep jidiyouxi
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from finder.browser import BrowserSession  # noqa: E402
from finder.health import check_site  # noqa: E402
from finder.sites import load_sites  # noqa: E402


def safe(text: object, limit: int = 160) -> str:
    s = str(text).encode("ascii", "backslashreplace").decode("ascii")
    return " ".join(s.split())[:limit]


def main(argv: list[str]) -> int:
    want = set(argv[1:]) or {"flysheep", "jidiyouxi"}
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    sites = [s for s in load_sites(ROOT / "sites.yaml") if s.id in want]
    words = cfg["health"]["probe_words"]
    timeout = int(cfg["search"]["timeout_ms"])
    print(f"probing {[s.id for s in sites]} timeout={timeout}")

    with BrowserSession(cfg, ROOT) as sess:
        page = sess.new_page()
        try:
            for site in sites:
                rec = check_site(page, site, words, timeout_ms=timeout)
                print(f"{rec.site_id:14s} status={rec.status:16s} "
                      f"latency={rec.latency_ms:6d}ms reason={safe(rec.reason)}")
        finally:
            page.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
