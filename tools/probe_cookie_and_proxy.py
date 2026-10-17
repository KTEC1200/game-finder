"""Throwaway probe #8: nail cookie persistence + find the real proxy port.

Open questions after probe #7:
  Q1 dedicated profile: cookies vanished across relaunch while localStorage
     survived. Is it (a) never flushed to disk, (b) flushed then dropped,
     or (c) a headless-mode artifact?  -> deterministic local HTTP server,
     inspect the Cookies sqlite after close, compare headless vs headful.
  Q2 proxy: 127.0.0.1:7890 refused. What IS listening? -> scan common
     Clash/v2ray/mihomo ports and report what is actually open.

Local server avoids all network flakiness and makes Set-Cookie deterministic.
"""

from __future__ import annotations

import http.server
import json
import shutil
import socket
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = Path(r"D:\K\deepseek\_gf_cookie_probe")

PORT = 8731
COMMON_PROXY_PORTS = [7890, 7891, 7892, 7897, 7898, 10808, 10809, 1080, 1087, 8889, 8888, 2080, 20171, 33210]


class CookieHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = b"<html><body>ok</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header(
            "Set-Cookie", "gf_persist=yes; Path=/; Max-Age=86400; SameSite=Lax"
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # silence
        return


def start_server() -> http.server.ThreadingHTTPServer:
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), CookieHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def cookie_db_rows(profile: Path) -> dict:
    for rel in ("Default/Network/Cookies", "Default/Cookies"):
        p = profile / rel
        if p.exists():
            break
    else:
        return {"exists": False}
    try:
        tmp = Path(tempfile.mkdtemp(prefix="ck8_")) / "Cookies"
        shutil.copy2(p, tmp)
        con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM cookies")
        n = cur.fetchone()[0]
        cur.execute("SELECT host_key,name,value FROM cookies")
        rows = cur.fetchall()
        con.close()
        return {"exists": True, "rows": n, "sample": rows[:3], "bytes": p.stat().st_size}
    except Exception as exc:  # noqa: BLE001
        return {"exists": True, "error": f"{type(exc).__name__}: {str(exc)[:150]}"}


def run_round(label: str, headless: bool) -> list[str]:
    if PROFILE.exists():
        shutil.rmtree(PROFILE, ignore_errors=True)
    PROFILE.mkdir(parents=True, exist_ok=True)
    log: list[str] = []

    def launch():
        p = sync_playwright().start()
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE),
            channel="chrome",
            executable_path=CHROME,
            headless=headless,
            timeout=60_000,
        )
        return p, ctx

    # round 1: visit the cookie-setting page
    p, ctx = launch()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(f"http://127.0.0.1:{PORT}/", timeout=20000)
    dom = page.evaluate("document.cookie")
    ctx.close()
    p.stop()
    log.append(f"[{label}] r1 document.cookie={dom!r} db_after_r1={cookie_db_rows(PROFILE)}")

    time.sleep(2)

    # round 2: relaunch, is it still sent?
    p, ctx = launch()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(f"http://127.0.0.1:{PORT}/", timeout=20000)
    dom2 = page.evaluate("document.cookie")
    ctx.close()
    p.stop()
    log.append(f"[{label}] r2 document.cookie={dom2!r} db_after_r2={cookie_db_rows(PROFILE)}")

    ok = "gf_persist=yes" in dom2
    log.append(f"[{label}] VERDICT: cookie persistence {'WORKS' if ok else 'BROKEN'}")
    return log


def scan_proxy_ports() -> dict:
    found = {}
    for port in COMMON_PROXY_PORTS:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                found[port] = "open"
        except Exception:  # noqa: BLE001
            pass
    return found


def listening_ports() -> list[str]:
    """List local listening ports from netstat (no extra deps)."""
    import subprocess

    out = subprocess.run(
        ["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True
    ).stdout
    lines = [
        ln.strip()
        for ln in out.splitlines()
        if "LISTENING" in ln and "127.0.0.1:" in ln
    ]
    return lines[:40]


if __name__ == "__main__":
    srv = start_server()
    result: dict = {}
    try:
        result["headless"] = run_round("headless", True)
        result["headful"] = run_round("headful", False)
    finally:
        srv.shutdown()
    result["proxy_ports_open"] = scan_proxy_ports()
    result["listening_127"] = listening_ports()
    print(json.dumps(result, indent=2, ensure_ascii=False))
