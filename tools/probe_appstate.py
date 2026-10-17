"""Throwaway probe #26: dump the values of jidiyouxi's download_* / cloud_resource keys.

probe #25 found `download_xlgame_url`, `cloud_resource`, `share_limiting`,
`resource_type`, `resource_tag` in the 538456-char #appState script. That is
almost certainly where THIS game's download links live. Dump real values.
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

        # 1. appState: is it parseable JSON? what top-level keys?
        out["appstate"] = page.evaluate(
            """() => {
                const s = document.getElementById('appState');
                if (!s) return {missing: true};
                const t = s.textContent || '';
                let parsed = null, err = null;
                try { parsed = JSON.parse(t); } catch (e) { err = String(e).slice(0,200); }
                return {len: t.length, parsed_ok: !!parsed, err,
                        head: t.slice(0,200),
                        top_keys: parsed ? Object.keys(parsed).slice(0,40) : null};
            }"""
        )

        # 2. every occurrence of the download keys with a window of raw text
        out["key_windows"] = page.evaluate(
            """() => {
                const s = document.getElementById('appState');
                const t = s ? (s.textContent||'') : '';
                const keys = ['download_xlgame_url','cloud_resource','share_limiting',
                              'resource_type','resource_tag','download_xlgame_conf'];
                const res = {};
                for (const k of keys) {
                    const hits = [];
                    let i = -1;
                    while ((i = t.indexOf('"'+k+'"', i+1)) !== -1 && hits.length < 4) {
                        hits.push(t.slice(Math.max(0,i-150), i+700));
                    }
                    res[k] = hits;
                }
                return res;
            }"""
        )

        # 3. does appState contain any pan./magnet URL at all?
        out["appstate_urls"] = page.evaluate(
            """() => {
                const s = document.getElementById('appState');
                const t = s ? (s.textContent||'') : '';
                const m = t.match(/https?:\\/\\/[^"\\\\\\s]*(?:pan\\.|quark|123pan|lanzou|aliyundrive|alipan|xunlei|pikpak|baidu|115\\.com|mega\\.nz|mediafire)[^"\\\\\\s]*/g) || [];
                return Array.from(new Set(m)).slice(0,25);
            }"""
        )
        ctx.close()
    (HERE / "probe_appstate.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("appstate:", json.dumps(out["appstate"], ensure_ascii=False)[:600])
    print("appstate_urls:", out["appstate_urls"])
    for k, hits in out["key_windows"].items():
        print(f"--- {k}: {len(hits)} hits")
        for h in hits[:2]:
            print("    ", h[:500].replace("\n", " "))


if __name__ == "__main__":
    main()
