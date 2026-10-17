"""Throwaway probe #36: jidiyouxi tab switching measured on the LIVE DOM.

probe #34 read `#appState` (an SSR-only script tag) to detect folder changes, so
its "clicks did nothing" result was a measurement bug. Re-measure by reading the
rendered post area's text after each tab click.
"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = Path(r"D:\K\deepseek\_gf_dl_probe")
PROXY = "http://127.0.0.1:6234"
TAB = "div.flex.cursor-pointer.flex-col"
HERE = Path(__file__).parent

PAN_RE = r"https?://[^\s\"'<>]*(?:pan\.|xunlei|quark|123pan|lanzou|aliyundrive)[^\s\"'<>]*"


def dom_state(page):
    return page.evaluate(
        """() => {
            const body = document.body.innerText || '';
            const pans = Array.from(new Set(body.match(/https?:\\/\\/[^\\s"'<>]*(?:pan\\.|xunlei|quark|123pan|lanzou|aliyundrive)[^\\s"'<>]*/g) || []));
            // any visible element whose own text is a folder-ish label
            const tabs = Array.from(document.querySelectorAll('div.flex.cursor-pointer.flex-col'))
                .map(e => (e.innerText || '').trim().slice(0, 12));
            // the post content block(s)
            const posts = Array.from(document.querySelectorAll('[class*=content],[class*=post],[class*=desc]'))
                .map(e => (e.innerText || '').trim())
                .filter(t => t.length > 40 && t.length < 4000);
            return {pans: pans.slice(0, 12), pans_total: pans.length,
                    tabs: tabs, post_count: posts.length,
                    post_head: posts.length ? posts[0].slice(0, 220) : null};
        }"""
    )


def main() -> None:
    out: dict = {}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE), channel="chrome", executable_path=CHROME,
            headless=True, timeout=60_000, proxy={"server": PROXY},
        )
        page = ctx.new_page()
        page.goto("https://www.jidiyouxi.com/topic/detail/171085167", timeout=45000,
                  wait_until="load")
        page.wait_for_timeout(8000)
        out["initial"] = dom_state(page)

        loc = page.locator(TAB)
        n = loc.count()
        out["tab_count"] = n
        results = []
        for i in range(n):
            try:
                loc.nth(i).click(timeout=5000)
                page.wait_for_timeout(4500)
                results.append({"i": i, "state": dom_state(page)})
            except Exception as e:  # noqa: BLE001
                results.append({"i": i, "err": str(e)[:140]})
        out["clicks"] = results
        ctx.close()

    (HERE / "probe_folder5.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    lines = [f"tab_count={n}"]
    lines.append("initial=" + json.dumps(out["initial"], ensure_ascii=False)[:700])
    for r in results:
        lines.append(f"{r.get('i')} -> " + json.dumps(r.get("state", r.get("err")), ensure_ascii=False)[:700])
    (HERE / "_folder5.txt").write_text("\n".join(lines), encoding="utf-8")
    print("ok, wrote _folder5.txt")


if __name__ == "__main__":
    main()
