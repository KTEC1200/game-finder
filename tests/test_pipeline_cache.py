"""pipeline.run 的缓存接线。

设计取舍（写下来免得以后重新纠结）：
  - **只缓存成功结果**（error is None）。失败/无下载缓存 12 小时等于让用户
    没法重试——站点临时抽风一次，用户就被卡半天。宁可多搜一次。
  - 缓存键用**该站实际使用的查询词**（clamp_query 之后），因为 acggw 有
    max_query_len=10 会截断；用原始词做键会让「截断后的同一搜索」漏命中。
  - 命中缓存的卡片打 extra["cached"]=True，UI 与测试都能看出来。
"""
from pathlib import Path

import pytest

from finder import pipeline
from finder.models import Download, GameDetail, SearchSpec, Site
from finder.store import Store


def _site(sid: str = "s1", maxlen: int | None = None) -> Site:
    return Site(
        id=sid,
        name=sid,
        homepage="https://s1.test/",
        kinds=["网盘"],
        langs={"zh"},
        url_searchable=True,
        max_query_len=maxlen,
        search=SearchSpec(mode="url", url_template="https://s1.test/?s={q}"),
    )


class _FakePage:
    def close(self):
        pass


class _FakeSession:
    """替代 BrowserSession：不碰浏览器。"""

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


def _stub_search_one(monkeypatch, calls: list, result_factory):
    """把 search_one 换成记录调用的假实现。"""

    def fake(page, site, query, timeout_ms=45000):
        calls.append((site.id, query))
        return result_factory(site, query)

    monkeypatch.setattr(pipeline, "search_one", fake)


def test_normalize_query_collapses_whitespace_and_case():
    assert pipeline.normalize_query("  Ender   Lilies  ") == "ender lilies"
    assert pipeline.normalize_query("终焉之莉莉") == "终焉之莉莉"
    assert pipeline.normalize_query("") == ""
    assert pipeline.normalize_query(None) == ""


def test_second_run_hits_cache_and_skips_search(monkeypatch, fake_browser, tmp_path):
    calls: list = []
    _stub_search_one(
        monkeypatch, calls,
        lambda site, q: GameDetail(
            site_id=site.id, url="https://s1.test/1", title="终结的百合花",
            downloads=[Download(kind="pan", url="https://pan.baidu.com/s/x")],
        ),
    )

    with Store(tmp_path / "c.db", ttl_hours=12) as st:
        first = pipeline.run({}, [_site()], "终焉之莉莉", tmp_path, store=st)
        second = pipeline.run({}, [_site()], "终焉之莉莉", tmp_path, store=st)

    assert len(calls) == 1, f"第二次不该再搜，实际调用了 {len(calls)} 次"
    assert first[0].extra.get("cached") is None
    assert second[0].extra["cached"] is True
    assert second[0].title == "终结的百合花"
    assert len(second[0].downloads) == 1
    assert second[0].downloads[0].kind == "pan"


def test_failures_are_cached_only_briefly(monkeypatch, fake_browser, tmp_path):
    """失败结果短缓存（默认 30min），不是不缓存也不是 12h。

    设计变更记录：最初实现是「失败完全不缓存」，实测发现 11 站里 6 个是
    失败站、占掉约 28s，导致重复搜索几乎和首次一样慢；改为短 TTL 后重复
    搜索能瞬时返回，同时站点恢复后最多等 30 分钟就能重试。
    """
    calls: list = []
    _stub_search_one(
        monkeypatch, calls,
        lambda site, q: GameDetail(
            site_id=site.id, url="https://s1.test/", title="",
            error="NO_RESULTS: nothing found",
        ),
    )

    with Store(tmp_path / "c.db", ttl_hours=12) as st:
        pipeline.run({}, [_site()], "终焉之莉莉", tmp_path, store=st)
        second = pipeline.run({}, [_site()], "终焉之莉莉", tmp_path, store=st)

    assert len(calls) == 1, "失败结果应短缓存，不该每次都重搜"
    assert second[0].error is not None, "缓存住的失败仍要如实报错，不能洗白"
    assert second[0].extra["cached"] is True


def test_use_cache_false_forces_fresh_search(monkeypatch, fake_browser, tmp_path):
    calls: list = []
    _stub_search_one(
        monkeypatch, calls,
        lambda site, q: GameDetail(site_id=site.id, url="u", title="t"),
    )

    with Store(tmp_path / "c.db", ttl_hours=12) as st:
        pipeline.run({}, [_site()], "x", tmp_path, store=st)
        pipeline.run({}, [_site()], "x", tmp_path, store=st, use_cache=False)

    assert len(calls) == 2


def test_cache_key_uses_clamped_query(monkeypatch, fake_browser, tmp_path):
    """acggw 有 max_query_len=10：超长查询被截断后应与短查询共用同一条缓存。"""
    calls: list = []
    _stub_search_one(
        monkeypatch, calls,
        lambda site, q: GameDetail(site_id=site.id, url="u", title="t"),
    )
    site = _site(maxlen=10)

    with Store(tmp_path / "c.db", ttl_hours=12) as st:
        pipeline.run({}, [site], "0123456789ABCDEF", tmp_path, store=st)
        pipeline.run({}, [site], "0123456789", tmp_path, store=st)

    assert len(calls) == 1, f"截断后应命中同一缓存，实际 {len(calls)} 次"
    # run() 把原始词交给 search_one，截断在 search_one 内部做（它自己调
    # clamp_query）。缓存键才是截断后的值 —— 这里验证的正是键的一致性。
    assert calls[0][1] == "0123456789ABCDEF"


def test_store_none_disables_cache(monkeypatch, fake_browser, tmp_path):
    calls: list = []
    _stub_search_one(
        monkeypatch, calls,
        lambda site, q: GameDetail(site_id=site.id, url="u", title="t"),
    )
    pipeline.run({}, [_site()], "x", tmp_path)
    pipeline.run({}, [_site()], "x", tmp_path)
    assert len(calls) == 2


def test_cache_is_per_site(monkeypatch, fake_browser, tmp_path):
    """两个站的结果不能串味。"""
    calls: list = []
    _stub_search_one(
        monkeypatch, calls,
        lambda site, q: GameDetail(site_id=site.id, url=f"https://{site.id}/1",
                                   title=f"title-{site.id}"),
    )
    sites = [_site("a"), _site("b")]

    with Store(tmp_path / "c.db", ttl_hours=12) as st:
        first = pipeline.run({}, sites, "q", tmp_path, store=st)
        second = pipeline.run({}, sites, "q", tmp_path, store=st)

    assert [d.site_id for d in first] == ["a", "b"]
    assert [d.site_id for d in second] == ["a", "b"]
    assert second[0].title == "title-a"
    assert second[1].title == "title-b"
    assert len(calls) == 2
