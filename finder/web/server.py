"""FastAPI + SSE。搜索按语种路由后流式推送。"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path

import yaml
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .. import paths
from ..engines import MIN_LINKED_SITES, engine_links, needs_fallback
from ..lang import detect_lang
from ..login import LoginSession, login_state, login_url_for
from ..models import GameDetail, Site
from ..sites import filter_sites_by_lang, load_sites

log = logging.getLogger("gamefinder.server")

# 开发形态下 ROOT 就是项目根（与改动前等价）；打包后是 exe 旁边，
# 这样 config.yaml / sites.yaml / data/ / chrome-profile/ 都能被用户改。
paths.ensure_runtime_files()
ROOT = paths.app_root()
CONFIG = yaml.safe_load(paths.config_path(ROOT).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 结果分档 & 排序
# ---------------------------------------------------------------------------
# 直链的字面值必须与 models.DownloadKind 对齐：
#   DownloadKind = Literal["direct", "pan", "magnet", "filehost", "unknown"]
# tests/test_result_order.py 断言 DIRECT_KIND 真的在 get_args(DownloadKind) 里，
# 免得 models 改名后这里悄悄失配。
DIRECT_KIND = "direct"

# 分档的先后 == 用户要求的排序优先级（m00620：「找到链接的排前面」）。
OUTCOME_ORDER = {"direct": 0, "pan": 1, "no_links": 2, "not_found": 3}

# 「站点确实找到了这款游戏、只是抽不到下载链接」的错误前缀（详情页级）。
# 注意 NEEDS_LOGIN 有两种语意，靠 extra["search_login_wall"] 区分（见 outcome_of），
# 不去比对中文文案。
NO_LINKS_PREFIXES = frozenset({
    "NO_DOWNLOADS", "NEEDS_GATE", "NEEDS_COMMENT", "NEEDS_LOGIN",
})


def _error_prefix(error: str | None) -> str:
    """`NO_RESULTS: xxx` -> `NO_RESULTS`；`NO_DOWNLOADS`（无冒号）原样返回。"""
    if not error:
        return ""
    return error.split(":", 1)[0].strip()


def outcome_of(d: GameDetail) -> str:
    """这个站对这次查询到底「找到了什么」，四档之一：

      direct     有直链：downloads 里有 kind == DIRECT_KIND 的条目
      pan        有下载但都不是直链（网盘 / 磁力 / filehost …）
      no_links   站点找到了这款游戏，但没有可下载的链接
      not_found  根本没搜到（无结果 / 选错游戏 / 表单失败 / 被拦 / 搜索页登录墙 …）

    只读 error / downloads / extra：NO_RESULTS 的实测形状是 url=None, title=''
    （例：acggw），任何字段为 None 都不该抛异常。
    """
    downloads = getattr(d, "downloads", None) or []
    if downloads:
        if any(getattr(x, "kind", None) == DIRECT_KIND for x in downloads):
            return "direct"
        return "pan"
    # error 为 None 或空串都算「没出错但也没链接」——与 gen() 里 `not d.error`
    # 计 ok 的口径保持一致。
    if not d.error:
        return "no_links"
    prefix = _error_prefix(d.error)
    if prefix == "NEEDS_LOGIN":
        # 搜索页级：搜索被重定向到登录页 == 根本没搜到，pipeline 会写
        # extra["search_login_wall"]（值是登录页 URL）。
        # 详情页级（隐藏内容门槛）不写这个键 → 属于「找到但没链接」。
        if (getattr(d, "extra", None) or {}).get("search_login_wall"):
            return "not_found"
        return "no_links"
    return "no_links" if prefix in NO_LINKS_PREFIXES else "not_found"


def order_results(
    results: list[GameDetail], tier_by_site: dict[str, str],
) -> list[GameDetail]:
    """按「链接质量 → 站点分级 → 原始顺序」排序，返回**新** list。

    主键 direct < pan < no_links < not_found；次键 backup 站排在同档 primary 之后；
    第三键用 enumerate 下标，保证同键项维持原相对顺序（sorted 本身稳定，加下标
    是为了连「主键+次键都相同」的情形也钉死）。
    """
    def key(item: tuple[int, GameDetail]) -> tuple[int, int, int]:
        idx, d = item
        backup = 1 if tier_by_site.get(d.site_id) == "backup" else 0
        return (OUTCOME_ORDER[outcome_of(d)], backup, idx)

    return [d for _, d in sorted(enumerate(results), key=key)]


def _run_pipeline(
    config: dict, sites: list[Site], query: str, root: Path,
    use_cache: bool = True,
) -> list[GameDetail]:
    """真实现。测试里会被 monkeypatch 掉，避免起浏览器。

    这里负责 Store 的生命周期：sqlite 连接不能跨线程共享，所以每次搜索
    新开一个（打开 + 建表都是毫秒级，不值得为它引入连接池）。
    """
    from ..pipeline import run
    from ..store import Store

    db = root / "data" / "finder.db"
    ttl = int((config.get("cache") or {}).get("ttl_hours") or 12)
    with Store(db, ttl) as st:
        return run(config, sites, query, root, store=st, use_cache=use_cache)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def create_app() -> FastAPI:
    app = FastAPI(title="Game Finder")
    all_sites = load_sites(paths.sites_path(ROOT))

    @app.get("/api/sites")
    def sites():
        return [
            {"id": s.id, "name": s.name, "langs": sorted(s.langs),
             "mode": s.search.mode, "url_searchable": s.url_searchable,
             "needs_login": s.needs_login, "max_query_len": s.max_query_len,
             "kinds": s.kinds,
             # UI 用：卡片标题/跳转链接的兜底（NO_RESULTS 时 title/url 都是空的）
             # 与「备用站」标签。既有字段一个都没动。
             "homepage": s.homepage, "tier": s.tier,
             # 需要登录的站才给登录入口，其余站不显示按钮
             "login_url": login_url_for(s)}
            for s in all_sites
        ]

    @app.post("/api/login")
    def login(body: dict):
        """开一个**有头**浏览器让用户手动登录，阻塞到登录成功 / 超时。

        为什么阻塞：前端点了按钮就一直显示「等你登录…」，用户登完自动重搜。
        profile 独占，同一时刻只允许一个（login.LoginSession 的 _LOCK）。
        """
        site_id = (body.get("site_id") or "").strip()
        target = next((s for s in all_sites if s.id == site_id), None)
        if target is None:
            return {"ok": False, "site_id": site_id, "message": f"没有这个站点：{site_id}"}
        if not target.needs_login:
            return {"ok": False, "site_id": site_id,
                    "message": f"{target.name} 不需要登录"}
        try:
            with LoginSession(CONFIG, ROOT, target) as sess:
                result = sess.wait_for_login()
        except RuntimeError as exc:  # 已有窗口开着
            return {"ok": False, "site_id": site_id, "message": str(exc)}
        except Exception as exc:  # noqa: BLE001 - 起浏览器失败等
            log.exception("login failed for %s", site_id)
            return {"ok": False, "site_id": site_id,
                    "message": f"{type(exc).__name__}: {str(exc)[:200]}"}
        return {
            "ok": result.ok, "site_id": result.site_id, "url": result.url,
            "message": result.message, "elapsed_s": result.elapsed_s,
            "cancelled": result.cancelled,
        }

    @app.get("/api/login/state")
    def login_state_api(site_id: str = ""):
        """只读探测 profile 里有没有该站 Cookie（不弹窗口、不搜索）。"""
        target = next((s for s in all_sites if s.id == site_id), None)
        if target is None:
            return {"site_id": site_id, "logged_in": False, "reason": "没有这个站点"}
        return login_state(CONFIG, ROOT, target)

    @app.post("/api/search")
    def search(body: dict):
        query = (body.get("query") or "").strip()
        # 前端「强制刷新」按钮用：绕过缓存重新抓一遍
        use_cache = not bool(body.get("refresh"))
        lang = detect_lang(query)
        part, skipped = filter_sites_by_lang(all_sites, lang)

        def gen():
            yield _sse("start", {
                "query": query, "lang": lang,
                "participating": len(part),
                "use_cache": use_cache,
                "skipped": [{"id": s.id, "name": s.name,
                             "reason": "LANG_MISMATCH"} for s in skipped],
            })
            try:
                results = _run_pipeline(CONFIG, part, query, ROOT, use_cache)
            except Exception as exc:  # noqa: BLE001
                yield _sse("error", {"message": f"{type(exc).__name__}: {str(exc)[:200]}"})
                yield _sse("done", {"ok": 0, "total": len(part)})
                return
            ok = 0
            # _run_pipeline 先把整个 list 拿回来，之后才逐条发帧，
            # 所以排序放后端是零成本的（不需要在 JS 里重排 DOM）。
            tier_by_site = {s.id: s.tier for s in part}
            ordered = order_results(results, tier_by_site)
            # 资源站没找够（有链接的站点 < 3）时补一块「去搜索引擎再找」。
            # 这一帧只带跳转链接，不带任何引擎结果；放在 result 之前，
            # 前端于是先建好结果区上方那个容器。顺序与阈值见 finder/engines.py。
            fallback, linked = needs_fallback(results)
            if fallback:
                yield _sse("engines", {
                    "query": query,
                    "linked_sites": linked,
                    "threshold": MIN_LINKED_SITES,
                    "links": engine_links(query),
                })
            for d in ordered:
                if not d.error:
                    ok += 1
                payload = asdict(d)
                # 让 UI 按档上色/分组，而不必在 JS 里解析错误字串
                payload["outcome"] = outcome_of(d)
                yield _sse("result", payload)
            yield _sse("done", {"ok": ok, "total": len(results)})

        return StreamingResponse(gen(), media_type="text/event-stream")

    # 前端资源跟着 Python 包走（打包后在只读资源里），不在 exe 旁边。
    static = paths.static_dir()
    if static.exists():
        app.mount("/", StaticFiles(directory=str(static), html=True), name="static")
    return app


app = create_app()
