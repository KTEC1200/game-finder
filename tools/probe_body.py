"""Throwaway probe #37: what does jidiyouxi's 本体 tab actually render?

probe #36: clicking the mod tab DID change the DOM (mod post titles appeared),
so tabs work and the earlier "no-op" reading was a measurement artifact. But the
本体 folder (default for 剑星) rendered 0 pan links in innerText. Dump the real
text/HTML of the content area to see where the body download link lives.
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


def main() -> None:
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE), channel="chrome", executable_path=CHROME,
            headless=True, timeout=60_000, proxy={"server": PROXY},
        )
        page = ctx.new_page()
        page.goto("https://www.jidiyouxi.com/topic/detail/171085167", timeout=45000,
                  wait_until="load")
        page.wait_for_timeout(9000)

        # click the 本体 tab (text-based, robust)
        clicked = None
        try:
            t = page.get_by_text("本体", exact=True)
            if t.count():
                t.first.click(timeout=5000)
                clicked = "本体"
                page.wait_for_timeout(7000)
        except Exception as e:  # noqa: BLE001
            clicked = f"err {e}"[:100]

        text = page.evaluate("() => document.body.innerText || ''")
        html = page.content()
        # pan links anywhere in the raw HTML (not just visible text)
        pans_html = page.evaluate(
            r"""() => {
                const h = document.documentElement.outerHTML;
                return Array.from(new Set(h.match(/https?:[^\s"'<>]*(?:pan\.|xunlei|quark|123pan|lanzou)[^\s"'<>]*/g) || [])).slice(0, 15);
            }"""
        )
        anchors = page.evaluate(
            r"""() => Array.from(document.querySelectorAll('a[href]')).map(a=>a.href)
                .filter(h => /pan\.|xunlei|quark|123pan|lanzou|magnet:/.test(h)).slice(0,15)"""
        )
        ctx.close()

    (HERE / "_body_text.txt").write_text(text, encoding="utf-8")
    (HERE / "_body_after_tab.html").write_text(html, encoding="utf-8")
    (HERE / "probe_body.json").write_text(json.dumps(
        {"clicked": clicked, "pans_html": pans_html, "anchors": anchors,
         "text_len": len(text)}, indent=2, ensure_ascii=False), encoding="utf-8")
    print("clicked:", clicked)
    print("text_len:", len(text))
    print("pans_html:", len(pans_html))
    for x in pans_html[:8]:
        print("   ", x[:150])
    print("anchors:", len(anchors))


if __name__ == "__main__":
    main()
