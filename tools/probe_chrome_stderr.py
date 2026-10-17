"""Throwaway probe #9: capture Chrome's OWN words for the default-dir ban.

Probes #2-#6 established empirically:
  default profile path -> playwright timeout / CDP never opens
  copied profile       -> works
Same content, different path. That is the signature of the Chrome 136+
restriction on remote debugging with the default user-data-dir, but I want
Chrome's literal stderr text rather than my inference.

Also re-tests add_cookies() vs server Set-Cookie persistence, because
probe #7 (add_cookies -> lost) contradicts probe #8 (Set-Cookie -> kept).
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
REAL_PROFILE = Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data"


def capture_real_profile_stderr() -> str:
    """Launch Chrome on the REAL profile with a debug port, capture stderr."""
    proc = subprocess.Popen(
        [
            CHROME,
            "--remote-debugging-port=9444",
            f"--user-data-dir={REAL_PROFILE}",
            "--no-first-run",
            "--no-default-browser-check",
            "--headless=new",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(8)
    proc.terminate()
    try:
        out, err = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
    combined = (out or "") + (err or "")
    interesting = [
        ln
        for ln in combined.splitlines()
        if any(
            k in ln.lower()
            for k in ("devtools", "debug", "remote", "user-data", "profile", "error", "refus", "denied", "not allowed")
        )
    ]
    return "\n".join(interesting[:25]) or f"<no matching stderr; raw head: {combined[:400]!r}>"


def capture_temp_profile_stderr() -> str:
    """Control: same command, temp path. Should NOT print the warning."""
    tmp = tempfile.mkdtemp(prefix="gf_ctl_")
    proc = subprocess.Popen(
        [
            CHROME,
            "--remote-debugging-port=9445",
            f"--user-data-dir={tmp}",
            "--no-first-run",
            "--no-default-browser-check",
            "--headless=new",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    time.sleep(8)
    proc.terminate()
    try:
        out, err = proc.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
    combined = (out or "") + (err or "")
    interesting = [
        ln
        for ln in combined.splitlines()
        if any(
            k in ln.lower()
            for k in ("devtools", "debug", "remote", "user-data", "profile", "error", "refus", "denied", "not allowed")
        )
    ]
    return "\n".join(interesting[:25]) or "<no matching stderr (expected: clean)>"


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    if which in ("both", "real"):
        print("=== REAL profile stderr ===")
        print(capture_real_profile_stderr())
    if which in ("both", "temp"):
        print("=== TEMP profile stderr (control) ===")
        print(capture_temp_profile_stderr())
