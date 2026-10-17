"""Throwaway probe #6: WHY did the copied profile have 0 cookies?

probe #5 read the copy's cookie DB AFTER probe #4 had already launched it.
So two explanations remain:
  W1 the copy itself is fine, but LAUNCHING it wipes/rewrites the cookie DB
  W2 the copy genuinely cannot carry cookies (encryption key is profile-bound)

Method: fresh copy, read the DB IMMEDIATELY (never launched), then launch
and re-read. Also inspect Local State for os_crypt / app-bound encryption,
which is the suspected mechanism for W2.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
REAL_PROFILE = Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data"
FRESH = Path(r"D:\K\deepseek\_gf_profile_fresh")


def read_cookie_db(profile: Path) -> dict:
    for rel in ("Default/Network/Cookies", "Default/Cookies"):
        path = profile / rel
        if path.exists():
            break
    else:
        return {"exists": False}
    try:
        tmp = Path(tempfile.mkdtemp(prefix="ck2_")) / "Cookies"
        shutil.copy2(path, tmp)
        con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM cookies")
        total = cur.fetchone()[0]
        cur.execute("SELECT COUNT(DISTINCT host_key) FROM cookies")
        hosts = cur.fetchone()[0]
        con.close()
        return {"exists": True, "total": total, "hosts": hosts, "bytes": path.stat().st_size}
    except Exception as exc:  # noqa: BLE001
        return {"exists": True, "error": f"{type(exc).__name__}: {str(exc)[:150]}"}


def local_state_info(profile: Path) -> dict:
    ls = profile / "Local State"
    if not ls.exists():
        return {"exists": False}
    try:
        data = json.loads(ls.read_text(encoding="utf-8", errors="replace"))
        os_crypt = data.get("os_crypt", {})
        return {
            "exists": True,
            "os_crypt_keys": sorted(os_crypt.keys()),
            "has_encrypted_key": "encrypted_key" in os_crypt,
            "has_app_bound": "app_bound_encrypted_key" in os_crypt,
            "profile_count": len(data.get("profile", {}).get("info_cache", {})),
        }
    except Exception as exc:  # noqa: BLE001
        return {"exists": True, "error": f"{type(exc).__name__}: {str(exc)[:150]}"}


if __name__ == "__main__":
    print("original Local State:", json.dumps(local_state_info(REAL_PROFILE), ensure_ascii=False))
    print("original cookies   :", json.dumps(read_cookie_db(REAL_PROFILE), ensure_ascii=False))

    if FRESH.exists():
        shutil.rmtree(FRESH, ignore_errors=True)
    FRESH.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        REAL_PROFILE,
        FRESH / "User Data",
        ignore=shutil.ignore_patterns(
            "Cache", "Code Cache", "GPUCache", "GrShaderCache", "ShaderCache",
            "Service Worker", "DawnCache", "component_crx_cache",
        ),
        dirs_exist_ok=True,
    )
    copied = FRESH / "User Data"
    print("fresh copy Local St:", json.dumps(local_state_info(copied), ensure_ascii=False))
    print("fresh copy cookies (NEVER launched):", json.dumps(read_cookie_db(copied), ensure_ascii=False))

    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(copied),
                channel="chrome",
                executable_path=CHROME,
                headless=True,
                timeout=60_000,
            )
            print("ctx.cookies() before nav =", len(ctx.cookies()))
            ctx.close()
    except Exception as exc:  # noqa: BLE001
        print("launch FAIL", type(exc).__name__, str(exc)[:150])

    print("fresh copy cookies (AFTER launch):", json.dumps(read_cookie_db(copied), ensure_ascii=False))
