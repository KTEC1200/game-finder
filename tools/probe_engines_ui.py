"""真机验证：搜索引擎兜底块（engines 帧 → #engines 显示）。

离线测试只能锁结构和帧契约，锁不住「真浏览器里那块到底出没出来」。
这个探针在同进程里起 uvicorn 线程 + 真 Chrome（系统 Chrome，不用自带 Chromium），
输入一个查询，等 done 帧，然后记录：

  - #engines 的 computed display / innerText / 每个按钮的 href
  - 它在 DOM 里是否真的排在 #out 之前
  - done 帧的 ok/total（从 langLine 文案里读）

控制台是 GBK，CJK 直接 print 会乱码 → 结果写 tools/probe_engines_ui.json，
用 read 工具看。

用法：python tools/probe_engines_ui.py [查询词]
"""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tools" / "probe_engines_ui.json"
PORT = 8791

# 直接 `python tools/probe_x.py` 时 sys.path[0] 是 tools/，得把项目根补上
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _serve() -> None:
    import uvicorn

    from finder.web.server import app as fastapi_app

    uvicorn.run(fastapi_app, host="127.0.0.1", port=PORT, log_level="warning")


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
    query = sys.argv[1] if len(sys.argv) > 1 else "终焉之莉莉"
    report: dict = {"query": query, "port": PORT}
    threading.Thread(target=_serve, daemon=True).start()
    if not wait_port(PORT):
        report["error"] = "server did not start"
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1

    from playwright.sync_api import sync_playwright

    try:
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
            # done 帧会把 langLine 补上「完成（成功 x/y）」
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
                ".map(a => ({name: a.textContent, href: a.href,"
                " target: a.target, rel: a.rel}))")
            report["cards"] = page.evaluate(
                "() => document.querySelectorAll('#out .card').length")
            report["engines_before_results"] = page.evaluate(
                "() => { const e = document.getElementById('engines');"
                " const m = document.getElementById('out');"
                " return !!(e.compareDocumentPosition(m)"
                " & Node.DOCUMENT_POSITION_FOLLOWING); }")
            page.screenshot(path=str(ROOT / "tools" / "probe_engines_ui.png"),
                            full_page=False)
            browser.close()
    except Exception as exc:  # noqa: BLE001 - 探针要把失败也留证
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {OUT}")
    return 0 if "error" not in report else 2


if __name__ == "__main__":
    raise SystemExit(main())
