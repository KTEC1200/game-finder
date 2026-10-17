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
from ..store import Store

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def _run_pipeline(config: dict, sites: list[Site], query: str, root: Path) -> list[GameDetail]:
    """真实现。测试里会被 monkeypatch 掉，避免起浏览器。"""
    from ..pipeline import run
    return run(config, sites, query, root)


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
        lang = detect_lang(query)
        part, skipped = filter_sites_by_lang(all_sites, lang)

        def gen():
            yield _sse("start", {
                "query": query, "lang": lang,
                "participating": len(part),
                "skipped": [{"id": s.id, "name": s.name,
                             "reason": "LANG_MISMATCH"} for s in skipped],
            })
            try:
                results = _run_pipeline(CONFIG, part, query, ROOT)
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

    @app.get("/api/health")
    def health():
        db = ROOT / "data" / "finder.db"
        if not db.exists():
            return {}
        with Store(db, CONFIG["cache"]["ttl_hours"]) as st:
            return {k: asdict(v) for k, v in st.health_latest().items()}

    static = Path(__file__).resolve().parent / "static"
    if static.exists():
        app.mount("/", StaticFiles(directory=str(static), html=True), name="static")
    return app


app = create_app()
