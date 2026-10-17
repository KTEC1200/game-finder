"""Throwaway probe #13: discover real search mechanics for the P2 sites.

probe #12 showed:
  gamer520  ?s=AI  -> 68 result links        (URL mode works)
  jidiyouxi ?s=AI  -> 0 links (homepage)     (URL mode FAILS)
  catcat    ?s=AI  -> 0 links (homepage)     (URL mode FAILS)

So P2's three sites do NOT share one mode. Before writing the plan I need
the actual mechanism for the two failures, otherwise the adapter tasks
would be speculation.

For each failing site:
  1. enumerate every <form> (action, method) and its inputs
  2. enumerate candidate search inputs with heuristics
  3. actually type + submit, then count result links
  4. dump a real result link so detail-extraction work has a target
"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = Path(r"D:\K\deepseek\_gf_form_probe")
PROXY = "http://127.0.0.1:6234"
QUERY = "AI"

SITES = {
    "jidiyouxi": "https://www.jidiyouxi.com/",
    "catcat": "https://catcat.cloud/",
}


def launch(p):
    return p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE),
        channel="chrome",
        executable_path=CHROME,
        headless=True,
        timeout=60_000,
        proxy={"server": PROXY},
    )


def describe_forms(page) -> list[dict]:
    return page.evaluate(
        """() => Array.from(document.querySelectorAll('form')).map(f => ({
            action: f.getAttribute('action'),
            method: (f.getAttribute('method')||'get').toLowerCase(),
            inputs: Array.from(f.querySelectorAll('input,select,textarea')).map(i => ({
                tag: i.tagName.toLowerCase(),
                type: i.getAttribute('type'),
                name: i.getAttribute('name'),
                id: i.getAttribute('id'),
                placeholder: i.getAttribute('placeholder'),
                visible: !!(i.offsetWidth||i.offsetHeight),
            })),
        }))"""
    )


def describe_inputs(page) -> list[dict]:
    return page.evaluate(
        """() => Array.from(document.querySelectorAll('input')).map(i => ({
            type: i.getAttribute('type'),
            name: i.getAttribute('name'),
            id: i.getAttribute('id'),
            placeholder: i.getAttribute('placeholder'),
            cls: (i.getAttribute('class')||'').slice(0,60),
            visible: !!(i.offsetWidth||i.offsetHeight),
        })).filter(i => i.visible)"""
    )


def count_results(page) -> tuple[int, list[str]]:
    links = page.eval_on_selector_all(
        "article a[href], .post a[href], h2 a[href], h3 a[href], "
        ".entry-title a[href], .item a[href], .card a[href], .list a[href], "
        ".search-result a[href], main a[href]",
        "els => els.map(e => e.href)",
    )
    return len(links), links[:5]


def probe_form(page, url: str) -> dict:
    out: dict = {"url": url}
    page.goto(url, timeout=40000, wait_until="domcontentloaded")
    out["title"] = (page.title() or "")[:80]
    out["forms"] = describe_forms(page)
    out["visible_inputs"] = describe_inputs(page)

    # try heuristic selectors in priority order
    selectors = [
        "input[type=search]",
        "input[name*=s i]", "input[name*=q i]", "input[name*=kw i]",
        "input[name*=key i]", "input[id*=search i]", "input[id*=kw i]",
        "input[placeholder*=搜索]", "input[placeholder*=search i]",
        "input[type=text]",
    ]
    chosen = None
    for sel in selectors:
        loc = page.locator(sel)
        n = loc.count()
        for i in range(n):
            el = loc.nth(i)
            try:
                if el.is_visible():
                    chosen = (sel, i)
                    break
            except Exception:  # noqa: BLE001
                continue
        if chosen:
            break

    if not chosen:
        out["form_search"] = "no visible input found"
        return out

    sel, idx = chosen
    out["chosen_selector"] = sel
    try:
        el = page.locator(sel).nth(idx)
        el.click()
        el.fill(QUERY)
        el.press("Enter")
        page.wait_for_load_state("domcontentloaded", timeout=25000)
        page.wait_for_timeout(2500)
        out["after_submit_url"] = page.url
        out["after_submit_title"] = (page.title() or "")[:80]
        n, sample = count_results(page)
        out["result_links"] = n
        out["sample"] = sample
    except Exception as exc:  # noqa: BLE001
        out["form_search"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    return out


if __name__ == "__main__":
    results = {}
    with sync_playwright() as p:
        ctx = launch(p)
        for site_id, url in SITES.items():
            page = ctx.new_page()
            try:
                results[site_id] = probe_form(page, url)
            except Exception as exc:  # noqa: BLE001
                results[site_id] = {"fatal": f"{type(exc).__name__}: {str(exc)[:200]}"}
            page.close()
        ctx.close()
    dest = Path(__file__).with_name("probe_forms.json")
    dest.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    for sid, r in results.items():
        print(f"--- {sid} ---")
        print(" title:", r.get("title"))
        print(" forms:", len(r.get("forms", [])))
        for f in r.get("forms", [])[:3]:
            print("   action=", f.get("action"), "method=", f.get("method"))
            print("   inputs=", [(i["type"], i["name"], i["id"], i["placeholder"]) for i in f["inputs"]][:6])
        print(" chosen:", r.get("chosen_selector"))
        print(" after :", r.get("after_submit_url"))
        print(" links :", r.get("result_links"), r.get("sample"))
    print(f"[wrote {dest}]")
