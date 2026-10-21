"""搜索引擎兜底链接：只拼跳转 URL，不发请求、不解析引擎结果页。

用户要求（原文，m01166）：
  「增加功能，如果出来的结果少于三个，在必应、百度、谷歌、Yandex也进行搜索和整合，
    不过不用给出结果，给跳转链接就行」

确认过的三个口径（ask_user_question，m01187）：
  1. 触发条件 = **有下载链接的站点数 < 3**（「找到但没链接」「未找到」都不算）
  2. 传给引擎的 q = **用户输入原样**，不追加 galgame / 下载 之类的词
  3. UI 位置 = 结果区上方单独一块，不混进卡片列表

这个模块是纯函数集合：`engine_links()` 的产物直接进 SSE 帧，因此它必须
(a) 对任意输入都不抛异常，(b) 把查询词正确转义（含 CJK / 空格 / & / #），
(c) 顺序稳定（必应 → 百度 → 谷歌 → Yandex）。
"""
from __future__ import annotations

from urllib.parse import quote

import pytest

from finder.engines import (
    ENGINES,
    MIN_LINKED_SITES,
    engine_links,
    linked_site_count,
    needs_fallback,
)
from finder.models import Download, GameDetail


def _card(site_id: str, downloads: list[Download] | None = None,
          error: str | None = None) -> GameDetail:
    return GameDetail(site_id=site_id, url=f"https://{site_id}.test/x",
                      title=site_id, downloads=downloads or [], error=error)


# ---------------------------------------------------------------------------
# 常量：阈值与引擎清单
# ---------------------------------------------------------------------------
def test_threshold_is_three():
    """用户原话「少于三个」→ 阈值就是 3，改成别的值必须有意识地改这个测试。"""
    assert MIN_LINKED_SITES == 3


def test_four_engines_in_the_requested_order():
    """用户点名的顺序：必应、百度、谷歌、Yandex。"""
    assert [e.id for e in ENGINES] == ["bing", "baidu", "google", "yandex"]
    assert [e.name for e in ENGINES] == ["必应", "百度", "谷歌", "Yandex"]


def test_each_engine_has_its_measured_search_url():
    """每个引擎的搜索入口都是实测可用的那个域名 + 参数名，别凭印象改。"""
    urls = {e.id: e.url_template for e in ENGINES}
    assert urls["bing"] == "https://www.bing.com/search?q={q}"
    assert urls["baidu"] == "https://www.baidu.com/s?wd={q}"
    assert urls["google"] == "https://www.google.com/search?q={q}"
    assert urls["yandex"] == "https://yandex.com/search/?text={q}"


# ---------------------------------------------------------------------------
# engine_links：只拼 URL
# ---------------------------------------------------------------------------
def test_engine_links_returns_four_dicts():
    links = engine_links("enderlilies")
    assert len(links) == 4
    assert [x["id"] for x in links] == ["bing", "baidu", "google", "yandex"]
    for x in links:
        assert set(x) == {"id", "name", "url"}
        assert x["url"].startswith("https://")


def test_query_is_used_verbatim():
    """用户输入原样传过去 —— 不追加 galgame / 下载 / 引号。"""
    links = engine_links("enderlilies")
    assert links[0]["url"] == "https://www.bing.com/search?q=enderlilies"
    assert links[2]["url"] == "https://www.google.com/search?q=enderlilies"


def test_space_is_encoded_as_percent20_not_plus():
    """`+` 在部分引擎里是字面加号；统一用 %20 才不会搜出别的东西。"""
    links = engine_links("summer clover")
    assert "%20" in links[0]["url"]
    assert "+" not in links[0]["url"]


def test_cjk_query_is_percent_encoded():
    links = engine_links("终焉之莉莉")
    q = quote("终焉之莉莉", safe="")
    for x in links:
        assert q in x["url"]
        assert "终焉" not in x["url"], "URL 里不能留原始 CJK（编码必须完成）"


