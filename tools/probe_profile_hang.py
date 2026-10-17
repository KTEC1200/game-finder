"""Throwaway probe #2: WHY does the real profile time out?

Hypotheses:
  H1 headless=True + real profile hangs (extensions / startup)
  H2 needs --profile-directory=Default explicitly
  H3 the profile dir is genuinely locked by something
  H4 channel="chrome" + executable_path conflict
  H5 any launch into a REAL profile hangs, and CDP (option b) is the only way

Each variant is isolated so one failure does not mask the next.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
REAL_PROFILE = Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data"
TIMEOUT = 45_000


def try_variant(label: str, **kwargs) -> str:
    try:
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(timeout=TIMEOUT, **kwargs)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("about:blank", timeout=15000)
            ctx.close()
            return f"{label}: OK"
    except Exception as exc:  # noqa: BLE001
        return f"{label}: FAIL {type(exc).__name__}: {str(exc)[:160]}"


def main() -> None:
    print(f"profile exists={REAL_PROFILE.exists()}")
    print(f"profile size =", end=" ")
    try:
        total = sum(f.stat().st_size for f in REAL_PROFILE.rglob("*") if f.is_file())
        print(f"{total / 1e6:.1f} MB")
    except Exception as exc:  # noqa: BLE001
        print(f"<error {exc}>")

    for name in ("Default", "Profile 1", "Profile 2"):
        print(f"  {name}: {(REAL_PROFILE / name).exists()}")
    print(f"  Local State: {(REAL_PROFILE / 'Local State').exists()}")
    print(f"  lockfile: {(REAL_PROFILE / 'lockfile').exists()}")
    print(f"  SingletonLock: {(REAL_PROFILE / 'SingletonLock').exists()}")

    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    results: list[str] = []

    if which in ("all", "temp-headless"):
        with tempfile.TemporaryDirectory(prefix="gf_a_") as tmp:
            results.append(
                try_variant(
                    "temp+headless",
                    user_data_dir=tmp,
                    channel="chrome",
                    executable_path=CHROME,
                    headless=True,
                )
            )

    if which in ("all", "real-headless"):
        results.append(
            try_variant(
                "real+headless",
                user_data_dir=str(REAL_PROFILE),
                channel="chrome",
                executable_path=CHROME,
                headless=True,
            )
        )

    if which in ("all", "real-headful"):
        results.append(
            try_variant(
                "real+headful",
                user_data_dir=str(REAL_PROFILE),
                channel="chrome",
                executable_path=CHROME,
                headless=False,
            )
        )

    if which in ("all", "real-default-dir"):
        results.append(
            try_variant(
                "real+headless+profile-directory=Default",
                user_data_dir=str(REAL_PROFILE),
                channel="chrome",
                executable_path=CHROME,
                headless=True,
                args=["--profile-directory=Default"],
            )
        )

    if which in ("all", "real-no-channel"):
        results.append(
            try_variant(
                "real+headless (no channel, explicit exe)",
                user_data_dir=str(REAL_PROFILE),
                executable_path=CHROME,
                headless=True,
            )
        )

    if which in ("all", "real-copy"):
        # H3 test: is the ORIGINAL dir locked, or does any real-shaped dir hang?
        with tempfile.TemporaryDirectory(prefix="gf_copy_") as tmp:
            dst = Path(tmp) / "User Data"
            dst.mkdir()
            for item in ("Local State",):
                src = REAL_PROFILE / item
                if src.exists():
                    (dst / item).write_bytes(src.read_bytes())
            default_src = REAL_PROFILE / "Default"
            if default_src.exists():
                (dst / "Default").mkdir()
                for f in ("Preferences", "Cookies", "Login Data"):
                    if (default_src / f).exists():
                        (dst / "Default" / f).write_bytes((default_src / f).read_bytes())
            results.append(
                try_variant(
                    "copied-profile+headless",
                    user_data_dir=str(dst),
                    channel="chrome",
                    executable_path=CHROME,
                    headless=True,
                )
            )

    if which == "procs":
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq chrome.exe"],
            capture_output=True,
            text=True,
        ).stdout
        print(out)
        return

    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
