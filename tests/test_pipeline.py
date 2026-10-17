"""pipeline 的离线单测 —— 只测纯函数与决策逻辑，不碰网络。

真站行为由 tools/smoke_live.py 负责（不进 pytest）；
这里锁住的是「哪一层失败该报哪个错误」这条判定链。
"""
import pytest

from finder.models import SearchSpec, Site
from finder.pipeline import (
    FormSearchError,
    _form_search,
    looks_blocked,
    looks_no_results,
    match_strength,
    search_one,
    _detail_body_text,
    _find_gate_links,
    _query_evidence,
    _visible_text,
)
from finder.search import build_search_url


def test_looks_blocked_detects_cloudflare_access_denied():
    html = "<html><body><h1>Access denied</h1></body></html>"
    assert looks_blocked("Access denied", html) == "access denied"


def test_looks_blocked_detects_just_a_moment():
    assert looks_blocked("Just a moment...", "") == "just a moment"
    assert looks_blocked("", "<div id='cf-error-details'>x</div>") == "cf-error-details"


def test_looks_blocked_ignores_normal_page():
    html = "<html><body><h1>终焉之莉莉</h1><p>正常内容</p></body></html>"
    assert looks_blocked("终焉之莉莉 - 某某站", html) is None


def test_looks_no_results_detects_wordpress_nothing_found():
    """flysheep 实测：无结果时页面是 WordPress 的 "Nothing Found"。"""
    html = (
        "<html><body><h1>与终焉之莉莉匹配搜索结果 - flysheep</h1>"
        "<div class='nothing'>Nothing Found</div>"
        "<p>Sorry, but nothing matched your search terms.</p>"
        "<a href='/'>首页</a></body></html>"
    )
    assert looks_no_results("与终焉之莉莉匹配搜索结果", html) == "nothing found"


def test_looks_no_results_detects_chinese_markers():
    html = "<html><body><p>抱歉，没有找到相关内容</p></body></html>"
    assert looks_no_results("", html) is not None


def test_looks_no_results_ignores_normal_page():
    html = "<html><body><h1>终焉之莉莉：骑士寂夜</h1><p>下载地址如下</p></body></html>"
    assert looks_no_results("终焉之莉莉：骑士寂夜", html) is None


def test_visible_text_drops_scripts_and_styles():
    html = (
        "<html><head><style>.a{color:red}</style>"
        "<script>var x='Nothing Found';</script></head>"
        "<body><p>真实正文</p></body></html>"
    )
    text = _visible_text(html)
    assert "真实正文" in text
    assert "Nothing Found" not in text          # script 里的文案不算
    assert "color:red" not in text


def test_looks_no_results_does_not_fire_on_script_only_marker():
    """脚本里出现 "no results" 不能把正常页面判成无结果。"""
    html = "<html><body><p>结果如下</p><script>var msg='no results';</script></body></html>"
    assert looks_no_results("结果", html) is None


def test_match_strength_strong_when_query_in_title():
    rate, strength = match_strength("终焉之莉莉", "终焉之莉莉：骑士寂夜 中文版")
    assert strength == "strong"
    assert rate == 1.0


def test_match_strength_reports_weak_for_translated_title():
    """同一游戏不同译名：只命中一个字 → weak，但不该被当成失败。"""
    rate, strength = match_strength("终焉之莉莉", "终结的百合花 骑士们的救赎")
    assert strength in {"weak", "none"}
    assert rate < 1.0


def test_find_gate_links_extracts_go_jump():
    """gamer520 详情页只有一个 /go?post_id= 跳板，链接不在详情页 HTML 里。"""
    html = '<a href="https://www.gamer520.com/go?post_id=18985">立即下载</a>'
    gates = _find_gate_links(html, "https://www.gamer520.com/18985.html")
    assert gates == ["https://www.gamer520.com/go?post_id=18985"]


def test_find_gate_links_handles_relative_and_none():
    html = '<a href="/go?post_id=1">x</a><a href="/wp-content/a.css">css</a>'
    gates = _find_gate_links(html, "https://www.gamer520.com/1.html")
    assert gates == ["https://www.gamer520.com/go?post_id=1"]
    assert _find_gate_links("", "https://e.com/") == []


