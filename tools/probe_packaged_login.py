"""打包版真机验收：登录入口在 exe 里也能用。

源码真机绿 != 打包版真机绿（前几轮踩过）。这里跑解压后的 exe，验：
  1. /api/sites 带 needs_login + login_url（静态资源与 Python 都进了包）；
  2. /api/login 对不需要登录的站快速拒绝；
  3. 真浏览器里 renderLogin 真的长出按钮（JS 在 _internal 里）。
不点按钮（会开有头窗口并阻塞等人），那部分由 probe_login_flow.py 验。
"""
import json, subprocess, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = Path(sys.argv[1]) if len(sys.argv) > 1 else \
    Path("D:/K/deepseek/_zipv2/game-finder/game-finder.exe")
PORT = 8797
OUT = ROOT / "tools" / "probe_packaged_login.json"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

rep = {"exe": str(EXE), "port": PORT}
proc = subprocess.Popen([str(EXE), "--no-browser", "--port", str(PORT)],
                        cwd=str(EXE.parent), stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
try:
    end = time.time() + 90
    ok = False
    while time.time() < end:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/sites", timeout=1) as r:
                if r.status == 200:
                    ok = True
                    break
        except Exception:
            time.sleep(0.4)
    if not ok:
        rep["error"] = "packaged server did not start"
    else:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/sites", timeout=5) as r:
            sites = json.loads(r.read().decode())
        rep["site_count"] = len(sites)
        gd = next((s for s in sites if s["id"] == "galgame.dev"), None)
        rep["galgame_dev"] = {"needs_login": gd and gd["needs_login"],
                              "login_url": gd and gd["login_url"]}
        rep["nyaa_login_url"] = next((s["login_url"] for s in sites if s["id"] == "nyaa"), "MISSING")

        req = urllib.request.Request(
            f"http://127.0.0.1:{PORT}/api/login",
            data=json.dumps({"site_id": "nyaa"}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=15) as r:
            rep["api_login_nyaa"] = json.loads(r.read().decode())

        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            b = pw.chromium.launch(executable_path=CHROME, headless=True)
            page = b.new_page(viewport={"width": 1366, "height": 900})
            page.goto(f"http://127.0.0.1:{PORT}/", wait_until="domcontentloaded")
            page.wait_for_function("() => Object.keys(SITES).length > 0", timeout=20000)
            rep["sites_loaded"] = page.evaluate("() => Object.keys(SITES).length")
            rep["cases"] = page.evaluate("""
(cases) => cases.map(c => {
  const card = document.createElement('div');
  document.body.appendChild(card);
  renderLogin(c, card);
  const btn = card.querySelector('button.login');
  const r = {site_id: c.site_id, outcome: c.outcome, has_box: !!btn,
             btn_text: btn ? btn.textContent : null};
  card.remove();
  return r;
})""", [
                {"site_id": "galgame.dev", "outcome": "not_found"},
                {"site_id": "galgame.dev", "outcome": "direct"},
                {"site_id": "nyaa", "outcome": "not_found"},
            ])
            b.close()
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
print("wrote")
