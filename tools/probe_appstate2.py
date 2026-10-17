"""Throwaway probe #27: save jidiyouxi's appState + topic record for offline grep.

probe #26 killed the `download_xlgame_url` hypothesis (it's a Xunlei client
installer ad, not the game). The topic's own download link is still unlocated.
Save the full appState JSON to disk and pull out the topic detail object so the
link field can be identified by inspection rather than guesswork.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = Path(r"D:\K\deepseek\_gf_dl_probe")
PROXY = "http://127.0.0.1:6234"
URL = "https://www.jidiyouxi.com/topic/detail/20093940"
HERE = Path(__file__).parent


def main() -> None:
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE),
            channel="chrome",
            executable_path=CHROME,
            headless=True,
            timeout=60_000,
            proxy={"server": PROXY},
        )
        page = ctx.new_page()
        page.goto(URL, timeout=45000, wait_until="load")
        page.wait_for_timeout(8000)
        raw = page.evaluate(
            "() => { const s=document.getElementById('appState'); return s ? s.textContent : ''; }"
        )
        # also grab the topic detail's visible intro + any 下载 button html
        out_html = page.evaluate(
            """() => {
                const btns = Array.from(document.querySelectorAll('button,div,a'))
                    .filter(e => /^\\s*下载\\s*$/.test(e.textContent||''))
                    .map(e => ({tag:e.tagName, cls:(e.className||'').toString().slice(0,120),
                                outer:e.outerHTML.slice(0,400)}));
                return btns.slice(0,5);
            }"""
        )
        ctx.close()

    (HERE / "_appstate_raw.js").write_text(raw, encoding="utf-8")
    payload = raw.split("=", 1)[1] if "=" in raw else raw
    data = json.loads(payload)
    (HERE / "_appstate.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    report = {"top_keys": list(data.keys()), "download_buttons": out_html}
    # find the topic record
    for k, v in data.items():
        if isinstance(v, dict) and "topic" in str(v.keys()).lower():
            report.setdefault("topicish", {})[k] = list(v.keys())[:40]
    # any key anywhere whose value looks like a URL list
    urlish = []
    for k, v in data.items():
        if isinstance(v, dict):
            for k2, v2 in v.items():
                if isinstance(v2, (list, str)) and re.search(r"down|link|pan|url|share", k2, re.I):
                    urlish.append((k, k2, type(v2).__name__))
    report["urlish"] = urlish[:40]
    (HERE / "probe_appstate2.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("top_keys:", report["top_keys"])
    print("urlish:", urlish[:40])
    print("download_buttons:", len(out_html))
    for b in out_html:
        print("  ", b["tag"], b["cls"][:70])


if __name__ == "__main__":
    main()