# ---- 内容证据闸门（WRONG_GAME）-------------------------------------------
# 背景：gamer520 查 enderlilies 时 pick_best 选中了「Switch 固件整合包」，
# 那是另一个页面却挂着真实网盘链接。_query_evidence 是选完之后的最后一道闸门。

ENDLILIES_FIRMWARE_TITLE = "1.12.0整合包系统稳定版+Switch 23.0.0固件"
ENDLILIES_FIRMWARE_BODY = (
    "Switch 23.0.0 固件更新说明 大气层整合包 系统稳定版 安装教程 "
    "请按步骤覆盖至 TF 卡根目录 重启后生效"
)


def test_query_evidence_latin_token_found():
    body = "Ender Lilies: Quietus of the Knights 官方中文版 下载"
    assert _query_evidence("enderlilies", "", body) > 0


def test_query_evidence_latin_token_found_in_title():
    assert _query_evidence("enderlilies", "ENDER LILIES 终结的百合花", "") > 0


def test_query_evidence_latin_unrelated_firmware_page_is_zero():
    """实测缺陷现场：固件整合包页面对 enderlilies 的证据必须是 0。"""
    n = _query_evidence(
        "enderlilies", ENDLILIES_FIRMWARE_TITLE, ENDLILIES_FIRMWARE_BODY
    )
    assert n == 0


def test_query_evidence_latin_ignores_two_letter_noise():
    """"AI" 不能命中 "chained" 里的 ai —— 短于 3 的词按整词子串计。"""
    assert _query_evidence("AI", "Chained Beasts", "a game about chained beasts") == 0


def test_query_evidence_cjk_two_or_more_chars():
    """CJK 查询命中 2 个以上不同字 → 证据 >= 2（正文里出现的其他字也算）。"""
    body = "终焉之莉莉 骑士寂夜 中文版 网盘下载"
    assert _query_evidence("终焉之莉莉", "", body) >= 2


def test_query_evidence_cjk_translated_title_still_nonzero():
    """跨译名：终焉之莉莉 vs 终结的百合花，只共享「终」也是正证据。

    这就是当初 Task 7 不设阈值的原因 —— 硬卡比例会误杀真实结果。
    闸门只卡「一个都没有」，所以这里 >= 1 即可放行。
    """
    body = "终结的百合花：骑士们的救赎 官方中文版 网盘下载"
    assert _query_evidence("终焉之莉莉", "", body) >= 1


def test_query_evidence_cjk_unrelated_page_is_zero():
    assert _query_evidence("终焉之莉莉", ENDLILIES_FIRMWARE_TITLE, ENDLILIES_FIRMWARE_BODY) == 0


def test_query_evidence_cjk_counts_distinct_chars():
    """重复出现的同一个字只算一次（避免正文复制粘贴把分数刷上去）。"""
    one = _query_evidence("终焉之莉莉", "", "莉")
    many = _query_evidence("终焉之莉莉", "", "莉莉莉莉莉莉莉莉")
    assert one == 1
    assert many == 1


def test_query_evidence_cjk_punctuation_is_not_evidence():
    """查询里的标点不能单独把错页放行（否则正文里一个「：」就算命中）。"""
    assert _query_evidence("终焉之莉莉", "", "。：、！？…") == 0


def test_query_evidence_empty_haystack_is_zero():
    assert _query_evidence("enderlilies", "", "") == 0
    assert _query_evidence("终焉之莉莉", None, None) == 0


def test_query_evidence_empty_query_is_zero():
    """空查询不能靠「0 个词」蒙混成候选；它什么也证明不了。"""
    assert _query_evidence("", "随便什么标题", "随便什么正文") == 0
    assert _query_evidence("   ", "随便什么标题", "随便什么正文") == 0


# ---- search_one 的闸门接线（假 page，不碰网络）-----------------------------
# 单测 _query_evidence 只证明计分对；这里锁住「闸门真的接在 search_one 上，
# 且命中 0 时下载链接一条都不剩」——这是本次缺陷的要害。


class _FakePage:
    """最小 page 替身：回答 goto/content/title/evaluate，按 URL 分派页面内容。"""

    def __init__(self, pages: dict[str, dict]):
        # {"<url 或 *>": {"html":..., "title":..., "text":...}}
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
        page = self._pages.get(self.url) or self._pages["*"]
        return page["html"]

    def title(self):
        return (self._pages.get(self.url) or self._pages["*"]).get("title", "")

    def evaluate(self, script):
        return (self._pages.get(self.url) or self._pages["*"]).get("text", "")


