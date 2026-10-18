"""失败结果用更短的 TTL 缓存。

设计权衡：
  - 成功结果缓存 12h：内容不会 12 小时内变，用户重复搜同一游戏应当瞬时返回。
  - 失败结果缓存 30min：不缓存的话，6 个失败站每次重搜要占掉 ~28s，
    让「重复搜索」几乎和首次一样慢；缓存 12h 又会让站点临时抽风时用户
    半天没法重试。30 分钟是这两者之间可接受的折中，且用户随时可以点
    「强制刷新」绕开。
"""
from pathlib import Path

import pytest

from finder import pipeline
from finder.models import GameDetail, SearchSpec, Site
from finder.store import Store


def _site(sid: str = "s1") -> Site:
    return Site(
        id=sid, name=sid, homepage=f"https://{sid}.test/",
        kinds=["网盘"], langs={"zh"}, url_searchable=True,
        search=SearchSpec(mode="url", url_template=f"https://{sid}.test/?s={{q}}"),
    )


class _FakePage:
    def close(self):
        pass


class _FakeSession:
    def __init__(self, *a, **kw):
        pass

    @classmethod
    def for_site(cls, config, root, site, profile_override=None):
        return cls()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def new_page(self):
        return _FakePage()


@pytest.fixture()
def fake_browser(monkeypatch):
    monkeypatch.setattr("finder.browser.BrowserSession", _FakeSession)


def _stub(monkeypatch, calls: list, factory):
    def fake(page, site, query, timeout_ms=45000):
        calls.append(site.id)
        return factory(site)

    monkeypatch.setattr(pipeline, "search_one", fake)


def test_failure_is_cached_briefly(monkeypatch, fake_browser, tmp_path):
    """同一次会话里连搜两次：失败站不该被重搜（否则重复搜索仍然很慢）。"""
    calls: list = []
    _stub(monkeypatch, calls,
          lambda s: GameDetail(site_id=s.id, url="u", title="",
                               error="NO_RESULTS: nothing found"))

    with Store(tmp_path / "c.db", ttl_hours=12) as st:
        pipeline.run({}, [_site()], "q", tmp_path, store=st)
        pipeline.run({}, [_site()], "q", tmp_path, store=st)

    assert len(calls) == 1, f"失败结果应短缓存，实际重搜 {len(calls)} 次"


def test_failure_cache_expires_much_sooner_than_success(monkeypatch, fake_browser, tmp_path):
    """失败 TTL 必须显著短于成功 TTL，否则站点恢复后用户半天等不到。"""
    import time as _t

    calls: list = []
    _stub(monkeypatch, calls,
          lambda s: GameDetail(site_id=s.id, url="u", title="",
                               error="TIMEOUT: x"))

    with Store(tmp_path / "c.db", ttl_hours=12, fail_ttl_minutes=0) as st:
        pipeline.run({}, [_site()], "q", tmp_path, store=st)
        _t.sleep(0.02)
        pipeline.run({}, [_site()], "q", tmp_path, store=st)

    assert len(calls) == 2, "fail_ttl_minutes=0 时失败结果必须立刻可重试"


def test_force_refresh_ignores_both_caches(monkeypatch, fake_browser, tmp_path):
    calls: list = []
    _stub(monkeypatch, calls,
          lambda s: GameDetail(site_id=s.id, url="u", title="",
                               error="TIMEOUT: x"))

    with Store(tmp_path / "c.db", ttl_hours=12) as st:
        pipeline.run({}, [_site()], "q", tmp_path, store=st)
        pipeline.run({}, [_site()], "q", tmp_path, store=st, use_cache=False)

    assert len(calls) == 2


def test_cached_failure_is_marked_as_cached(monkeypatch, fake_browser, tmp_path):
    _stub(monkeypatch, lambda calls, factory: None,
          lambda s: GameDetail(site_id=s.id, url="u", title=""))
    calls: list = []
    _stub(monkeypatch, calls,
          lambda s: GameDetail(site_id=s.id, url="u", title="",
                               error="NO_RESULTS: x"))

    with Store(tmp_path / "c.db", ttl_hours=12) as st:
        pipeline.run({}, [_site()], "q", tmp_path, store=st)
        second = pipeline.run({}, [_site()], "q", tmp_path, store=st)

    assert second[0].extra.get("cached") is True
    assert second[0].error is not None, "缓存住的失败仍要如实报错"
