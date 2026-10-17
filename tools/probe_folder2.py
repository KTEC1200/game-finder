"""Throwaway probe #32: does jidiyouxi serve 游戏本体 (folder 10) links at all?

probe #29-#31 established: this topic renders only the 修改器 folder (8); the
appState holds trainer pan links but no game-body link, and the only other
download affordance is the Xunlei-assistant ad. Hypothesis: 游戏本体 posts are
fetched on demand. Test on a hot topic (剑星) and capture every XHR.
"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = Path(r"D:\K\deepseek\_gf_dl_probe")
PROXY = "http://127.0.0.1:6234"
URL = "https://www.jidiyouxi.com/topic/detail/171085167"  # 剑星
HERE = Path(__file__).parent


def main() -> None:
    out: dict = {}
    xhr: list[dict] = []
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

        def on_resp(r):
            if r.request.resource_type in ("xhr", "fetch"):
                body = ""
                try:
                    body = r.text()[:2500]
                except Exception:  # noqa: BLE001
                    pass
                xhr.append({"url": r.url, "status": r.status, "method": r.request.method,
                            "post": (r.request.post_data or "")[:300], "body": body})

        page.on("response", on_resp)
        page.goto(URL, timeout=45000, wait_until="load")
        page.wait_for_timeout(9000)

        # folder tabs present?
        out["tabs"] = page.evaluate(
            """() => Array.from(document.querySelectorAll('div,span,a,li'))
                .filter(e => e.children.length===0)
                .map(e => (e.textContent||'').trim())
                .filter(t => ['游戏本体','修改器','补丁','工具','全部','存档'].includes(t))
                .filter((v,i,a)=>a.indexOf(v)===i)"""
        )
        # appState folder_list + selectedNav
        out["folder_info"] = page.evaluate(
            """() => {
                const s=document.getElementById('appState');
                if(!s) return null;
                const t=s.textContent||'';
                const fl=t.match(/"folder_list":(\\[.*?\\])/);
                const sn=t.match(/"selectedNav":"(\\d+)"/);
                const pt=t.match(/"post_tab":(\\d+)/);
                return {folder_list: fl?fl[1]:null, selectedNav: sn?sn[1]:null, post_tab: pt?pt[1]:null};
            }"""
        )
        # click each tab and watch what happens
        results = []
        for label in ("游戏本体", "补丁", "工具", "存档"):
            try:
                loc = page.get_by_text(label, exact=True)
                if loc.count() == 0:
                    results.append({"label": label, "found": False})
                    continue
                before = len(xhr)
                loc.first.click(timeout=4000)
                page.wait_for_timeout(5000)
                pans = page.evaluate(
                    """() => Array.from(document.querySelectorAll('a[href]'))
                        .map(a=>a.href)
                        .filter(h=>/pan\\.|magnet:|quark|123pan|lanzou|xunlei|aliyundrive/.test(h))"""
                )
                results.append({"label": label, "found": True, "new_xhr": len(xhr) - before,
                                "pan_links": pans[:8]})
            except Exception as e:  # noqa: BLE001
                results.append({"label": label, "error": str(e)[:120]})
        out["tab_clicks"] = results

        # final: all pan links in appState for THIS topic
        out["appstate_pans"] = page.evaluate(
            """() => {
                const s=document.getElementById('appState');
                const t=s?(s.textContent||''):'';
                const m=t.match(/https?:\\\\?\\/\\\\?\\/[^"\\\\\\s]*(?:pan\\.|xunlei|quark|123pan|lanzou)[^"\\\\\\s]*/g)||[];
                return Array.from(new Set(m)).slice(0,25);
            }"""
        )
        ctx.close()

    out["xhr"] = [{"url": x["url"][:160], "status": x["status"], "method": x["method"],
                   "post": x["post"], "body_head": x["body"][:300]} for x in xhr]
    (HERE / "probe_folder2.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("tabs:", out["tabs"])
    print("folder_info:", json.dumps(out["folder_info"], ensure_ascii=False))
    print("tab_clicks:", json.dumps(results, ensure_ascii=False)[:900])
    print("appstate_pans:", out["appstate_pans"])
    print("--- xhr ---")
    for x in out["xhr"]:
        print("  ", x["status"], x["method"], x["url"][:130])


if __name__ == "__main__":
    main()