def _site() -> Site:
    return Site(
        id="fake520",
        name="Fake520",
        homepage="https://fake520.test/",
        kinds=["网盘"],
        langs={"zh", "en"},
        url_searchable=True,
        search=SearchSpec(mode="url", url_template="https://fake520.test/?s={q}"),
    )


def _smoke_page(scenario: dict) -> _FakePage:
    search_url = build_search_url(_site(), "enderlilies")
    pages = {search_url: {"html": SEARCH_HTML, "title": "search"}}
    pages.update(scenario)
    pages["*"] = {"html": "", "title": "", "text": ""}
    return _FakePage(pages)


SEARCH_HTML = (
    '<html><body><h2>搜索结果</h2>'
    '<a href="/122908.html">1.12.0整合包系统稳定版+Switch 23.0.0固件</a>'
    '<a href="/18974.html">终结的百合花 骑士们的救赎|官方中文</a>'
    "</body></html>"
)
FIRMWARE_DETAIL_HTML = (
    '<html><head><meta property="og:title" content="1.12.0整合包系统稳定版+Switch 23.0.0固件">'
    "</head><body><p>固件更新说明 大气层整合包</p>"
    '<a href="https://pan.baidu.com/s/WRONGGAME">下载</a></body></html>'
)
FIRMWARE_DETAIL_TEXT = "固件更新说明 大气层整合包 系统稳定版 安装教程"


def test_search_one_reports_wrong_game_and_drops_links():
    """实测缺陷现场：选中的是不可描述的固件页 → error=WRONG_GAME 且 dl=0。

    关键断言是 downloads == []：页面上确实有 1 条真实网盘链接，
    闸门必须把它摘掉，绝不能挂到（错误的）结果卡上。
    """
    page = _smoke_page(
        {
            "https://fake520.test/122908.html": {
                "html": FIRMWARE_DETAIL_HTML,
                "title": "固件",
                "text": FIRMWARE_DETAIL_TEXT,
            }
        }
    )
    card = search_one(page, _site(), "enderlilies")
    # 先确认真的是「选错了」这条路径（pick_best 选中固件页），否则本测试会假绿
    assert card.extra["best_url"] == "https://fake520.test/122908.html"
    assert card.url == "https://fake520.test/122908.html"
    assert card.error == "WRONG_GAME: no query evidence in page"
    assert card.downloads == []
    assert card.extra["evidence"] == 0
    assert card.extra["wrong_game"] is True


def test_search_one_keeps_card_when_evidence_present():
    """有证据时正常返回，并把 evidence 记进 extra（下载链接原样保留）。"""
    page = _smoke_page(
        {
            "https://fake520.test/122908.html": {
                "html": FIRMWARE_DETAIL_HTML.replace(
                    "1.12.0整合包系统稳定版+Switch 23.0.0固件",
                    "Ender Lilies 终结的百合花",
                ),
                "title": "Ender Lilies",
                "text": "Ender Lilies 终结的百合花 官方中文版",
            }
        }
    )
    card = search_one(page, _site(), "enderlilies")
    assert card.error is None
    assert card.extra["evidence"] > 0
    assert len(card.downloads) == 1


def test_detail_body_text_falls_back_to_html_when_evaluate_fails():
    """innerText 取不到时必须退回 HTML 去标签，而不是把正文当空 → 误判错游戏。"""

    class _NoEvalPage:
        def evaluate(self, script):
            raise RuntimeError("Target page closed")

    text = _detail_body_text(_NoEvalPage(), "<html><body><p>终焉之莉莉</p></body></html>")
    assert "终焉之莉莉" in text


# ---- form 模式搜索框定位 ---------------------------------------------------# 实测缺陷（2026-10-18）：5 个 form 站全部 FORM_FAILED TimeoutError Locator.fill。
# 根因不是各站坏了，而是 .first 命中了 0x0 的隐藏 input：
#   anime-sharing 首页 25 个 input，只有 1 个可见，前 8 个都叫 keywords
#   gamebounty / touchgal / sayafx 的搜索框是折叠的，要先点搜索图标才出现
#   zi0 首页没有任何搜索入口
# 所以：必须按「可见性」挑输入框，并且允许先点开折叠搜索框。

