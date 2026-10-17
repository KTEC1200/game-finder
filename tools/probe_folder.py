"""Throwaway probe #29: jidiyouxi game-body download = switch folder tab.

probe #28 proved the visible pan links belong to 修改器 posts, and that
`currentTopic.folder_list` = [{8:修改器},{10:游戏本体}] with `post_tab: 8`.
So the GAME BODY's download links are behind folder 10. Capture the request
that loads it, and the pan URLs that come back.
"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = Path(r"D:\K\deepseek\_gf_dl_probe")
PROXY = "http://127.0.0.1:6234"
URL = "https://www.jidiyouxi.com/topic/detail/20093940"
HERE = Path(__file__).parent


def main() -> None:
    out: dict = {}
    api_calls: list[dict] = []
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

        def on_resp(resp):
            u = resp.url
            if "/api/" in u:
                body = ""
                try:
                    body = resp.text()[:4000]
                except Exception:  # noqa: BLE001
                    pass
                api_calls.append({"url": u, "status": resp.status, "body": body})

        page.on("response", on_resp)
        page.goto(URL, timeout=45000, wait_until="load")
        page.wait_for_timeout(8000)

        # what folder tabs are visible?
        out["tabs"] = page.evaluate(
            """() => Array.from(document.querySelectorAll('*'))
                .filter(e => {
                    const t = (e.textContent||'').trim();
                    return (t==='游戏本体' || t==='修改器' || t==='补丁' || t==='工具')
                           && e.children.length===0;
                })
                .map(e => ({tag:e.tagName, txt:e.textContent.trim(),
                            cls:(e.className||'').toString().slice(0,80)}))
                .slice(0,12)"""
        )

        # click 游戏本体
        clicked = False
        try:
            loc = page.get_by_text("游戏本体", exact=True)
            if loc.count():
                loc.first.click(timeout=5000)
                clicked = True
                page.wait_for_timeout(7000)
        except Exception as e:  # noqa: BLE001
            out["click_err"] = str(e)[:200]
        out["clicked_game_body"] = clicked

        # after the click: what pan links are in the DOM / in appState now?
        out["pan_after"] = page.evaluate(
            """() => Array.from(document.querySelectorAll('a[href]'))
                .map(a=>a.href)
                .filter(h=>/pan\\.|magnet:|quark|123pan|lanzou|xunlei|aliyundrive/.test(h))"""
        )
        out["appstate_pan_after"] = page.evaluate(
            """() => {
                const s=document.getElementById('appState');
                const t=s?(s.textContent||''):'';
                const m=t.match(/https?:\\\\?\\/\\\\?\\/[^"\\\\\\s]*(?:pan\\.|xunlei|quark|123pan|lanzou)[^"\\\\\\s]*/g)||[];
                return Array.from(new Set(m)).slice(0,20);
            }"""
        )
        out["post_tab_after"] = page.evaluate(
            """() => {
                const s=document.getElementById('appState');
                if(!s) return null;
                const t=s.textContent||'';
                const m=t.match(/"post_tab":(\\d+)/);
                return m?m[1]:null;
            }"""
        )
        out["body_text_after"] = page.evaluate(
            "() => document.body.innerText.slice(0,2500)"
        )
        ctx.close()

    out["api_calls"] = [
        {"url": c["url"], "status": c["status"], "body_head": c["body"][:600]}
        for c in api_calls
    ]
    (HERE / "probe_folder.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("tabs:", json.dumps(out["tabs"], ensure_ascii=False)[:500])
    print("clicked:", clicked, out.get("click_err"))
    print("post_tab_after:", out["post_tab_after"])
    print("pan_after:", out["pan_after"])
    print("appstate_pan_after:", out["appstate_pan_after"])
    print("--- api calls ---")
    for c in out["api_calls"]:
        print("  ", c["status"], c["url"][:140])


if __name__ == "__main__":
    main()
