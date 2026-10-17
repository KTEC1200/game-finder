"""Throwaway probe #20: what's on jidiyouxi's /post/detail/ download page?

probe #19 showed the detail page's 下载 button opens a NEW TAB at
https://www.jidiyouxi.com/post/detail/<id>. That post page is where the pan
links should live. Confirm: which host, what anchor shapes, any 提取码 text.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = Path(r"D:\K\deepseek\_gf_dl_probe")
PROXY = "http://127.0.0.1:6234"
POST = "https://www.jidiyouxi.com/post/detail/3054647172"


def main() -> None:
    out: dict = {"url": POST}
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
        page.goto(POST, timeout=45000, wait_until="load")
        page.wait_for_timeout(6000)
        page.mouse.wheel(0, 8000)
        page.wait_for_timeout(3000)

        out["title"] = page.title()
        out["all_anchors"] = page.evaluate(
            """() => Array.from(document.querySelectorAll('a[href]'))
                .map(a=>({t:(a.textContent||'').trim().slice(0,40), h:a.href}))
                .filter(x=>x.h && !/^javascript/.test(x.h)).slice(0,60)"""
        )
        out["body_text"] = page.evaluate(
            """() => (document.body.innerText||'').slice(0, 3000)"""
        )
        # anything that looks like a pan share link or extraction code
        txt = out["body_text"]
        out["pan_matches"] = re.findall(
            r"https?://[^\s\u4e00-\u9fff]*(?:pan\.|quark|123pan|lanzou|aliyundrive|"
            r"alipan|xunlei|pikpak|baidu|115|mypikpak)[^\s\u4e00-\u9fff]*",
            txt,
        )[:20]
        out["code_matches"] = re.findall(r"[提取密码码]{1,2}[:：]?\s*([A-Za-z0-9]{4,8})", txt)[:10]
        ctx.close()
    dest = Path(__file__).with_name("probe_post.json")
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[wrote {dest}]")
    print("TITLE:", out["title"])
    print("PAN:", out["pan_matches"])
    print("CODE:", out["code_matches"])


if __name__ == "__main__":
    main()
