"""Throwaway probe #41: follow gamer520's /go popup and read what it contains.

probe #40 showed `a.go-downblank` opens a POPUP at /go?post_id=123857 (the main
page never navigates). Read the popup's own DOM.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = Path(r"D:\K\deepseek\_gf_e2e_probe")
PROXY = "http://127.0.0.1:6234"
HERE = Path(__file__).parent
PAN = (r"https?://[^\s\"'<>]*(?:pan\.baidu\.com|pan\.quark\.cn|pan\.xunlei\.com|"
       r"aliyundrive\.com|alipan\.com|123pan\.com|lanzou[a-z]?\.com|magnet:\?xt=)[^\s\"'<>]*")


def dump(page) -> dict:
    html = page.content()
    text = page.evaluate("() => document.body.innerText || ''")
    pans = sorted(set(re.findall(PAN, html)))
    return {
        "url": page.url, "title": page.title(),
        "pan_total": len(pans), "pan_links": pans[:15],
        "codes": sorted(set(re.findall(r"(?:提取码|密码|文件密码)\s*[:：=]?\s*([a-zA-Z0-9]{4,8})", html)))[:10],
        "text": re.sub(r"\s+", " ", text)[:1500],
        "anchors": page.evaluate(
            r"""() => Array.from(document.querySelectorAll('a[href]')).map(a=>({t:(a.innerText||'').trim().slice(0,50), h:a.href})).slice(0,40)"""),
        "body_html_len": len(html),
    }


def main() -> None:
    out: dict = {}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE), channel="chrome", executable_path=CHROME,
            headless=True, timeout=60_000, proxy={"server": PROXY},
        )
        page = ctx.new_page()
        page.goto("https://www.gamer520.com/123857.html", timeout=45000, wait_until="load")
        page.wait_for_timeout(6000)

        with page.expect_popup(timeout=25000) as pop_info:
            page.click("a.go-downblank", timeout=8000)
        pop = pop_info.value
        try:
            pop.wait_for_load_state("load", timeout=25000)
        except Exception:  # noqa: BLE001
            pass
        pop.wait_for_timeout(7000)
        out["popup_immediate"] = dump(pop)

        # some gates need a second hop or a wait; re-dump after settling
        pop.wait_for_timeout(8000)
        out["popup_settled"] = dump(pop)

        # also try direct navigation in a fresh tab (referer-less)
        p2 = ctx.new_page()
        try:
            p2.goto("https://www.gamer520.com/go?post_id=123857", timeout=40000, wait_until="load")
            p2.wait_for_timeout(8000)
            out["direct"] = dump(p2)
        except Exception as e:  # noqa: BLE001
            out["direct"] = {"error": str(e)[:160]}
        ctx.close()

    (HERE / "probe_go2.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = []
    for k in ("popup_immediate", "popup_settled", "direct"):
        d = out[k]
        lines.append(f"\n=== {k} ===")
        if "error" in d:
            lines.append("  ERROR " + d["error"])
            continue
        lines.append(f"url={d['url']}")
        lines.append(f"title={d['title']}  html_len={d['body_html_len']}  pan_total={d['pan_total']}")
        lines.append(f"codes={d['codes']}")
        for x in d["pan_links"]:
            lines.append("  PAN " + x[:150])
        lines.append("text=" + d["text"][:800])
        lines.append("anchors=" + json.dumps(d["anchors"], ensure_ascii=False)[:700])
    (HERE / "_go2.txt").write_text("\n".join(lines), encoding="utf-8")
    print("ok -> _go2.txt")
    for k in ("popup_immediate", "popup_settled", "direct"):
        d = out[k]
        if "error" in d:
            print(k, "ERR", d["error"][:90])
        else:
            print(k, "pan_total=", d["pan_total"], "title=", d["title"][:60])


if __name__ == "__main__":
    main()
