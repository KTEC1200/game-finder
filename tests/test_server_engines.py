"""`/api/search` 的搜索引擎兜底帧（event: engines）。

用户要求（原文，m01166）：
  「如果出来的结果少于三个，在必应、百度、谷歌、Yandex也进行搜索和整合，
    不过不用给出结果，给跳转链接就行」

契约：
  - 触发条件 = **有下载链接的站点数 < 3**（`finder.engines.needs_fallback`）
  - 帧里只有跳转链接，没有引擎结果
  - 帧里 `query` 与用户输入逐字相同（引擎链接也用这个 query 拼）
  - 达到 3 个有链接的站点时**不发**这一帧（前端于是不会显示那块）
  - `done` 帧的 `ok/total` 语义一个字不改（既有测试锁着）
"""
from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from finder.models import Download, GameDetail


def _card(site_id: str, downloads: list[Download] | None = None,
          error: str | None = None) -> GameDetail:
    return GameDetail(site_id=site_id, url=f"https://{site_id}.test/x",
                      title=site_id, downloads=downloads or [], error=error)


def _pan(i: int = 0) -> Download:
    return Download(kind="pan", url=f"https://pan.baidu.com/s/{i}")


def _client(monkeypatch, results: list[GameDetail]) -> TestClient:
    from finder.web import server as srv
    monkeypatch.setattr(
        srv, "_run_pipeline",
        lambda config, sites, query, root, use_cache=True: list(results),
    )
    return TestClient(srv.create_app())


def _frames(body: str) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for blk in body.split("\n\n"):
        ev = re.search(r"^event:\s*(\S+)$", blk, re.M)
        data = re.search(r"^data:\s*(.+)$", blk, re.M)
        if ev and data:
            out.append((ev.group(1), json.loads(data.group(1))))
    return out


def _search(client: TestClient, query: str) -> list[tuple[str, dict]]:
    with client.stream("POST", "/api/search", json={"query": query}) as r:
        assert r.status_code == 200
        body = "".join(r.iter_text())
    return _frames(body)


# ---------------------------------------------------------------------------
# 触发 / 不触发
# ---------------------------------------------------------------------------
def test_two_linked_sites_emits_engines_frame(monkeypatch):
    client = _client(monkeypatch, [
        _card("a", [_pan(1)]),
        _card("b", [Download(kind="direct", url="https://x.test/a.zip")]),
    ])
    frames = _search(client, "终焉之莉莉")
    names = [n for n, _ in frames]
    assert "engines" in names, f"两个有链接的站应当补搜索引擎，实际帧：{names}"

    data = dict(frames)["engines"]
    assert data["linked_sites"] == 2
    assert data["threshold"] == 3
    assert [x["id"] for x in data["links"]] == ["bing", "baidu", "google", "yandex"]


def test_zero_linked_sites_emits_engines_frame(monkeypatch):
    client = _client(monkeypatch, [
        _card("a", [], error="NO_RESULTS: 未找到相關內容"),
        _card("b", [], error=None),
    ])
    frames = _search(client, "夏色四叶草")
    data = dict(frames).get("engines")
    assert data is not None
    assert data["linked_sites"] == 0


def test_three_linked_sites_does_not_emit_engines_frame(monkeypatch):
    client = _client(monkeypatch, [
        _card("a", [_pan(1)]),
        _card("b", [Download(kind="direct", url="https://x.test/a.zip")]),
        _card("c", [Download(kind="magnet", url="magnet:?xt=urn:btih:" + "b" * 40)]),
    ])
    frames = _search(client, "enderlilies")
    assert "engines" not in [n for n, _ in frames]


def test_found_but_no_links_counts_toward_nothing(monkeypatch):
    """三张「找到但没链接」的卡 + 一张有链接 → 仍然只有 1 个有链接站。"""
    client = _client(monkeypatch, [
        _card("a", [], error="NO_DOWNLOADS: x"),
        _card("b", [], error="NEEDS_LOGIN: x"),
        _card("c", [], error=None),
        _card("d", [_pan(1)]),
    ])
    data = dict(_search(client, "x"))["engines"]
    assert data["linked_sites"] == 1


# ---------------------------------------------------------------------------
# 帧内容
# ---------------------------------------------------------------------------
def test_engines_frame_carries_the_query_verbatim(monkeypatch):
    client = _client(monkeypatch, [])
    data = dict(_search(client, "Summer Clover"))["engines"]
    assert data["query"] == "Summer Clover"
    # 链接里用的就是同一个 query（空格 → %20）
    assert "q=Summer%20Clover" in data["links"][0]["url"]


def test_engines_frame_has_no_engine_results(monkeypatch):
    """用户明确说「不用给出结果」——帧里除了链接不许有别的东西。"""
    client = _client(monkeypatch, [])
    data = dict(_search(client, "终焉之莉莉"))["engines"]
    assert set(data) == {"query", "linked_sites", "threshold", "links"}
    for link in data["links"]:
        assert set(link) == {"id", "name", "url"}


def test_engines_frame_links_are_all_https(monkeypatch):
    client = _client(monkeypatch, [])
    for link in dict(_search(client, "x"))["engines"]["links"]:
        assert link["url"].startswith("https://")


# ---------------------------------------------------------------------------
# 既有语义不受影响
# ---------------------------------------------------------------------------
def test_done_frame_keeps_ok_total_semantics(monkeypatch):
    """`ok` 仍只数「无 error」的站，不因兜底帧改变。"""
    client = _client(monkeypatch, [
        _card("a", [_pan(1)]),                    # ok
        _card("b", [], error="NO_RESULTS: x"),    # 不算 ok
        _card("c", [], error=None),               # ok
    ])
    done = dict(_search(client, "x"))["done"]
    assert done == {"ok": 2, "total": 3}


def test_engines_frame_comes_before_result_frames(monkeypatch):
    """兜底块在结果区上方，帧顺序也要在 result 之前，前端才能先建容器。"""
    client = _client(monkeypatch, [_card("a", [_pan(1)])])
    names = [n for n, _ in _search(client, "x")]
    assert names.index("engines") < names.index("result")
    assert names[-1] == "done"


def test_pipeline_error_still_emits_done(monkeypatch):
    """管线炸了：不补引擎链接（没结果可判断），但仍然要收尾。"""
    from finder.web import server as srv

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(srv, "_run_pipeline", boom)
    frames = _search(TestClient(srv.create_app()), "x")
    names = [n for n, _ in frames]
    assert "error" in names
    assert "engines" not in names
    assert names[-1] == "done"
