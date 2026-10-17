"""Throwaway probe #33: click jidiyouxi's folder tabs by DOM order, dump each folder.

probe #32 found `folder_list` = [7, 6, 8, 10] and that the topic detail comes from
`POST https://api2.jidiyouxi.com/topic/detail` (websign-signed, not replayable).
So the extractor must click tabs. Find the real tab elements and read each
folder's posts (looking for the game-body pan link).
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


def dump_state(page):
    return page.evaluate(
        """() => {
            const s=document.getElementById('appState');
            const t=s?(s.textContent||''):'';
            const sn=t.match(/"selectedNav":"?(\\d+)"?/);
            const pt=t.match(/"post_tab":(\\d+)/);
            // pan/magnet links anywhere in appState text
            const pans=Array.from(new Set((t.match(/https?:[^"\\s]*(?:pan\\.|xunlei|quark|123pan|lanzou|aliyundrive)[^"\\s]*/g)||[])));
            return {selectedNav: sn?sn[1]:null, post_tab: pt?pt[1]:null,
                    pans: pans.slice(0,12), pans_total: pans.length};
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
        page.goto(URL, timeout=45000, wait_until="load")
        page.wait_for_timeout(8000)

        # find candidate tab elements: leaf nodes whose text is short and contains 本体/mod/攻略/修改
        out["tab_candidates"] = page.evaluate(
            """() => {
                const keys=['本体','攻略','修改器','mod','MOD','补丁','存档','工具','游戏'];
                return Array.from(document.querySelectorAll('div,span,a,li,p'))
                  .filter(e=>e.children.length===0)
                  .map(e=>({t:(e.textContent||'').trim(), cls:(e.className||'').toString().slice(0,80)}))
                  .filter(o=>o.t.length>0 && o.t.length<12 && keys.some(k=>o.t.includes(k)))
                  .filter((v,i,a)=>a.findIndex(x=>x.t===v.t)===i);
            }"""
        )

        # click by index over the leaf nodes matching tab texts, in DOM order
        results = []
        n = page.evaluate(
            """() => {
                const keys=['本体','攻略','修改器','mod','MOD','补丁','存档','工具'];
                return Array.from(document.querySelectorAll('div,span,a,li,p'))
                  .filter(e=>e.children.length===0)
                  .map(e=>(e.textContent||'').trim())
                  .filter(t=>t.length>0 && t.length<12 && keys.some(k=>t.includes(k)))
                  .filter((v,i,a)=>a.indexOf(v)===i).length;
            }"""
        )
        for i in range(n):
            label = page.evaluate(
                """(i) => {
                    const keys=['本体','攻略','修改器','mod','MOD','补丁','存档','工具'];
                    const els=Array.from(document.querySelectorAll('div,span,a,li,p'))
                      .filter(e=>e.children.length===0)
                      .map(e=>(e.textContent||'').trim())
                      .filter(t=>t.length>0 && t.length<12 && keys.some(k=>t.includes(k)))
                      .filter((v,j,a)=>a.indexOf(v)===j);
                    return els[i];
                }""",
                i,
            )
            try:
                el = page.evaluate_handle(
                    """(i) => {
                        const keys=['本体','攻略','修改器','mod','MOD','补丁','存档','工具'];
                        const els=Array.from(document.querySelectorAll('div,span,a,li,p'))
                          .filter(e=>e.children.length===0)
                          .map(e=>(e.textContent||'').trim())
                          .filter(t=>t.length>0 && t.length<12 && keys.some(k=>t.includes(k)))
                          .filter((v,j,a)=>a.indexOf(v)===j);
                        return els[i];
                    }""",
                    i,
                ).as_element()
                if el is None:
                    results.append({"i": i, "label": label, "err": "no element"})
                    continue
                el.click(timeout=4000)
                page.wait_for_timeout(4500)
                st = dump_state(page)
                results.append({"i": i, "label": label, "state": st})
            except Exception as e:  # noqa: BLE001
                results.append({"i": i, "label": label, "err": str(e)[:140]})
        out["clicks"] = results
        ctx.close()

    (HERE / "probe_folder3.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("candidates:", json.dumps(out["tab_candidates"], ensure_ascii=False)[:600])
    print("--- clicks ---")
    for r in out["clicks"]:
        print(" ", r.get("i"), r.get("label"), "->", json.dumps(r.get("state", r.get("err")), ensure_ascii=False)[:400])


if __name__ == "__main__":
    main()
