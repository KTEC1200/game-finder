"""缺陷 1：查询词在拉丁词中间被截断时，不要拿半截词去搜，直接跳过该站。

真站现场（2026-10-18，acggw `max_query_len: 10`）：
    用户查 `summer clover`（13 字）→ 被截成 `summer clo`
    acggw 的 token 命中 summer=YES / clo=NO，但整句 `summer clo` 是页面里
    `Summer Clover` 的子串 → 「整句匹配」挡不住 → 用户看到**别的游戏**。

判定：`truncated` 且 `query[limit-1].isalnum() and query[limit].isalnum()`
且查询不含 CJK/假名（CJK 没有词边界，硬截断可接受）。
"""
import pytest

from finder.models import SearchSpec, Site
from finder.pipeline import search_one
from finder.search import clamp_query, clamp_query_detail


def _site(max_query_len=None, mode="url", **search_kwargs) -> Site:
    if mode == "url":
        spec = SearchSpec(mode="url", url_template="https://acg.test/search?q={q}", **search_kwargs)
    elif mode == "index":
        spec = SearchSpec(mode="index", index_url="https://acg.test/search.xml", **search_kwargs)
    else:
        spec = SearchSpec(mode="form", form_url="https://acg.test/search", **search_kwargs)
    return Site(
        id="acgtest",
        name="ACGTest",
        homepage="https://acg.test/",
        kinds=["网盘"],
        langs={"zh", "en"},
        url_searchable=mode == "url",
        search=spec,
        max_query_len=max_query_len,
    )


# ---- clamp_query_detail 的边界（真数据 / 边界 / CJK 例外）---------------------

def test_mid_word_cut_detected_for_summer_clover():
    """真站数据：`summer clover` limit=10 → `summer clo`，切在 o|v 中间。"""
    q, truncated, mid = clamp_query_detail(_site(max_query_len=10), "summer clover")
    assert q == "summer clo"
    assert truncated is True
    assert mid is True


def test_mid_word_cut_detected_for_enderlilies():
    """`enderlilies`（11 字）limit=10 → `enderlilie`，同样切在词中间。"""
    q, truncated, mid = clamp_query_detail(_site(max_query_len=10), "enderlilies")
    assert q == "enderlilie"
    assert truncated is True
    assert mid is True


def test_no_mid_word_cut_when_query_fits_exactly_within_limit():
    """刚好等于上限不截断 → 不触发。"""
    q, truncated, mid = clamp_query_detail(_site(max_query_len=10), "enderlili")
    assert q == "enderlili"
    assert truncated is False
    assert mid is False


def test_no_mid_word_cut_when_query_shorter_than_limit():
    q, truncated, mid = clamp_query_detail(_site(max_query_len=10), "ender")
    assert (q, truncated, mid) == ("ender", False, False)


def test_no_mid_word_cut_without_site_limit():
    q, truncated, mid = clamp_query_detail(_site(max_query_len=None), "summer clover")
    assert (q, truncated, mid) == ("summer clover", False, False)


def test_no_mid_word_cut_when_cut_lands_on_a_space():
    """截断点正好落在空格后 → 拿到的是一整个词，允许。"""
    q, truncated, mid = clamp_query_detail(_site(max_query_len=7), "summer clover")
    assert q == "summer "
    assert truncated is True
    assert mid is False


def test_no_mid_word_cut_when_the_cut_lands_after_a_whole_token():
    """`summer clo ver` limit=10 → `summer clo`，下一字符是空格 → 截下的是完整词。"""
    q, truncated, mid = clamp_query_detail(_site(max_query_len=10), "summer clo ver")
    assert q == "summer clo"
    assert truncated is True
    assert mid is False  # query[9]='o' 但 query[10]=' '：`clo` 本来就是查询里的一个完整词


def test_cjk_truncation_is_never_mid_word():
    """CJK 没有词边界（且 `'莉'.isalnum()` 为真），硬截断必须照旧放行。"""
    q, truncated, mid = clamp_query_detail(_site(max_query_len=10), "终焉之莉莉终焉之莉莉终焉之莉莉")
    assert truncated is True
    assert mid is False
    q2, t2, m2 = clamp_query_detail(_site(max_query_len=4), "终焉之莉莉")
    assert (q2, t2, m2) == ("终焉之莉", True, False)


def test_kana_truncation_is_never_mid_word():
    q, truncated, mid = clamp_query_detail(_site(max_query_len=4), "エンダーリリー")
    assert truncated is True
    assert mid is False


def test_mixed_cjk_latin_query_follows_cjk_rule():
    """混合查询走 CJK 规则：不因为拉丁词被切断就跳过。"""
    q, truncated, mid = clamp_query_detail(_site(max_query_len=10), "summer clover 四叶草")
    assert q == "summer clo"
    assert truncated is True
    assert mid is False


def test_clamp_query_keeps_its_old_two_value_contract():
    site = _site(max_query_len=10)
    assert clamp_query(site, "summer clover") == ("summer clo", True)
    assert clamp_query(site, "ender") == ("ender", False)


# ---- search_one：三种模式都要在截断到词中间时跳过 ----------------------------

class _NoNavPage:
    """记录被访问过的 URL；一旦被 goto 就记下来（本缺陷要求「不许去搜」）。"""

    def __init__(self):
        self.visited = []
        self.url = "about:blank"

    def goto(self, url, **kw):
        self.visited.append(url)
        self.url = url
        return type("_R", (), {"status": 200})()

    def wait_for_load_state(self, *a, **kw):
        pass

    def wait_for_timeout(self, *a, **kw):
        pass


@pytest.mark.parametrize("mode", ["url", "index", "form"])
def test_search_one_skips_site_when_mid_word_cut(mode):
    page = _NoNavPage()
    card = search_one(page, _site(max_query_len=10, mode=mode), "summer clover", timeout_ms=500)
    assert card.error is not None
    assert card.error.startswith("QUERY_TOO_LONG:")
    assert "summer clo" in card.error
    assert card.downloads == []
    assert card.extra["query_truncation"] == "mid_word"
    assert card.extra["query_used"] == "summer clo"
    assert page.visited == [], "截断到词中间就不该再发起任何搜索请求"


def test_search_one_still_searches_when_truncation_is_clean():
    """CJK 超长查询照旧截断后去搜（acggw 正常路径，不能因本修复被跳过）。"""
    page = _NoNavPage()
    card = search_one(page, _site(max_query_len=10), "终焉之莉莉终焉之莉莉终焉之莉莉", timeout_ms=500)
    assert not (card.error or "").startswith("QUERY_TOO_LONG:")
    assert page.visited, "CJK 截断应该照常搜索"
