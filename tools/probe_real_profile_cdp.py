"""Throwaway probe #3: can we EVER use the real profile?

Findings so far (probe #2): real profile (1.7 GB) times out in every
launch_persistent_context variant; temp and copied profiles work fine.

This probe tests the two remaining candidate explanations and the
fallback architecture:

  H6 extensions/extensions-state block DevTools startup
      -> real profile + --disable-extensions
  H7 the real profile is too large / has heavy state to initialise
      -> real profile + --disable-extensions + --no-first-run + disk cache disabled
  H8 chrome.exe itself CAN open the real profile; only *playwright's* launch
     handshake fails -> option (b): launch chrome with --remote-debugging-port
     and connect_over_cdp

H8 is the one that matters: if it passes, the fallback in the design
(tools/chrome_debug.bat) becomes the PRIMARY path and (a) is retired.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
REAL_PROFILE = Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data"
TIMEOUT = 40_000
CDP_PORT = 9222


def try_variant(label: str, **kwargs) -> str:
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(timeout=TIMEOUT, **kwargs)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("about:blank", timeout=15000)
            n = len(ctx.pages)
            ctx.close()
            return f"{label}: OK (pages={n})"
    except Exception as exc:  # noqa: BLE001
        return f"{label}: FAIL {type(exc).__name__}: {str(exc)[:120]}"


def kill_chrome() -> None:
    subprocess.run(
        ["taskkill", "/F", "/IM", "chrome.exe"],
        capture_output=True,
        text=True,
    )
    time.sleep(2)


def probe_disable_extensions() -> str:
    return try_variant(
        "real+--disable-extensions",
        user_data_dir=str(REAL_PROFILE),
        channel="chrome",
        executable_path=CHROME,
        headless=True,
        args=["--disable-extensions"],
    )


def probe_disable_extensions_and_cache() -> str:
    return try_variant(
        "real+disable-ext+cache",
        user_data_dir=str(REAL_PROFILE),
        channel="chrome",
        executable_path=CHROME,
        headless=True,
        args=[
            "--disable-extensions",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-application-cache",
            "--disk-cache-size=1",
            "--disable-features=Translate,MediaRouter",
        ],
    )


def probe_cdp() -> str:
    """H8: launch real Chrome ourselves, then attach over CDP."""
    kill_chrome()
    proc = subprocess.Popen(
        [
            CHROME,
            f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={REAL_PROFILE}",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # poll the DevTools endpoint instead of sleeping a fixed amount
    deadline = time.time() + 40
    version: dict | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{CDP_PORT}/json/version", timeout=2
            ) as resp:
                version = json.loads(resp.read().decode("utf-8", "replace"))
                break
        except (urllib.error.URLError, OSError, TimeoutError):
            time.sleep(1)

    if version is None:
        proc.terminate()
        return "cdp: FAIL devtools endpoint never came up on real profile"

    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("about:blank", timeout=15000)
            n_cookies = len(ctx.cookies())
            n_pages = len(ctx.pages)
            browser.close()
        return (
            f"cdp: OK attached to real Chrome "
            f"(browser={version.get('Browser','?')}, "
            f"pages={n_pages}, cookies={n_cookies})"
        )
    except Exception as exc:  # noqa: BLE001
        return f"cdp: FAIL attach {type(exc).__name__}: {str(exc)[:160]}"
    finally:
        proc.terminate()
        time.sleep(1)
        kill_chrome()


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    out: list[str] = []
    if which in ("all", "ext"):
        out.append(probe_disable_extensions())
    if which in ("all", "extcache"):
        out.append(probe_disable_extensions_and_cache())
    if which in ("all", "cdp"):
        out.append(probe_cdp())
    print(json.dumps(out, indent=2, ensure_ascii=False))
