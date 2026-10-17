from pathlib import Path

import pytest

from finder.models import SearchHit, SearchSpec, Site
from finder.search import (
    ASSET_RE,
    build_search_url,
    clamp_query,
    parse_result_links,
    pick_best,
)

FIX = Path(__file__).resolve().parent / "fixtures"


def _site(mode="url", tpl="https://e.com/?s={q}", maxlen=None, sid="e"):
    return Site(id=sid, name=sid, homepage="https://e.com/", kinds=[], langs={"zh"},
                url_searchable=(mode == "url"),
                search=SearchSpec(mode=mode, url_template=tpl),
                max_query_len=maxlen)


def test_build_search_url_encodes_cjk():
    s = _site()
    url = build_search_url(s, "终焉之莉莉")
    assert "?" in url and "%" in url          # 被 URL 编码
    assert "终焉" not in url                  # 原始中文不应出现
    assert url.startswith("https://e.com/?s=")


def test_build_search_url_form_mode_raises():
    s = _site(mode="form")
    with pytest.raises(ValueError):
        build_search_url(s, "x")


def test_clamp_query_truncates_to_site_limit():
    s = _site(maxlen=10)
    q, truncated = clamp_query(s, "终焉之莉莉终焉之莉莉终焉之莉莉")   # 15 字
    assert len(q) == 10
    assert truncated is True


def test_clamp_query_no_limit_keeps_full():
    s = _site(maxlen=None)
    q, truncated = clamp_query(s, "终焉之莉莉")
    assert q == "终焉之莉莉"
    assert truncated is False


def test_parse_result_links_from_jidi_fixture():
    html = (FIX / "jidiyouxi" / "search_ai.html").read_text(encoding="utf-8")
    s = _site(tpl="https://www.jidiyouxi.com/search/detail/{q}", sid="jidiyouxi")
    hits = parse_result_links(html, "https://www.jidiyouxi.com/search/detail/AI", s)
    assert hits, "jidiyouxi search page must yield hits"
    assert all("jidiyouxi.com" in h.url for h in hits)
    # Task 7 基线：43 条（40 条 /topic/detail/ 详情页 + 3 条站点导航），
    # 零静态资源泄漏；相对路径已 urljoin 成绝对 URL。
    assert len(hits) == 43
    detail = [h for h in hits if h.score == 1.0]
    assert len(detail) == 40
    assert all("/topic/detail/" in h.url for h in detail)
    assert all(h.url.startswith("https://") for h in hits)
    assert not any("/undefined" in h.url for h in hits)
    assert not any(ASSET_RE.search(h.url) for h in hits)


def test_parse_result_links_joins_relative_hrefs():
    """线上 jidiyouxi 的结果链接是相对路径（Task 7 实测），必须 urljoin。

    旧实现只收 http 开头的 href，真站上 hit=0。
    """
    html = (
        '<a href="/topic/detail/959615543">终焉之莉莉：骑士寂夜</a>'
        '<a href="/topic/detail/undefined">占位</a>'
        '<a href="#top">top</a>'
    )
    s = _site(tpl="https://www.jidiyouxi.com/search/detail/{q}", sid="jidiyouxi")
    hits = parse_result_links(html, "https://www.jidiyouxi.com/search/detail/x", s)
    assert [h.url for h in hits] == ["https://www.jidiyouxi.com/topic/detail/959615543"]
    assert hits[0].title.startswith("终焉之莉莉")


def test_parse_result_links_from_g520_fixture():
    html = (FIX / "gamer520" / "search_ai.html").read_text(encoding="utf-8")
    s = _site(tpl="https://www.gamer520.com/?s={q}", sid="gamer520")
    hits = parse_result_links(html, "https://www.gamer520.com/?s=AI", s)
    assert hits, "gamer520 search page must yield hits"
    assert any(h.url.rstrip('/').endswith('.html') for h in hits)
    # Task 7 基线：31 条（22 条详情页 + 9 条导航），零静态资源泄漏。
    assert len(hits) == 31
    assert not any(ASSET_RE.search(h.url) for h in hits)
    # pick_best 必须选到真实文章，而不是 /pcplay 分类页。
    best = pick_best(hits, "AI")
    assert best is not None
    assert best.url == "https://www.gamer520.com/90467.html"


def test_pick_best_prefers_title_match():
    hits = [
        SearchHit("x", "完全无关的内容", "https://e.com/1"),
        SearchHit("x", "终焉之莉莉 Ender Lilies", "https://e.com/2"),
        SearchHit("x", "其他游戏", "https://e.com/3"),
    ]
    best = pick_best(hits, "终焉之莉莉")
    assert best is not None
    assert best.url == "https://e.com/2"


def test_pick_best_latin_query_uses_word_boundary():
    """短查询 "AI" 不能命中 "Chained" 里的 "ai"（Task 7 实测的误选）。"""
    hits = [
        SearchHit("x", "链兽角斗 Chained Beasts|官方中文", "https://e.com/1", 1.0),
        SearchHit("x", "AI LIMIT 无限机兵|豪华中文", "https://e.com/2", 1.0),
    ]
    best = pick_best(hits, "AI")
    assert best is not None
    assert best.url == "https://e.com/2"


def test_pick_best_prefers_title_start_over_later_mention():
    hits = [
        SearchHit("x", "Switch 固件合集 AI 工具包", "https://e.com/1", 1.0),
        SearchHit("x", "AI LIMIT 无限机兵", "https://e.com/2", 1.0),
    ]
    best = pick_best(hits, "AI")
    assert best is not None
    assert best.url == "https://e.com/2"


def test_pick_best_returns_none_on_empty():
    assert pick_best([], "x") is None
