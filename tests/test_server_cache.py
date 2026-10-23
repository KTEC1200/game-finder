"""/api/search 的 refresh 开关：前端「强制刷新」必须真的绕过缓存。"""
import pytest
from fastapi.testclient import TestClient

from finder.models import GameDetail


@pytest.fixture()
def recorded(monkeypatch):
    """记录 _run_pipeline 收到的 use_cache 值。"""
    from finder.web import server as srv

    seen: list[bool] = []

    def fake(config, sites, query, root, use_cache=True, on_result=None):
        seen.append(use_cache)
        if not sites:
            return []
        d = GameDetail(site_id=sites[0].id, url="u", title="t")
        if on_result:
            on_result(d)
        return [d]

    monkeypatch.setattr(srv, "_run_pipeline", fake)
    return TestClient(srv.create_app()), seen


def test_search_defaults_to_using_cache(recorded):
    client, seen = recorded
    with client.stream("POST", "/api/search", json={"query": "终焉之莉莉"}) as r:
        "".join(r.iter_text())
    assert seen == [True]


def test_search_refresh_bypasses_cache(recorded):
    client, seen = recorded
    with client.stream("POST", "/api/search",
                       json={"query": "终焉之莉莉", "refresh": True}) as r:
        "".join(r.iter_text())
    assert seen == [False]


def test_start_event_reports_cache_mode(recorded):
    client, _ = recorded
    with client.stream("POST", "/api/search",
                       json={"query": "终焉之莉莉", "refresh": True}) as r:
        body = "".join(r.iter_text())
    assert '"use_cache": false' in body or '"use_cache":false' in body
