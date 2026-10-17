"""Throwaway probe #5: does a COPIED profile actually keep login state?

Why this matters: probe #4 showed the real (default-path) profile cannot be
driven by playwright on Chrome 155, but a COPY to a non-default path CAN.
That workaround is only useful if the copy preserves cookies/logins.

Red flag to explain: probe #4's full copy reported cookies visible=0.
Either
  C1 cookies did not copy / cannot be decrypted (DPAPI key mismatch), or
  C2 ctx.cookies() just returns 0 before any navigation in that setup.

Method:
  - read the ORIGINAL Cookies sqlite directly (count rows, count hosts)
  - read the COPIED Cookies sqlite directly (same counts?)
  - launch the copy and call ctx.cookies() with and without a navigation
  - compare a few target-site domains present in the original DB
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
REAL_PROFILE = Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data"
COPY = Path(r"D:\K\deepseek\_gf_profile_copy") / "User Data"

TARGETS = [
    "anime-sharing.com",
    "ggbases.dlgal.com",
    "www.gamer520.com",
    "www.jidiyouxi.com",
    "catcat.cloud",
    "www.touchgal.ink",
    "galgame.dev",
    "www.kungal.com",
]


def cookie_stats(label: str, profile: Path) -> dict:
    db = profile / "Default" / "Network" / "Cookies"
    alt = profile / "Default" / "Cookies"
    path = db if db.exists() else alt
    out: dict = {"label": label, "db": str(path), "exists": path.exists()}
    if not path.exists():
        return out
    try:
        # copy the db first: chrome may hold it, and we must not write to it
        tmp = Path(tempfile.mkdtemp(prefix="ck_")) / "Cookies"
        shutil.copy2(path, tmp)
        con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM cookies")
        out["total_cookies"] = cur.fetchone()[0]
        cur.execute("SELECT COUNT(DISTINCT host_key) FROM cookies")
        out["distinct_hosts"] = cur.fetchone()[0]
        found = {}
        for t in TARGETS:
            cur.execute(
                "SELECT COUNT(*) FROM cookies WHERE host_key LIKE ?", (f"%{t}%",)
            )
            n = cur.fetchone()[0]
            if n:
                found[t] = n
        out["target_hosts_present"] = found
        con.close()
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return out


def launch_and_count(profile: Path) -> str:
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                channel="chrome",
                executable_path=CHROME,
                headless=True,
                timeout=60_000,
            )
            before = len(ctx.cookies())
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("about:blank", timeout=15000)
            after_blank = len(ctx.cookies())
            ctx.close()
            return f"OK cookies: before={before} after_blank={after_blank}"
    except Exception as exc:  # noqa: BLE001
        return f"FAIL {type(exc).__name__}: {str(exc)[:200]}"


if __name__ == "__main__":
    results = [
        cookie_stats("ORIGINAL", REAL_PROFILE),
        cookie_stats("COPY", COPY),
    ]
    print(json.dumps(results, indent=2, ensure_ascii=False))
    if COPY.exists():
        print("launch copy ->", launch_and_count(COPY))
