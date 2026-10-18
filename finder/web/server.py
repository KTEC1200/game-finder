"""FastAPI + SSE。搜索按语种路由后流式推送。"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import yaml
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from ..lang import detect_lang
from ..models import GameDetail, Site
from ..sites import filter_sites_by_lang, load_sites

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


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
    all_sites = load_sites(ROOT / "sites.yaml")

    @app.get("/api/sites")
    def sites():
        return [
            {"id": s.id, "name": s.name, "langs": sorted(s.langs),
             "mode": s.search.mode, "url_searchable": s.url_searchable,
             "needs_login": s.needs_login, "max_query_len": s.max_query_len,
             "kinds": s.kinds}
            for s in all_sites
        ]

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
            for d in results:
                if not d.error:
                    ok += 1
                yield _sse("result", asdict(d))
            yield _sse("done", {"ok": ok, "total": len(results)})

        return StreamingResponse(gen(), media_type="text/event-stream")

    static = Path(__file__).resolve().parent / "static"
    if static.exists():
        app.mount("/", StaticFiles(directory=str(static), html=True), name="static")
    return app


app = create_app()