INPUT = "input[type=text]"


class _FakeLocator:
    def __init__(self, page, selector, matches):
        self._page = page
        self._selector = selector
        self._matches = matches
        self._idx = 0

    @property
    def first(self):
        self._idx = 0
        return self

    def nth(self, i):
        clone = _FakeLocator(self._page, self._selector, self._matches)
        clone._idx = i
        return clone

    def count(self):
        return len(self._matches)

    def _cur(self):
        return self._matches[self._idx]

    def is_visible(self, timeout=0):
        el = self._cur()
        self._page.calls.append(("is_visible", self._selector, el["visible"]))
        return el["visible"]

    def fill(self, value, timeout=0):
        el = self._cur()
        if not el["visible"]:
            raise RuntimeError("Element is not visible")
        self._page.calls.append(("fill", self._selector, value))
        el["value"] = value

    def press(self, key):
        self._page.calls.append(("press", self._selector, key))
        if key == "Enter" and hasattr(self._page, "submit"):
            self._page.submit()

    def click(self, timeout=0):
        el = self._cur()
        if not el["visible"]:
            raise RuntimeError("Element is not visible")
        self._page.calls.append(("click", self._selector))
        # 折叠搜索框在点击后才出现（gamebounty / touchgal 实测）
        if el.get("reveals"):
            self._page.reveal(el["reveals"])


class _FakeFormPage:
    """form 搜索用的最小 page：locator(sel) 按选择器匹配预先埋好的元素。"""

    def __init__(self, elements, results_html="", results_url=None,
                 anchors_sequence=None, navigates_to=None):
        # elements: [{"selector": str, "visible": bool, "reveals": [...]}, ...]
        self.elements = elements
        self.calls = []
        self.url = "https://form.test/"
        self._results_html = results_html
        self._results_url = results_url
        self._anchors_sequence = list(anchors_sequence or [])
        self._navigates_to = navigates_to
        self._anchor_reads = 0

    def reveal(self, elements):
        self.elements.extend(elements)

    def locator(self, selector):
        matches = [e for e in self.elements if e["selector"] == selector]
        return _FakeLocator(self, selector, matches)

    def goto(self, url, **kw):
        self.url = url
        return type("_R", (), {"status": 200})()

    def wait_for_load_state(self, *a, **kw):
        pass

    def wait_for_timeout(self, *a, **kw):
        pass

    def content(self):
        return self._results_html

    def title(self):
        return "search results"

    def evaluate(self, script):
        # 只有取锚点的脚本需要按序返回快照；其他脚本返回空文本
        if "querySelectorAll" not in script:
            return ""
        seq = self._anchors_sequence
        if not seq:
            return []
        i = min(self._anchor_reads, len(seq) - 1)
        self._anchor_reads += 1
        return [{"href": h, "text": "", "vis": True} for h in seq[i]]

    def submit(self):
        """模拟「按回车真的触发了导航」。"""
        if self._navigates_to:
            self.url = self._navigates_to


def _form_site(**search_kwargs) -> Site:
    return Site(
        id="fakeform",
        name="FakeForm",
        homepage="https://form.test/",
        kinds=["网盘"],
        langs={"zh"},
        url_searchable=False,
        search=SearchSpec(mode="form", **search_kwargs),
    )


def test_form_search_skips_hidden_input_and_fills_visible_one():
    """anime-sharing 实测：前 8 个 input 都叫 keywords 但全是 0x0 隐藏框。"""
    page = _FakeFormPage(
        [
            {"selector": "input[name=keywords]", "visible": False},
            {"selector": "input[name=keywords]", "visible": False},
        ]
    )
    # 第 3 个才是可见的那个
    page.elements.append({"selector": "input[name=keywords]", "visible": True})
    site = _form_site(input_selector="input[name=keywords]")
    _form_search(page, site, "终焉之莉莉", timeout_ms=1000)

    fills = [c for c in page.calls if c[0] == "fill"]
    assert fills == [("fill", "input[name=keywords]", "终焉之莉莉")]
    # 不能去点隐藏框上方的那个
    pressed = [c for c in page.calls if c[0] == "press"]
    assert pressed and pressed[0][2] == "Enter"


