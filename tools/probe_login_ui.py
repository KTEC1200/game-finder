"""真机验证：登录框的接线（真 Chrome + 真 /api/sites，不替用户输密码）。

离线测试只能锁字串；这个探针在真浏览器里跑真 JS，验四件事：
  1. needs_login 的站卡片上真的长出登录框；
  2. 不需要登录的站**不会**长（否则每个卡片都被骚扰）；
  3. 已经有链接的卡片（direct/pan）不长；
  4. /api/login 对不需要登录的站快速拒绝、不弹窗。

点按钮那一步故意不点 —— 它会开一个有头 Chrome 并阻塞等用户操作，
自动化里做不了，那部分由 tools/probe_login_flow.py 单独验（已验证通过）。

用法：python tools/probe_login_ui.py
"""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tools" / "probe_login_ui.json"
PORT = 8793
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


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


JS = """
(cases) => {
  const out = [];
  for (const c of cases) {
    const card = document.createElement('div');
    document.body.appendChild(card);
    // 真 JS 函数，不是复制品
    renderLogin(c, card);
    const box = card.querySelector('.loginbox');
    const btn = card.querySelector('button.login');
    out.push({
      site_id: c.site_id, outcome: c.outcome,
      has_box: !!box,
      btn_text: btn ? btn.textContent : null,
      msg: box ? box.querySelector('.loginmsg').textContent.slice(0, 20) : null,
    });
    card.remove();
  }
  return out;
}
"""


def main() -> int:
    rep: dict = {"port": PORT}
    threading.Thread(target=_serve, daemon=True).start()
    if not wait_port(PORT):
        rep["error"] = "server did not start"
        OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1

    # 接口侧：不需要登录的站必须被快速拒绝（不会弹窗）
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/api/login",
        data=json.dumps({"site_id": "nyaa"}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        rep["api_login_nyaa"] = json.loads(r.read().decode())

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=CHROME, headless=True)
        page = b.new_page(viewport={"width": 1366, "height": 900})
        page.goto(f"http://127.0.0.1:{PORT}/", wait_until="domcontentloaded")
        page.wait_for_function("() => Object.keys(SITES).length > 0", timeout=15000)
        rep["sites_loaded"] = page.evaluate("() => Object.keys(SITES).length")
        rep["galgame_dev_needs_login"] = page.evaluate(
            "() => SITES['galgame.dev'] && SITES['galgame.dev'].needs_login")
        rep["galgame_dev_login_url"] = page.evaluate(
            "() => SITES['galgame.dev'] && SITES['galgame.dev'].login_url")

        cases = [
            {"site_id": "galgame.dev", "outcome": "not_found"},
            {"site_id": "galgame.dev", "outcome": "no_links"},
            {"site_id": "galgame.dev", "outcome": "direct"},
            {"site_id": "galgame.dev", "outcome": "pan"},
            {"site_id": "nyaa", "outcome": "not_found"},
            {"site_id": "touchgal", "outcome": "not_found"},
        ]
        rep["cases"] = page.evaluate(JS, cases)
        b.close()

    OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
