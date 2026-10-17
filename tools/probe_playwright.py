"""Throwaway probe: does playwright drive real Chrome on Python 3.14?

Answers three questions the design depends on:
  1. can we launch_persistent_context with channel="chrome" (real Chrome, not bundled Chromium)?
  2. does the profile-in-use detection actually fire when Chrome is already running?
  3. can we reach a real site through the local proxy?

This is a SPIKE. Delete it once the answers are recorded in the plan.
"""

import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
REAL_PROFILE = Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data"
PROXY = "http://127.0.0.1:7890"


def probe_basic() -> str:
    """Temp profile + real Chrome + fetch example.com."""
    with tempfile.TemporaryDirectory(prefix="gf_probe_") as tmp:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=tmp,
                channel="chrome",
                executable_path=CHROME,
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://example.com", timeout=20000)
            title = page.title()
            ctx.close()
            return f"OK title={title!r}"


def probe_real_profile() -> str:
    """The real question: is the user's own Chrome profile usable?"""
    if not REAL_PROFILE.exists():
        return f"SKIP profile missing: {REAL_PROFILE}"
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(REAL_PROFILE),
                channel="chrome",
                executable_path=CHROME,
                headless=True,
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("about:blank", timeout=15000)
            n_cookies = len(ctx.cookies())
            ctx.close()
            return f"OK real profile opened, cookies visible={n_cookies}"
    except Exception as exc:  # noqa: BLE001 - probe: report the real error text
        return f"FAIL {type(exc).__name__}: {str(exc)[:300]}"


def probe_proxy() -> str:
    """Can the context route through the local proxy?"""
    with tempfile.TemporaryDirectory(prefix="gf_proxy_") as tmp:
        try:
            with sync_playwright() as p:
                ctx = p.chromium.launch_persistent_context(
                    user_data_dir=tmp,
                    channel="chrome",
                    executable_path=CHROME,
                    headless=True,
                    proxy={"server": PROXY},
                )
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto("https://www.google.com", timeout=25000)
                title = page.title()
                ctx.close()
                return f"OK proxied fetch title={title!r}"
        except Exception as exc:  # noqa: BLE001
            return f"FAIL {type(exc).__name__}: {str(exc)[:300]}"


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "basic"
    result = {
        "basic": probe_basic,
        "real": probe_real_profile,
        "proxy": probe_proxy,
    }[which]()
    print(f"[{which}] {result}")
