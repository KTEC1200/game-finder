"""缺陷 2：拉丁查询的证据门从「命中任一 token」收紧成「>=3 字的 token 全中」。

真站实测（2026-10-18）：
| 站        | 查询            | token 命中            | 旧闸门 `>0` | 新闸门（全中） |
|-----------|-----------------|-----------------------|-------------|----------------|
| acggw     | `summer clo`    | summer=YES, clo=NO    | 误放行 ❌   | 拦下 ✅        |
| galgamex  | `summer clover` | summer=YES, clover=YES| 放行        | 放行 ✅        |

CJK 查询保持 required=1（跨译名：查「终焉之莉莉」要能命中「终结的百合花」）。
`_query_evidence` 的旧回传语义不变（仍有测试与诊断用）。
"""
import pytest

from finder.detail import extract_card
from finder.models import SearchSpec, Site
from finder.pipeline import _query_evidence, _query_evidence_ok


# ---- 真站数据（lead 实测的两组）---------------------------------------------

@pytest.mark.parametrize(
    "query,title,body,ok,found,required",
    [
        # acggw 实测：截断后的 `summer clo` —— summer 命中、clo 不命中
        ("summer clo", "夏色四叶草", "Summer Clover 夏色四叶草 galgame", False, 1, 2),
        # galgamex 实测：未截断的 `summer clover` —— 两个都命中
        ("summer clover", "夏色四叶草 | 夏色クローバー", "summer clover", True, 2, 2),
    ],
)
def test_real_site_evidence_matrix(query, title, body, ok, found, required):
    got = _query_evidence_ok(query, title, body)
    assert got == (ok, found, required)
    # 旧函数语义不变：仍返回命中数（acggw 那组是 1，不是 0）
    assert _query_evidence(query, title, body) == found


def test_acggw_page_really_contains_summer_clover():
    """说明为什么旧闸门会误放行：整句 `summer clo` 是 `Summer Clover` 的子串。"""
    body = "Summer Clover 夏色四叶草"
    assert "summer clo" in body.lower()
    assert _query_evidence_ok("summer clo", "", body)[0] is False


# ---- token 语义 ---------------------------------------------------------------

def test_partial_token_hit_is_not_enough():
    assert _query_evidence_ok("ender lilies requiem", "", "Ender Lilies") == (False, 2, 3)


def test_all_tokens_present_passes():
    assert _query_evidence_ok("ender lilies", "", "Ender Lilies: Quietus") == (True, 2, 2)


def test_short_tokens_are_ignored_for_the_required_count():
    """<3 字的 token 不计入门槛（`ai` 命中 `chained` 那类噪声）。"""
    ok, found, required = _query_evidence_ok("senren banka", "", "Senren Banka")
    assert (ok, required) == (True, 2)
    ok2, found2, required2 = _query_evidence_ok("ai senren banka", "", "Senren Banka")
    assert required2 == 2  # `ai` 不算 required
    assert ok2 is True


def test_query_without_long_tokens_falls_back_to_required_one():
    """`AI` 这种全是短词的查询：required=1，命中一个也算过（否则永远 0）。"""
    assert _query_evidence_ok("AI", "", "some ai article") == (True, 1, 1)
    assert _query_evidence_ok("AI", "", "unrelated page") == (False, 0, 1)


def test_latin_token_needs_a_word_boundary():
    """3-4 字的词不做紧致匹配：`clo` 不能命中 `clover`（这正是 acggw 的要害）。"""
    assert _query_evidence_ok("clo ver", "", "clover version") == (False, 0, 2)
    assert _query_evidence_ok("clo ver", "", "clo ver 分别出现") == (True, 2, 2)


def test_long_token_may_match_ignoring_separators():
    """>=5 字的词允许「去掉分隔符后整串命中」：enderlilies 要能对上 Ender Lilies。"""
    assert _query_evidence_ok("enderlilies", "", "Ender Lilies: Quietus of the Knights")[0] is True


# ---- CJK / 假名 ---------------------------------------------------------------

def test_cjk_requires_one_distinct_char():
    ok, found, required = _query_evidence_ok("终焉之莉莉", "终结的百合花", "终结的百合花：骑士们的救赎")
    assert ok is True
    assert required == 1
    assert found >= 1


