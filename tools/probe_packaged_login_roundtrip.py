"""打包版真机验收：完整 HTTP 往返走一次 /api/login（真的开有头窗口）。

这是整条链路上唯一还没在**打包版**里验过的一段：
  前端按钮 → POST /api/login → LoginSession 起有头 Chrome → 落到登录页
  → 轮询 → 超时返回人话 → 关窗、释放锁

自动化没法替用户输密码，所以验的是「超时这条路径」：
把 exe 旁边的 config.yaml 里 login.timeout_s 改成 15，然后 POST 一次。
期望：HTTP 200、ok=false、message 含「等了 15 秒」、耗时 ≈ 15s（不是 600s，
也不是立刻 500）。同时验第二次调用不会被锁卡死（锁已释放）。

用法：python tools/probe_packaged_login_roundtrip.py [exe 所在目录]
"""
import json, re, subprocess, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("D:/K/deepseek/_zipv3/game-finder")
PORT = 8799
OUT = ROOT / "tools" / "probe_packaged_login_roundtrip.json"

rep = {"app": str(APP), "port": PORT}

# 把超时压到 15 秒（默认 600 会把验收卡 10 分钟）
cfg_path = APP / "config.yaml"
cfg = cfg_path.read_text(encoding="utf-8")
cfg2 = re.sub(r"(login:\s*\n(?:.*\n)*?\s*timeout_s:\s*)\d+", r"\g<1>15", cfg, count=1)
if cfg2 == cfg:
    rep["warn"] = "config 里没找到 login.timeout_s，未改写"
cfg_path.write_text(cfg2, encoding="utf-8")
rep["timeout_s_patched"] = "timeout_s: 15" in cfg2

proc = subprocess.Popen([str(APP / "game-finder.exe"), "--no-browser", "--port", str(PORT)],
                        cwd=str(APP), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        def post_login():
            t0 = time.time()
            req = urllib.request.Request(
                f"http://127.0.0.1:{PORT}/api/login",
                data=json.dumps({"site_id": "galgame.dev"}).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.status, json.loads(r.read().decode()), round(time.time() - t0, 1)

        st, body, dur = post_login()
        rep["first"] = {"status": st, "elapsed_s": dur, **body}
        # 第二次：锁必须已释放（否则会立刻回「已经有一个登录窗口开着」）
        st2, body2, dur2 = post_login()
        rep["second"] = {"status": st2, "elapsed_s": dur2, **body2}
finally:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()

OUT.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
print("wrote")
