"""Throwaway probe #7: does a DEDICATED app profile persist logins?

Established (probes #2-#6) on this machine, Chrome 155.0.8059.80:
  - real default profile  : cannot be driven at all (playwright timeout;
                            --remote-debugging-port never comes up) -> banned
  - copy of real profile  : launches, but Chrome WIPES its cookies on
                            first launch (224 -> 0), so logins do NOT carry
  => "reuse the user's logged-in Chrome" is IMPOSSIBLE here.

Replacement design: the app owns a DEDICATED profile at a non-default
path. The user logs into sites ONCE in that browser; logins persist there.
This probe proves the persistence property (the whole design rests on it),
plus that the proxy path works.

Tests:
  T1 set a cookie in a dedicated profile, close, relaunch -> cookie survives?
  T2 same profile, second/third relaunch -> still survives (no wipe)?
  T3 localStorage survives too (some sites auth via localStorage)?
  T4 local proxy 127.0.0.1:7890 reachable at all?
"""

from __future__ import annotations

import json
import socket
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
APP_PROFILE = Path(r"D:\K\deepseek\_gf_dedicated_profile")
PROXY = "http://127.0.0.1:7890"
PROXY_HOST, PROXY_PORT = "127.0.0.1", 7890


def open_ctx(p, extra_args: list[str] | None = None):
    return p.chromium.launch_persistent_context(
        user_data_dir=str(APP_PROFILE),
        channel="chrome",
        executable_path=CHROME,
        headless=True,
        timeout=60_000,
        args=extra_args or [],
    )


def probe_persistence() -> str:
    if APP_PROFILE.exists():
        import shutil
        shutil.rmtree(APP_PROFILE, ignore_errors=True)
    APP_PROFILE.mkdir(parents=True, exist_ok=True)
    log: list[str] = []

    # --- launch 1: write a cookie + localStorage ---
    with sync_playwright() as p:
        ctx = open_ctx(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://example.com", timeout=25000)
        ctx.add_cookies([
            {
                "name": "gf_test",
                "value": "persist_me",
                "domain": "example.com",
                "path": "/",
            }
        ])
        page.evaluate("localStorage.setItem('gf_ls', 'ls_persist_me')")
        n1 = len(ctx.cookies())
        ctx.close()
    log.append(f"launch1: wrote cookie, cookies now={n1}")

    time.sleep(1)

    # --- launch 2: does it survive? ---
    with sync_playwright() as p:
        ctx = open_ctx(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://example.com", timeout=25000)
        cookies = {c["name"]: c["value"] for c in ctx.cookies()}
        ls = page.evaluate("localStorage.getItem('gf_ls')")
        ctx.close()
    log.append(f"launch2: cookies={cookies} localStorage={ls!r}")

    time.sleep(1)

    # --- launch 3: still there (no delayed wipe)? ---
    with sync_playwright() as p:
        ctx = open_ctx(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://example.com", timeout=25000)
        cookies3 = {c["name"]: c["value"] for c in ctx.cookies()}
        ctx.close()
    log.append(f"launch3: cookies={cookies3}")

    ok = cookies.get("gf_test") == "persist_me" and cookies3.get("gf_test") == "persist_me"
    log.append(f"VERDICT: dedicated-profile persistence {'WORKS' if ok else 'BROKEN'}")
    return " | ".join(log)


def probe_proxy_port() -> str:
    try:
        with socket.create_connection((PROXY_HOST, PROXY_PORT), timeout=3):
            return f"proxy {PROXY}: port OPEN"
    except Exception as exc:  # noqa: BLE001
        return f"proxy {PROXY}: NOT reachable ({type(exc).__name__})"


def probe_proxy_browse() -> str:
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(APP_PROFILE) + "_proxy",
                channel="chrome",
                executable_path=CHROME,
                headless=True,
                timeout=60_000,
                proxy={"server": PROXY},
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://www.gamer520.com/", timeout=40_000)
            title = page.title()
            ctx.close()
            return f"proxy browse OK: title={title!r}"
    except Exception as exc:  # noqa: BLE001
        return f"proxy browse FAIL {type(exc).__name__}: {str(exc)[:200]}"


if __name__ == "__main__":
    out = {
        "persistence": probe_persistence(),
        "proxy_port": probe_proxy_port(),
        "proxy_browse": probe_proxy_browse(),
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
