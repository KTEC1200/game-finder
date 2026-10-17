"""index 模式（sayafx /search.xml）与 filehost / 跳板解码的测试。"""
from __future__ import annotations

import base64

from finder.detail import decode_gb_dl_links, extract_downloads
from finder.models import SearchSpec, Site
from finder.pipeline import hits_from_index, parse_search_index

INDEX_XML = """<?xml version="1.0" encoding="utf-8"?>
<search>
  <entry>
    <title>【官中】【汉化】千恋＊万花／千恋万花／Senren＊Banka</title>
    <url>/aaaa1111/</url>
  </entry>
  <entry>
    <title>【日文硬盘】制服カノジョ</title>
    <url>/bbbb2222/</url>
  </entry>
  <entry>
    <title>【安卓】苍之彼方的四重奏：交予世界的答卷[同人作品]</title>
    <url>/cccc3333/</url>
  </entry>
</search>
"""


def _index_site() -> Site:
    return Site(
        id="sayafx",
        name="月谣",
        homepage="https://www.sayafx.vip/",
        kinds=["直链"],
        langs={"zh", "ja"},
        url_searchable=False,
        search=SearchSpec(mode="index", index_url="https://www.sayafx.vip/search.xml"),
    )


def test_parse_search_index_extracts_title_and_url():
    entries = parse_search_index(INDEX_XML)
    assert len(entries) == 3
    assert entries[0][1] == "/aaaa1111/"
    assert "千恋" in entries[0][0]


def test_parse_search_index_tolerates_garbage():
    assert parse_search_index("") == []
    assert parse_search_index("<html>not an index</html>") == []


def test_hits_from_index_matches_full_query():
    entries = parse_search_index(INDEX_XML)
    hits = hits_from_index(entries, _index_site(), "千恋万花",
                           "https://www.sayafx.vip/")
    assert len(hits) == 1
    assert hits[0].url == "https://www.sayafx.vip/aaaa1111/"
    assert hits[0].score == 1.0


def test_hits_from_index_matches_japanese_title():
    entries = parse_search_index(INDEX_XML)
    hits = hits_from_index(entries, _index_site(), "制服カノジョ",
                           "https://www.sayafx.vip/")
    assert len(hits) == 1
    assert "/bbbb2222/" in hits[0].url


def test_hits_from_index_returns_empty_when_absent():
    """实测：索引里确实没有「终焉之莉莉」，必须老实返回空，不能模糊凑数。"""
    entries = parse_search_index(INDEX_XML)
    assert hits_from_index(entries, _index_site(), "终焉之莉莉",
                           "https://www.sayafx.vip/") == []


def test_hits_from_index_does_not_match_single_char_overlap():
    """逐字模糊匹配会让「终焉之莉莉」命中 118 条无关条目（实测）。

    这里用「莉莉」这种两字片段验证：只认整词/全词，不做单字拼凑。
    """
    entries = parse_search_index(INDEX_XML)
    assert hits_from_index(entries, _index_site(), "终焉之莉莉",
                           "https://www.sayafx.vip/") == []


def test_hits_from_index_multiword_query_needs_all_words():
    entries = parse_search_index(INDEX_XML)
    assert hits_from_index(entries, _index_site(), "千恋 万花",
                           "https://www.sayafx.vip/")
    assert hits_from_index(entries, _index_site(), "千恋 不存在的词",
                           "https://www.sayafx.vip/") == []


def test_hits_from_index_respects_limit():
    entries = [("同一款游戏 终焉之莉莉", f"/{i}/") for i in range(30)]
    hits = hits_from_index(entries, _index_site(), "终焉之莉莉",
                           "https://www.sayafx.vip/", limit=5)
    assert len(hits) == 5


# ---- gamebounty 的 /api/dl 跳板解码 ----

def _wrap(real: str) -> str:
    b = base64.urlsafe_b64encode(real.encode()).decode().rstrip("=")
    return f"https://gamebounty.world/api/dl/some-slug/{b}"


def test_decode_gb_dl_links_unwraps_base64():
    real = "https://pixeldrain.com/u/We8HvSTc"
    html = f'<a href="{_wrap(real)}">下载完整游戏</a>'
    assert decode_gb_dl_links(html) == [real]


def test_decode_gb_dl_links_handles_padding():
    for real in ("https://gofile.io/d/OwkZrd",
                 "https://fileditchfiles.me/beta9/x/ENDER.rar"):
        html = f'<a href="{_wrap(real)}">x</a>'
        assert decode_gb_dl_links(html) == [real], real


def test_decode_gb_dl_links_ignores_unwrappable():
    html = '<a href="/api/dl/slug/!!!not-base64!!!">x</a>'
    assert decode_gb_dl_links(html) == []


def test_extract_downloads_unwraps_gb_gate_and_drops_the_wrapper():
    """跳板本身不是下载链接：只留解码后的真链，否则用户点开是个 JSON 接口。"""
    real = "https://pixeldrain.com/u/We8HvSTc"
    html = f'<html><body><a href="{_wrap(real)}">下载完整游戏</a></body></html>'
    dl = extract_downloads(html, "https://gamebounty.world/x")
    urls = [d.url for d in dl]
    assert real in urls
    assert not any("/api/dl/" in u for u in urls)


def test_extract_downloads_keeps_filehost_links():
    """anime-sharing 实测：帖子只给 rapidgator / katfile 直链。"""
    html = (
        '<html><body>'
        '<a href="https://rapidgator.net/file/abc/GAME.part1.rar">PART1</a>'
        '<a href="https://katfile.biz/xyz/GAME.part1.rar.html">PART1</a>'
        '</body></html>'
    )
    dl = extract_downloads(html, "https://www.anime-sharing.com/threads/x/")
    kinds = {d.kind for d in dl}
    assert "filehost" in kinds
    assert len([d for d in dl if d.kind == "filehost"]) == 2
