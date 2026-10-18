"""FastAPI + SSE 接口测试。全部离线：pipeline 被 monkeypatch。"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    # 让 server 不真的起浏览器：把 pipeline.run 替换成假实现
    from finder.web import server as srv
    monkeypatch.setattr(
        srv, "_run_pipeline",
        lambda config, sites, query, root, use_cache=True: [
            __import__("finder.models", fromlist=["GameDetail"]).GameDetail(
                site_id=sites[0].id, url="https://e.com/1", title="fake") if sites else
            __import__("finder.models", fromlist=["GameDetail"]).GameDetail(
                site_id="none", url="u", title="")
        ],
    )
    return TestClient(srv.create_app())


def test_sites_endpoint_lists_19(client):
    r = client.get("/api/sites")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 19
    assert {"id", "name", "langs", "mode"} <= set(data[0])


def test_search_streams_start_result_done(client):
    with client.stream("POST", "/api/search", json={"query": "终焉之莉莉"}) as r:
        assert r.status_code == 200
        body = "".join(r.iter_text())
    assert "event: start" in body
    assert '"lang": "zh"' in body or '"lang":"zh"' in body
    assert "event: result" in body
    assert "event: done" in body


def test_search_lang_routing_counts(client):
    """zh 输入应报告 14 个参与站点（移出 zi0 / nysoure / lzacg 后）。"""
    with client.stream("POST", "/api/search", json={"query": "终焉之莉莉"}) as r:
        body = "".join(r.iter_text())
    import re
    m = re.search(r'"participating":\s*(\d+)', body)
    assert m and int(m.group(1)) == 14
