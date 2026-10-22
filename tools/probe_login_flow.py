"""真机验证「打开浏览器手动登录」。

不替用户输密码，只验证程序这一侧的四件事：
  1. 有头窗口真的能起来（headful + 专用 profile，不被默认目录守卫拦）；
  2. 起来就落在登录页，用户不用自己找入口；
  3. 没人登录时到点超时、返回人话，不抛异常；
  4. profile 里的 Cookie 探测能读出真实结果。
"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import yaml
from finder.login import LoginSession, login_state
from finder.sites import load_sites

cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
cfg["proxy"] = {"enabled": False}          # 6234 不一定活着，直连测
sites = {s.id: s for s in load_sites(ROOT / "sites.yaml")}
site = sites["galgame.dev"]

out = {"site": site.id, "needs_login": site.needs_login}
out["state_before"] = login_state(cfg, ROOT, site)

sess = LoginSession(cfg, ROOT, site, timeout_s=12, poll_ms=500)
with sess:
    page = sess.page
    out["landed"] = page.url
    out["title"] = page.title()
    result = sess.wait_for_login()

out["result"] = {
    "ok": result.ok, "cancelled": result.cancelled,
    "message": result.message, "url": result.url,
    "elapsed_s": round(result.elapsed_s, 1),
}
out["state_after"] = login_state(cfg, ROOT, site)
Path("tools/probe_login_flow.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("wrote")