def test_form_search_clicks_open_selector_when_box_is_collapsed():
    """gamebounty / touchgal 实测：搜索框折叠，点搜索图标后才出现。"""
    page = _FakeFormPage(
        [
            {
                "selector": "[class*=search]",
                "visible": True,
                "reveals": [{"selector": "input[type=text]", "visible": True}],
            }
        ]
    )
    site = _form_site(open_selector="[class*=search]")
    _form_search(page, site, "Ender Lilies", timeout_ms=1000)

    assert ("click", "[class*=search]") in page.calls
    fills = [c for c in page.calls if c[0] == "fill"]
    assert fills and fills[0][2] == "Ender Lilies"


def test_form_search_uses_explicit_submit_selector_when_given():
    """有提交按钮时点按钮，不靠回车（站点可能拦 keydown）。"""
    page = _FakeFormPage(
        [
            {"selector": "#q", "visible": True},
            {"selector": "#go", "visible": True},
        ]
    )
    site = _form_site(input_selector="#q", submit_selector="#go")
    _form_search(page, site, "莉莉", timeout_ms=1000)

    assert ("click", "#go") in page.calls
    assert not [c for c in page.calls if c[0] == "press"]


def test_form_search_raises_clear_error_when_no_input_anything():
    """zi0 实测：首页没有任何搜索入口 → 必须报可读错误，不能静默。"""
    page = _FakeFormPage([])
    site = _form_site()
    with pytest.raises(FormSearchError) as exc:
        _form_search(page, site, "终焉之莉莉", timeout_ms=500)
    assert "no visible input" in str(exc.value)


def test_form_search_reports_no_effect_when_nothing_changed():
    """gamebounty / sayafx 实测：输入+回车后 URL 不变、也没有新链接。

    这是命令面板式搜索框（Ctrl+K）——回车不触发任何检索。此时页面上的
    首页链接绝不能被当成搜索结果，必须报「搜索未生效」。
    """
    page = _FakeFormPage([{"selector": INPUT, "visible": True}])
    site = _form_site(input_selector=INPUT)
    outcome = _form_search(page, site, "终焉之莉莉", timeout_ms=500)
    assert outcome.navigated is False
    assert outcome.new_anchor_count() == 0
    assert outcome.effective is False


def test_form_search_effective_when_live_results_appear():
    """anime-sharing 实测：不打转页面，但输入后有 5 条新结果链接出现。"""
    page = _FakeFormPage(
        [{"selector": INPUT, "visible": True}],
        anchors_sequence=[["https://as.test/threads/1"],        # 输入前
                          ["https://as.test/threads/1",
                           "https://as.test/threads/2"]],        # 输入后
    )
    site = _form_site(input_selector=INPUT)
    outcome = _form_search(page, site, "终焉之莉莉", timeout_ms=500)
    assert outcome.navigated is False
    assert outcome.new_anchor_count() == 1
    assert outcome.effective is True


def test_form_search_effective_when_page_navigates():
    """真表单站（有 <form action>）：跳转本身就是效果，不需要新链接。"""
    page = _FakeFormPage(
        [{"selector": INPUT, "visible": True}],
        anchors_sequence=[["https://f.test/a"], ["https://f.test/a"]],
        navigates_to="https://f.test/search?q=x",
    )
    site = _form_site(input_selector=INPUT)
    outcome = _form_search(page, site, "终焉之莉莉", timeout_ms=500)
    assert outcome.navigated is True
    assert outcome.effective is True


def test_search_one_fails_instead_of_using_homepage_links():
    """要害：搜索没生效时，绝不能把首页链接当搜索结果报成功。"""
    page = _FakeFormPage(
        [{"selector": INPUT, "visible": True}],
        results_html=(
            "<html><body>"
            '<a href="/100-india-cats">100 India Cats</a>'
            '<a href="/lords-and-villeins">Lords and Villeins</a>'
            "</body></html>"
        ),
    )
    site = _form_site(input_selector=INPUT)
    card = search_one(page, site, "终焉之莉莉", timeout_ms=500)
    assert card.error is not None
    assert card.error.startswith("FORM_FAILED:")
    assert "search did not execute" in card.error
    assert card.downloads == []
