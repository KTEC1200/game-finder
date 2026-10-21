"""打包版真机验收：引擎兜底块在 PyInstaller 产物里也真的出现。

与 `tools/probe_engines_ui.py` 的区别：那个跑的是源码（同进程 uvicorn），
这个跑的是**解压后的 exe**（`_internal/` 里的静态资源、frozen 路径全部生效）。
打包后 `finder/web/static/index.html` 来自 `_internal/`，如果 spec 的 datas 漏了
新增的 HTML 改动，界面上就看不到兜底块 —— 离线测试发现不了这件事。

用法：python tools/probe_packaged_engines.py <解压目录> [查询词]
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent / "probe_packaged_engines.json"
PORT = 8795


def wait_port(port: int, timeout: float = 60.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/sites", timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: probe_packaged_engines.py <extract_dir> [query]")
        return 1
    exe = Path(sys.argv[1]) / "game-finder.exe"
    query = sys.argv[2] if len(sys.argv) > 2 else "终焉之莉莉"
    report: dict = {"exe": str(exe), "query": query, "port": PORT}
    if not exe.exists():
        report["error"] = f"exe not found: {exe}"
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1

    proc = subprocess.Popen([str(exe), "--no-browser", "--port", str(PORT)],
                            cwd=str(exe.parent),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_port(PORT):
            report["error"] = "packaged server did not start"
            return 1
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = browser.new_page(viewport={"width": 1400, "height": 1000})
            page.goto(f"http://127.0.0.1:{PORT}/", wait_until="domcontentloaded")
            page.fill("#q", query)
            page.click("#go")
            page.wait_for_function(
                "() => document.getElementById('langLine').textContent.includes('完成')",
                timeout=300_000,
            )
            report["lang_line"] = page.inner_text("#langLine")
            report["engines_display"] = page.evaluate(
                "() => getComputedStyle(document.getElementById('engines')).display")
            report["engines_text"] = page.inner_text("#engines")
            report["engine_links"] = page.evaluate(
                "() => [...document.querySelectorAll('#engines a.engine')]"
                ".map(a => ({name: a.textContent, href: a.href}))")
            report["cards"] = page.evaluate(
                "() => document.querySelectorAll('#out .card').length")
            page.screenshot(path=str(OUT.with_suffix(".png")), full_page=False)
            browser.close()
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {OUT}")
    return 0 if "error" not in report else 2


if __name__ == "__main__":
    raise SystemExit(main())
