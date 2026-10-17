"""Throwaway probe #40: gamer520's /go?post_id= download gate.

probe #39 found the real control: <a class="go-downblank" href="/go?post_id=123857">
立即下载</a>. Resolve it and see what it yields (pan list page? JS? direct?).
Also confirm whether it needs login, and whether the 文件密码 is exposed.
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
GO = "https://www.gamer520.com/go?post_id=123857"


def main() -> None:
    out: dict = {}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE), channel="chrome", executable_path=CHROME,
            headless=True, timeout=60_000, proxy={"server": PROXY},
        )
        page = ctx.new_page()

        # click the real control from the detail page (more faithful than goto)
        page.goto("https://www.gamer520.com/123857.html", timeout=45000, wait_until="load")
        page.wait_for_timeout(6000)
        out["pre_url"] = page.url
        navs: list[str] = []
        page.on("popup", lambda pg: navs.append("POPUP " + pg.url))
        try:
            with page.expect_navigation(timeout=25000):
                page.click("a.go-downblank", timeout=8000)
            out["click"] = "navigated"
        except Exception as e:  # noqa: BLE001
            out["click"] = f"no-nav: {str(e)[:100]}"
        page.wait_for_timeout(6000)
        out["after_url"] = page.url
        out["popups"] = navs
        out["after_title"] = page.title()

        html = page.content()
        text = page.evaluate("() => document.body.innerText || ''")
        pans = sorted(set(re.findall(
            r"https?://[^\s\"'<>]*(?:pan\.baidu\.com|pan\.quark\.cn|pan\.xunlei\.com|"
            r"aliyundrive\.com|alipan\.com|123pan\.com|lanzou[a-z]?\.com)[^\s\"'<>]*", html)))
        out["pan_links"] = pans[:12]
        out["pan_total"] = len(pans)
        out["codes"] = sorted(set(re.findall(r"(?:提取码|密码|文件密码)\s*[:：=]?\s*([a-zA-Z0-9]{4,8})", html)))[:8]
        out["text_head"] = re.sub(r"\s+", " ", text)[:900]
        out["anchors"] = page.evaluate(
            r"""() => Array.from(document.querySelectorAll('a[href]')).map(a=>({t:(a.innerText||'').trim().slice(0,40), h:a.href}))
                 .filter(o => /pan\.|quark|xunlei|baidu|123pan|lanzou|magnet:/.test(o.h)).slice(0,12)"""
        )
        out["buttons"] = page.evaluate(
            r"""() => Array.from(document.querySelectorAll('a,button')).map(e=>({t:(e.innerText||'').trim().slice(0,40), cls:(e.className||'').toString().slice(0,60)}))
                 .filter(o => /下载|获取|复制|查看|网盘/.test(o.t)).slice(0,15)"""
        )
        ctx.close()

    (HERE / "probe_go.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [f"pre_url={out['pre_url']}", f"click={out['click']}",
             f"after_url={out['after_url']}", f"after_title={out['after_title']}",
             f"popups={out['popups']}", f"pan_total={out['pan_total']}",
             f"codes={out['codes']}"]
    for x in out["pan_links"]:
        lines.append("  PAN " + x[:140])
    lines.append("anchors=" + json.dumps(out["anchors"], ensure_ascii=False)[:600])
    lines.append("buttons=" + json.dumps(out["buttons"], ensure_ascii=False)[:600])
    lines.append("text_head=" + out["text_head"])
    (HERE / "_go.txt").write_text("\n".join(lines), encoding="utf-8")
    print("ok -> _go.txt")
    print("after_url:", out["after_url"][:120])
    print("pan_total:", out["pan_total"], "codes:", out["codes"])


if __name__ == "__main__":
    main()
