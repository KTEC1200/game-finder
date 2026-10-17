"""Throwaway probe #15: drive jidiyouxi's real search box; diagnose catcat.

probe #14 findings:
  jidiyouxi: exactly 1 visible input, no name/id, placeholder
             "游戏/mod/修改器", Tailwind classes -> real search box
  catcat:    0 inputs, body only 18794 bytes, 11 scripts -> likely SPA
             that never finished rendering, or search is elsewhere

Tests:
  T1 jidiyouxi: fill the single input, press Enter, count result links
  T2 catcat: wait much longer + capture network requests to see if an API
     is used, and dump a text preview of the page
"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = Path(r"D:\K\deepseek\_gf_form_probe3")
PROXY = "http://127.0.0.1:6234"
QUERY = "AI"


def launch(p):
    return p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE),
        channel="chrome",
        executable_path=CHROME,
        headless=True,
        timeout=60_000,
        proxy={"server": PROXY},
    )


def t1_jidiyouxi(ctx) -> dict:
    out: dict = {}
    page = ctx.new_page()
    page.goto("https://www.jidiyouxi.com/", timeout=45000, wait_until="load")
    page.wait_for_timeout(5000)
    inp = page.locator("input").first
    out["count_inputs"] = page.locator("input").count()
    inp.click()
    inp.fill(QUERY)
    page.wait_for_timeout(800)
    out["typed_value"] = inp.input_value()
    inp.press("Enter")
    page.wait_for_timeout(6000)
    out["after_url"] = page.url
    out["after_title"] = (page.title() or "")[:90]
    # broad link harvest, same-domain only
    links = page.eval_on_selector_all(
        "a[href]", "els => els.map(e => e.href)"
    )
    from urllib.parse import urlparse

    same = [
        l for l in links
        if l.startswith("http") and "jidiyouxi.com" in urlparse(l).netloc
        and not any(k in l for k in ("/tag/", "/page/", "javascript", "#", "login"))
    ]
    out["total_links"] = len(links)
    out["same_domain_links"] = len(same)
    out["sample"] = same[:8]
    page.close()
    return out


def t2_catcat(ctx) -> dict:
    out: dict = {}
    page = ctx.new_page()
    reqs: list[str] = []
    page.on("request", lambda r: reqs.append(r.url))
    page.goto("https://catcat.cloud/", timeout=45000, wait_until="load")
    page.wait_for_timeout(15000)  # long settle for SPA
    out["final_url"] = page.url
    out["title"] = (page.title() or "")[:90]
    out["inputs_now"] = page.locator("input").count()
    out["buttons"] = page.locator("button").count()
    try:
        out["text_preview"] = page.inner_text("body")[:600]
    except Exception as exc:  # noqa: BLE001
        out["text_preview"] = f"<{type(exc).__name__}>"
    out["n_requests"] = len(reqs)
    out["api_like"] = [u for u in reqs if "/api" in u or "search" in u.lower()][:10]
    out["all_requests_sample"] = reqs[:15]
    page.close()
    return out


if __name__ == "__main__":
    results = {}
    with sync_playwright() as p:
        ctx = launch(p)
        for name, fn in (("jidiyouxi", t1_jidiyouxi), ("catcat", t2_catcat)):
            try:
                results[name] = fn(ctx)
            except Exception as exc:  # noqa: BLE001
                results[name] = {"fatal": f"{type(exc).__name__}: {str(exc)[:250]}"}
        ctx.close()
    dest = Path(__file__).with_name("probe_forms3.json")
    dest.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(results, indent=2, ensure_ascii=False)[:4000])
    print(f"[wrote {dest}]")
