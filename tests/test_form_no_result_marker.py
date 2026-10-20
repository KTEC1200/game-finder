"""缺陷 3：touchgal 表单搜索「确实执行了、站方说没结果」不该报 FORM_FAILED。

真站实测（2026-10-18）：touchgal `mode: form` + `form_url: /search`，
查 `夏色四叶草` → 页面逐字显示 `未找到相關內容`，但 **URL 没变、也没有新增锚点**
→ `FormOutcome.effective == False` → 旧代码回
`FORM_FAILED: search did not execute (url unchanged, no new links; N anchors)`。
这是误导：站方已经明确回了「没有」这个状态。修法：先复查站点自己的空结果文案，
命中 → 视为「搜索确实已执行」，输出 `NO_RESULTS: <marker>`。

风险点（本文件同时守住）：**没有空结果文案时，绝不能因为页面里有链接就报成功**。
"""
from finder.models import SearchSpec, Site
from finder.pipeline import looks_no_results, search_one

INPUT = "input[type=text]"

TOUCHGAL_NO_RESULT_HTML = (
    "<html><head><title>搜索 - TouchGAL</title></head><body>"
    "<div>未找到相關內容</div>"
    "</body></html>"
)


def test_looks_no_results_knows_touchgal_empty_copy():
    """touchgal 的真实文案（繁体）+ 简体兄弟文案都要认。"""
    assert looks_no_results("搜索", "<div>未找到相關內容</div>") == "未找到相關內容"
    assert looks_no_results("", "<div>未找到相关内容</div>") == "未找到相关内容"


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

    def is_visible(self, timeout=0):
        return self._matches[self._idx]["visible"]

    def fill(self, value, timeout=0):
        self._page.calls.append(("fill", value))

    def press(self, key):
        self._page.calls.append(("press", key))

    def click(self, timeout=0):
        self._page.calls.append(("click", self._selector))


class _FakeFormPage:
    """form 站最小替身：搜索不生效（url 不变、无新锚点），页面内容由调用方给定。"""

    def __init__(self, html: str, anchors=None):
        self.elements = [{"selector": INPUT, "visible": True}]
        self.calls = []
        self.url = "https://www.touchgal.ink/search"
        self._html = html
        self._anchors = list(anchors or [])

    def locator(self, selector):
        return _FakeLocator(self, selector, [e for e in self.elements if e["selector"] == selector])

    def goto(self, url, **kw):
        self.url = url
        return type("_R", (), {"status": 200})()

    def wait_for_load_state(self, *a, **kw):
        pass

    def wait_for_timeout(self, *a, **kw):
        pass

    def content(self):
        return self._html

    def title(self):
        return "搜索 - TouchGAL"

    def evaluate(self, script):
        if "querySelectorAll" not in script:
            return ""
        return [{"href": h, "text": "", "vis": True} for h in self._anchors]


def _touchgal_site() -> Site:
    return Site(
        id="touchgal",
        name="TouchGAL",
        homepage="https://www.touchgal.ink/",
        kinds=["网盘"],
        langs={"zh"},
        url_searchable=False,
        search=SearchSpec(
            mode="form",
            form_url="https://www.touchgal.ink/search",
            input_selector=INPUT,
        ),
    )


def test_form_no_effect_with_site_empty_copy_reports_no_results():
    page = _FakeFormPage(TOUCHGAL_NO_RESULT_HTML)
    card = search_one(page, _touchgal_site(), "夏色四叶草", timeout_ms=500)
    assert card.error is not None
    assert card.error.startswith("NO_RESULTS:")
    assert "未找到相關內容" in card.error
    assert "FORM_FAILED" not in card.error
    assert card.downloads == []
    assert card.extra["form_navigated"] is False
    assert card.extra["form_new_anchors"] == 0


def test_form_no_effect_without_empty_copy_still_form_failed():
    """没有空结果文案时行为不变（绝不能变成假成功）。"""
    page = _FakeFormPage(
        "<html><body><a href='/100-india-cats'>100 India Cats</a></body></html>",
        anchors=["https://www.touchgal.ink/100-india-cats"],
    )
    card = search_one(page, _touchgal_site(), "夏色四叶草", timeout_ms=500)
    assert card.error is not None
    assert card.error.startswith("FORM_FAILED:")
    assert "search did not execute" in card.error
    assert card.downloads == []


def test_form_no_effect_with_marker_never_treats_homepage_links_as_results():
    """空结果文案 + 首页残留链接：链接不是结果，仍然只能报 NO_RESULTS。"""
    page = _FakeFormPage(
        "<html><body><div>未找到相關內容</div>"
        '<a href="/100-india-cats">100 India Cats</a>'
        '<a href="/lords-and-villeins">Lords and Villeins</a>'
        "</body></html>",
        anchors=["https://www.touchgal.ink/100-india-cats"],
    )
    card = search_one(page, _touchgal_site(), "夏色四叶草", timeout_ms=500)
    assert card.error.startswith("NO_RESULTS:")
    assert card.downloads == []
    assert card.title == ""
