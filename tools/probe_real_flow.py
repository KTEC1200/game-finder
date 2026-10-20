"""Run the REAL `_fetch_popup_redirect_links` against the live galgamex page.

Selector choice came from measurement (see probe_galgamex_selectors.py):
`button[data-slot='button'][data-variant='default'][data-size='sm']` matched
exactly the three resource buttons (分卷 2 / 分卷 1 / 百度网盘) and excluded the
ghost-variant 复制. This probe proves the shipped function works end to end on
the real site, not just against the fake page in the test suite.

No proxy: the local proxy (127.0.0.1:6234) is down, and the site answers 200 to
a real Chrome UA. /redirect navigations are aborted by the function itself.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from finder.models import SearchSpec, Site  # noqa: E402
from finder.pipeline import _fetch_popup_redirect_links  # noqa: E402

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = Path(r"D:\K\deepseek\_gf_galgamex_probe")
URL = "https://www.galgamex.net/game/cbe7d89e"
HERE = Path(__file__).parent
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
)
SELECTOR = "button[data-slot='button'][data-variant='default'][data-size='sm']"


def main() -> None:
    site = Site(
        id="galgamex",
        name="GalgameX",
        homepage="https://www.galgamex.net/",
        kinds=["galgame"],
        langs={"zh", "ja"},
        url_searchable=True,
        search=SearchSpec(
            mode="url",
            url_template="https://www.galgamex.net/search?q={q}",
            download_flow="popup_redirect",
            detail_open_selector="button:has-text('\u8d44\u6e90\u4e0b\u8f7d')",
            download_open_selector=SELECTOR,
        ),
    )
    extra: dict = {}
    out: dict = {}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE),
            channel="chrome",
            executable_path=CHROME,
            headless=True,
            timeout=60_000,
            user_agent=UA,
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.new_page()
        resp = page.goto(URL, timeout=45000, wait_until="load")
        out["status"] = getattr(resp, "status", None)
        page.wait_for_timeout(4500)
        try:
            downloads = _fetch_popup_redirect_links(page, site, 15000, extra)
        except Exception as exc:  # noqa: BLE001
            out["exception"] = f"{type(exc).__name__}: {exc}"[:400]
            downloads = []
        out["downloads"] = [{"kind": d.kind, "url": d.url, "label": d.label} for d in downloads]
        out["extra"] = extra
        ctx.close()

    (HERE / "probe_real_flow.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("status:", out.get("status"))
    print("exception:", out.get("exception"))
    print("clicks:", extra.get("galgamex_clicks"))
    print("errors:", extra.get("galgamex_errors"))
    print("downloads:", len(downloads))
    for d in downloads:
        print("  ", d.kind, "|", d.url[:110])
    print("wrote probe_real_flow.json")


if __name__ == "__main__":
    main()