def test_cjk_unrelated_page_is_rejected():
    ok, found, required = _query_evidence_ok("终焉之莉莉", "固件整合包", "固件更新说明 大气层")
    assert ok is False
    assert required == 1
    assert found == 0


def test_mixed_query_follows_cjk_rule():
    """混合查询（含 CJK）走 CJK 规则：required=1，不会因为英文没全中而误杀。"""
    ok, found, required = _query_evidence_ok("summer clover 夏色", "夏色四叶草", "")
    assert required == 1
    assert ok is True


def test_empty_haystack_and_empty_query_never_pass():
    assert _query_evidence_ok("enderlilies", "", "") == (False, 0, 1)
    assert _query_evidence_ok("", "Ender Lilies", "正文") == (False, 0, 1)


# ---- 闸门接进管线：截断查询不再挂上别的游戏 ----------------------------------

class _FakePage:
    def __init__(self, pages):
        self._pages = pages
        self.url = "about:blank"

    def goto(self, url, **kw):
        self.url = url
        return type("_R", (), {"status": 200})()

    def wait_for_load_state(self, *a, **kw):
        pass

    def wait_for_timeout(self, *a, **kw):
        pass

    def content(self):
        return (self._pages.get(self.url) or self._pages["*"])["html"]

    def title(self):
        return (self._pages.get(self.url) or self._pages["*"]).get("title", "")

    def evaluate(self, script):
        return (self._pages.get(self.url) or self._pages["*"]).get("text", "")


SEARCH_HTML = (
    "<html><body><h2>搜索结果</h2>"
    '<a href="/game/cbe7d89e">夏色四叶草 | 夏色クローバー</a>'
    "</body></html>"
)
DETAIL_HTML = (
    '<html><head><meta property="og:title" content="夏色四叶草 | 夏色クローバー"></head>'
    "<body><p>summer clover</p>"
    '<a href="https://pan.baidu.com/s/1aCmoplMimsXAb16i9tfP_A?pwd=us6i">百度网盘</a>'
    "</body></html>"
)


def _galx_site(flow=None) -> Site:
    return Site(
        id="galgamex",
        name="Galgamex",
        homepage="https://www.galgamex.net/",
        kinds=["网盘"],
        langs={"zh", "en"},
        url_searchable=True,
        search=SearchSpec(
            mode="url", url_template="https://www.galgamex.net/search?q={q}", download_flow=flow
        ),
    )


def _page(query_url_html: str) -> _FakePage:
    return _FakePage(
        {
            query_url_html: {"html": SEARCH_HTML, "title": "搜索"},
            "https://www.galgamex.net/game/cbe7d89e": {
                "html": DETAIL_HTML,
                "title": "夏色四叶草 | 夏色クローバー",
                "text": "summer clover",
            },
            "*": {"html": "", "title": "", "text": ""},
        }
    )


def test_pipeline_rejects_when_only_one_of_two_tokens_matches():
    """用户真查 `summer clo`（非截断站）：页面上只有 Summer Clover → 不能挂链接。"""
    from finder.pipeline import search_one

    card = search_one(_page("https://www.galgamex.net/search?q=summer%20clo"),
                      _galx_site(), "summer clo", timeout_ms=500)
    assert card.error is not None
    assert card.error.startswith("WRONG_GAME")
    assert card.downloads == []
    assert card.extra["evidence_found"] == 1
    assert card.extra["evidence_required"] == 2


def test_pipeline_keeps_card_when_all_tokens_match():
    from finder.pipeline import search_one

    card = search_one(_page("https://www.galgamex.net/search?q=summer%20clover"),
                      _galx_site(), "summer clover", timeout_ms=500)
    assert card.error is None
    assert card.extra["evidence_required"] == 2
    assert len(card.downloads) == 1


def test_extract_card_still_used_for_title_source():
    """防御：本文件里的 DETAIL_HTML 确实能让 extract_card 抽出标题。"""
    card = extract_card(DETAIL_HTML, "https://www.galgamex.net/game/cbe7d89e", "galgamex")
    assert card.title
