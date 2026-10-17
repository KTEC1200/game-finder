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
    # 实测基线：41 条，全部是 /topic/detail/ 详情页，零静态资源泄漏。
    assert len(hits) == 41
    assert all("/topic/detail/" in h.url for h in hits)
    assert not any(ASSET_RE.search(h.url) for h in hits)


def test_parse_result_links_from_g520_fixture():
    html = (FIX / "gamer520" / "search_ai.html").read_text(encoding="utf-8")
    s = _site(tpl="https://www.gamer520.com/?s={q}", sid="gamer520")
    hits = parse_result_links(html, "https://www.gamer520.com/?s=AI", s)
    assert hits, "gamer520 search page must yield hits"
    assert any(h.url.rstrip('/').endswith('.html') for h in hits)
    # 实测基线：35 条，零静态资源泄漏（NAV_RE/ASSET_RE 修正前是 39 条含 css/js）。
    assert len(hits) == 35
    assert not any(ASSET_RE.search(h.url) for h in hits)
    # pick_best 必须选到真实文章，而不是 /pcplay 分类页。
    best = pick_best(hits, "AI")
    assert best is not None
    assert best.url == "https://www.gamer520.com/122908.html"


def test_pick_best_prefers_title_match():
    hits = [
        SearchHit("x", "完全无关的内容", "https://e.com/1"),
        SearchHit("x", "终焉之莉莉 Ender Lilies", "https://e.com/2"),
        SearchHit("x", "其他游戏", "https://e.com/3"),
    ]
    best = pick_best(hits, "终焉之莉莉")
    assert best is not None
    assert best.url == "https://e.com/2"


def test_pick_best_returns_none_on_empty():
    assert pick_best([], "x") is None
