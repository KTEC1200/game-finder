"""Throwaway probe #34: jidiyouxi folder tab bar — click each tab, dump posts.

probe #33 showed the real tab bar nodes carry class
`flex cursor-pointer flex-col items-center whitespace-nowrap pb-[2px] text-base f...`.
Click each by nth and read back selectedNav + the pan links in appState.
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


def state(page):
    return page.evaluate(
        """() => {
            const s=document.getElementById('appState');
            const t=s?(s.textContent||''):'';
            const sn=t.match(/"selectedNav":"?(\\d+)"?/);
            const pt=t.match(/"post_tab":(\\d+)/);
            const pans=Array.from(new Set((t.match(/https?:[^"\\s]*(?:pan\\.|xunlei|quark|123pan|lanzou|aliyundrive)[^"\\s]*/g)||[])));
            // visible text of the post area
            const body=(document.body.innerText||'');
            return {selectedNav: sn?sn[1]:null, post_tab: pt?pt[1]:null,
                    pans_total: pans.length, pans: pans.slice(0,10),
                    has_game_body_word: body.includes('游戏本体'),
                    pan_word_count: (body.match(/网盘|下载链接|pan\\./g)||[]).length};
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

        loc = page.locator(TAB)
        n = loc.count()
        out["tab_count"] = n
        out["tab_texts"] = [loc.nth(i).inner_text().strip()[:20] for i in range(n)]
        out["state_initial"] = state(page)

        results = []
        for i in range(n):
            try:
                loc.nth(i).click(timeout=5000)
                page.wait_for_timeout(4500)
                results.append({"i": i, "state": state(page)})
            except Exception as e:  # noqa: BLE001
                results.append({"i": i, "err": str(e)[:140]})
        out["clicks"] = results
        ctx.close()

    (HERE / "probe_folder4.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("tab_count:", n)
    print("tab_texts:", json.dumps(out["tab_texts"], ensure_ascii=False))
    print("initial:", json.dumps(out["state_initial"], ensure_ascii=False))
    for r in results:
        print(" ", r.get("i"), "->", json.dumps(r.get("state", r.get("err")), ensure_ascii=False)[:400])


if __name__ == "__main__":
    main()
