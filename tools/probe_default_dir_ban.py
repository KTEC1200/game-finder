"""Throwaway probe #4: confirm the Chrome-136+ default-profile restriction.

Evidence so far:
  temp profile          -> OK
  copied mini profile   -> OK
  REAL profile (all launch variants, incl. CDP) -> FAIL

Hypothesis H9: Chrome >=136 refuses DevTools remote debugging (both
--remote-debugging-port and --remote-debugging-pipe) when the user data
dir IS the default one. Playwright uses the pipe, so it times out; CDP
never comes up. This has nothing to do with extensions, size, or locking.

Decisive test: FULL copy of the real profile to a non-default path.
  - if the full copy launches -> H9 confirmed, root cause is the PATH
  - if it also fails       -> the profile CONTENT is the problem

Second test: temp dir + --remote-debugging-port -> proves CDP itself works
when the dir is non-default (isolates "CDP broken" from "default dir banned").
"""

from __future__ import annotations

import json
import shutil
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
COPY_DEST = Path(r"D:\K\deepseek\_gf_profile_copy")
TIMEOUT = 45_000


def kill_chrome() -> None:
    subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True, text=True)
    time.sleep(2)


def probe_full_copy() -> str:
    """H9 decisive test: full copy of the real profile to a NON-default path."""
    if COPY_DEST.exists():
        shutil.rmtree(COPY_DEST, ignore_errors=True)
    COPY_DEST.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(
            REAL_PROFILE,
            COPY_DEST / "User Data",
            ignore=shutil.ignore_patterns(
                "Cache", "Code Cache", "GPUCache", "GrShaderCache",
                "ShaderCache", "Service Worker", "DawnCache",
            ),
            dirs_exist_ok=True,
        )
    except Exception as exc:  # noqa: BLE001
        return f"fullcopy: FAIL during copy {type(exc).__name__}: {str(exc)[:200]}"

    size = sum(f.stat().st_size for f in (COPY_DEST / "User Data").rglob("*") if f.is_file())
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(COPY_DEST / "User Data"),
                channel="chrome",
                executable_path=CHROME,
                headless=True,
                timeout=TIMEOUT,
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("about:blank", timeout=15000)
            n_cookies = len(ctx.cookies())
            ctx.close()
            return (
                f"fullcopy: OK (copied {size / 1e6:.0f} MB, "
                f"cookies visible={n_cookies}) -> H9 CONFIRMED: the default PATH is the blocker"
            )
    except Exception as exc:  # noqa: BLE001
        return (
            f"fullcopy: FAIL {type(exc).__name__}: {str(exc)[:150]} "
            f"(copied {size / 1e6:.0f} MB) -> H9 REFUTED: content, not path"
        )


def probe_cdp_temp() -> str:
    """Does CDP work at all when the user-data-dir is NOT the default?"""
    kill_chrome()
    tmp = tempfile.mkdtemp(prefix="gf_cdp_")
    proc = subprocess.Popen(
        [
            CHROME,
            "--remote-debugging-port=9333",
            f"--user-data-dir={tmp}",
            "--no-first-run",
            "--no-default-browser-check",
            "--headless=new",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 35
    version = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:9333/json/version", timeout=2) as r:
                version = json.loads(r.read().decode("utf-8", "replace"))
                break
        except (urllib.error.URLError, OSError, TimeoutError):
            time.sleep(1)

    if version is None:
        proc.terminate()
        return "cdp-temp: FAIL devtools never came up even on a temp dir"
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp("http://127.0.0.1:9333")
            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("about:blank", timeout=15000)
            browser.close()
        return f"cdp-temp: OK browser={version.get('Browser','?')} -> CDP works on non-default dir"
    except Exception as exc:  # noqa: BLE001
        return f"cdp-temp: FAIL attach {type(exc).__name__}: {str(exc)[:150]}"
    finally:
        proc.terminate()
        time.sleep(1)
        kill_chrome()


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    out: list[str] = []
    if which in ("all", "copy"):
        out.append(probe_full_copy())
    if which in ("all", "cdptemp"):
        out.append(probe_cdp_temp())
    print(json.dumps(out, indent=2, ensure_ascii=False))
