"""真机：galgame.dev 真的搜一次，确认 outcome 是 not_found（登录框才会出现）。

登录框出现的判据是 d.outcome in (not_found, no_links)，
而 galgame.dev 的 /search 未登录会 302 到 /login —— 这条链路必须实测一次，
否则「UI 有按钮但永远不出现」会静默通过所有离线测试。
"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import yaml
from finder.browser import BrowserSession
from finder.pipeline import search_one
from finder.sites import load_sites
from finder.web.server import outcome_of

cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
cfg["proxy"] = {"enabled": False}
site = {s.id: s for s in load_sites(ROOT / "sites.yaml")}["galgame.dev"]
out = {"site": site.id}
with BrowserSession(cfg, ROOT) as sess:
    page = sess.new_page()
    card = search_one(page, site, "千恋万花", timeout_ms=45000)
out["error"] = card.error
out["title"] = card.title
out["outcome"] = outcome_of(card)
out["downloads"] = len(card.downloads or [])
out["extra_keys"] = sorted((card.extra or {}).keys())
out["search_login_wall"] = (card.extra or {}).get("search_login_wall")
Path("tools/probe_login_outcome.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("wrote")
