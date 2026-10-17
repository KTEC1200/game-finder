"""Throwaway probe #11: true-direct vs system-proxy vs explicit proxy.

probe #10 reported the P2 sites reachable, but Chrome inherits the WinINET
system proxy (127.0.0.1:6234, ProxyEnable=1) by DEFAULT. So "reachable"
may have been proxy-assisted, not direct. That distinction decides the
whole proxy design in the spec:

  if true-direct works  -> default to NO proxy (system proxy left alone)
  if only proxy works   -> default to the system proxy, not a hardcoded 7890

Three configurations per site:
  A --no-proxy-server        (genuinely direct)
  B (no proxy arg)           (Chrome default: system proxy 6234)
  C --proxy-server=6234      (explicit)
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
BASE = Path(r"D:\K\deepseek\_gf_proxy_probe")

SITES = {
    "jidiyouxi": "https://www.jidiyouxi.com/",
    "gamer520": "https://www.gamer520.com/",
    "catcat": "https://catcat.cloud/",
    "anime-sharing": "https://www.anime-sharing.com/",
    "nyaa": "https://sukebei.nyaa.si/",
}

CONFIGS = {
    "A_true_direct": {"args": ["--no-proxy-server"]},
    "B_system_default": {},
    "C_explicit_6234": {"proxy": {"server": "http://127.0.0.1:6234"}},
}


def run(cfg_name: str, cfg: dict) -> list[dict]:
    profile = BASE / cfg_name
    profile.mkdir(parents=True, exist_ok=True)
    out = []
    with sync_playwright() as p:
        kwargs = dict(
            user_data_dir=str(profile),
            channel="chrome",
            executable_path=CHROME,
            headless=True,
            timeout=60_000,
        )
        kwargs.update(cfg)
        ctx = p.chromium.launch_persistent_context(**kwargs)
        for site_id, url in SITES.items():
            page = ctx.new_page()
            t0 = time.time()
            entry = {"cfg": cfg_name, "site": site_id}
            try:
                resp = page.goto(url, timeout=25_000, wait_until="domcontentloaded")
                entry["status"] = resp.status if resp else None
                entry["ok"] = bool(resp and resp.status < 400)
            except Exception as exc:  # noqa: BLE001
                entry["ok"] = False
                entry["error"] = type(exc).__name__
            entry["ms"] = int((time.time() - t0) * 1000)
            out.append(entry)
            page.close()
        ctx.close()
    return out


if __name__ == "__main__":
    results = []
    for name, cfg in CONFIGS.items():
        try:
            results.extend(run(name, cfg))
        except Exception as exc:  # noqa: BLE001
            results.append({"cfg": name, "fatal": f"{type(exc).__name__}: {str(exc)[:200]}"})
    dest = Path(__file__).with_name("probe_proxy_matrix.json")
    dest.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    for r in results:
        if "fatal" in r:
            print(f"{r['cfg']}: FATAL {r['fatal']}")
            continue
        flag = "OK  " if r.get("ok") else "FAIL"
        print(f"{r['cfg']:<16} {flag} {r['site']:<14} status={r.get('status')} {r.get('ms')}ms {r.get('error','')}")
    print(f"[wrote {dest}]")