@pytest.mark.parametrize("raw", [
    "a&b", "a#b", "a?b", "a=b", "a/b", "a%b", "a+b", 'a"b', "a b",
])
def test_special_characters_cannot_break_the_url(raw):
    """& 会截断参数、# 会变片段、% 会破坏百分号编码 —— 全部必须转义。"""
    links = engine_links(raw)
    expected = quote(raw, safe="")
    for x in links:
        assert expected in x["url"]
    assert "?" not in links[0]["url"].split("q=", 1)[1], "参数值里不能有未转义的 ?"


def test_leading_and_trailing_space_is_stripped():
    """前端已经 strip 过一次，这里再来一次 —— 保证 URL 里不会出现 %20 开头/结尾。"""
    links = engine_links("  summer clover  ")
    assert links[0]["url"] == "https://www.bing.com/search?q=summer%20clover"


def test_empty_query_still_returns_links_without_raising():
    """空查询不该抛：帧仍然要能发出去（UI 会把它当普通兜底块显示）。"""
    links = engine_links("")
    assert len(links) == 4
    for x in links:
        assert x["url"].startswith("https://")
        assert "{q}" not in x["url"]


def test_none_query_does_not_raise():
    links = engine_links(None)  # type: ignore[arg-type]
    assert len(links) == 4


# ---------------------------------------------------------------------------
# linked_site_count / needs_fallback
# ---------------------------------------------------------------------------
def test_zero_results_needs_fallback():
    assert linked_site_count([]) == 0
    assert needs_fallback([]) == (True, 0)


def test_three_linked_sites_is_enough():
    cards = [
        _card("a", [Download(kind="pan", url="https://pan.baidu.com/s/1")]),
        _card("b", [Download(kind="direct", url="https://x.test/a.zip")]),
        _card("c", [Download(kind="magnet", url="magnet:?xt=urn:btih:" + "a" * 40)]),
    ]
    assert linked_site_count(cards) == 3
    assert needs_fallback(cards) == (False, 3)


def test_two_linked_sites_triggers_fallback():
    cards = [
        _card("a", [Download(kind="pan", url="https://pan.baidu.com/s/1")]),
        _card("b", [Download(kind="direct", url="https://x.test/a.zip")]),
    ]
    assert needs_fallback(cards) == (True, 2)


def test_found_but_no_links_does_not_count():
    """「站点找到游戏但抽不到链接」和「未找到」都不算 —— 用户拿不到资源。"""
    cards = [
        _card("a", [], error="NO_DOWNLOADS: only comments"),
        _card("b", [], error="NO_RESULTS: 未找到相關內容"),
        _card("c", [], error=None),          # no_links：没错但也没链接
        _card("d", [Download(kind="pan", url="https://pan.baidu.com/s/1")]),
    ]
    assert linked_site_count(cards) == 1
    assert needs_fallback(cards) == (True, 1)


def test_site_with_three_downloads_counts_once():
    """计数单位是**站点**，同一站给 3 条网盘也只算 1 个。"""
    cards = [
        _card("a", [Download(kind="pan", url=f"https://pan.baidu.com/s/{i}")
                    for i in range(3)]),
        _card("b", [Download(kind="pan", url="https://pan.quark.cn/s/x")]),
    ]
    assert linked_site_count(cards) == 2


def test_unknown_kind_still_counts_as_a_link():
    """`kind` 判不准但 URL 有了，对用户仍然是可用链接 —— 不能被漏掉。"""
    cards = [_card("a", [Download(kind="unknown", url="https://x.test/f")])]
    assert linked_site_count(cards) == 1


def test_none_fields_do_not_raise():
    """NO_RESULTS 实测形状是 downloads 为空 / url=None，任何字段为 None 都不该炸。"""
    cards = [GameDetail(site_id="a", url=None, title="", downloads=None)]  # type: ignore[arg-type]
    assert linked_site_count(cards) == 0
    assert needs_fallback(cards)[0] is True
