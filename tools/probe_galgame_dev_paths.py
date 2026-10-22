"""真红讨论组：未登录时哪些路径能读、哪些必须登录。

目的：如果站内搜索必须登录，看有没有「不登录也能找到游戏」的路径
（版块列表 / 标签 / 最新 / 站点地图 / API）。
"""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import yaml
from finder.browser import BrowserSession

cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
cfg["browser"]["headless"] = True

PATHS = [
    "/", "/categories", "/recent", "/popular", "/tags",
    "/api/recent", "/api/categories", "/api/tags",
    "/search?term=test&in=titles", "/api/search?term=test&in=titles",
    "/sitemap.xml", "/api/config",
]
out = {}
with BrowserSession(cfg, ROOT) as s:
    page = s.new_page()
    for p in PATHS:
        rec = {}
        try:
            r = page.goto("https://galgame.dev" + p, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(1200)
            rec["status"] = r.status if r else None
            rec["landed"] = page.url.replace("https://galgame.dev","")
            rec["login_wall"] = "/login" in page.url
            body = page.evaluate("() => document.body ? document.body.innerText : ''") or ""
            rec["text_len"] = len(body)
            rec["has_login_prompt"] = "登录或注册以进行搜索" in body
            rec["head"] = body[:180].replace("\n"," ")
            rec["links"] = page.evaluate(
                "() => Array.from(document.querySelectorAll('a[href*=\"/topic/\"]')).length")
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"[:160]
        out[p] = rec
Path("tools/probe_galgame_dev_paths.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("wrote tools/probe_galgame_dev_paths.json")
