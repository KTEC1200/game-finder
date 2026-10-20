"""缺陷 4：galgamex 的下载按钮藏在弹窗/站内跳转后面。

真站实测（2026-10-18，`https://www.galgamex.net/game/cbe7d89e`，查 `summer clover`）：
- 详情页有 `button:has-text('资源下载')` 标签页（`visible=True`），点开后出现供应商按钮
  `BUTTON "百度网盘"`（还有 夸克 / 阿里云盘 / 迅雷 / 天翼 / 移动云盘 / 123云盘 / MEGA /
  Google Drive / OneDrive）。
- 原始 HTML 里 **搜不到任何 `/redirect?url=`**（锚点 48 个，没有一个是下载链）——
  链接是**点击后用 JS 生成的**，所以「抽 HTML」永远抽不到。
- 点 `百度网盘` 会开新窗口，URL 是站内跳转：
  `https://www.galgamex.net/redirect?url=https%3A%2F%2Fpan.baidu.com%2Fs%2F1aCmoplMimsXAb16i9tfP_A%3Fpwd%3Dus6i`
  → `unquote(url 参数)` 才是真链 `https://pan.baidu.com/s/1aCmoplMimsXAb16i9tfP_A?pwd=us6i`
- 同时会打 `POST https://www.galgamex.net/api/game/resource/7320/download`。

取链手段选 **(a) 路由拦截**：`context.route("**/redirect*", handler)` 读出 URL 后
`route.abort()` —— 根本不加载网盘页（省流量、不触发网盘风控），比接 popup 更稳。

⚠️ 真机复测修正（2026-10-20，Playwright 直连 + 真实 UA）：
- 供应商控件是 `<button>`，**不是** `<a>`；静态 HTML 里 `download-provider` 出现 0 次。
  本文件早期用的 `a.download-provider` 是**凭空想的**选择器，真站上匹配 0 个元素。
  真站可用的选择器是
  `button[data-slot='button'][data-variant='default'][data-size='sm']`
  —— 资源卡片里「分卷 N」与「百度网盘」的 class 完全相同，只有 `data-variant`
  （资源=default，复制=ghost）与 `data-size`（资源=sm，登录=default）能分开。
- 点完按钮**不能**固定等 400ms：`百度网盘` 要先开弹窗再跳转，400ms 内路由没被触发，
  实测会漏掉这一条。实现已改成轮询（`_PROVIDER_POLL_MS` / `_PROVIDER_WAIT_MS`）。
  本文件用假 page，**测不出**这个时序问题 —— 时序只能靠真机验证。
"""
from urllib.parse import quote

import pytest

from finder.models import Download, SearchSpec, Site
from finder.pipeline import _fetch_popup_redirect_links, search_one

REDIRECT = "https://www.galgamex.net/redirect"
PAN_URL = "https://pan.baidu.com/s/1aCmoplMimsXAb16i9tfP_A?pwd=us6i"
QUARK_URL = "https://pan.quark.cn/s/0c00d8f7f6c1"


def _redirect_url(target: str) -> str:
    return f"{REDIRECT}?url={quote(target, safe='')}"


# ---- 假 context / 假 page ------------------------------------------------------

class _FakeRoute:
    def __init__(self, url):
        self.request = type("_R", (), {"url": url})()
        self.aborted = False

    def abort(self, *a, **kw):
        self.aborted = True


class _FakePopup:
    def __init__(self, url):
        self.url = url
        self.closed = False

    def close(self):
        self.closed = True


class _FakeContext:
    """记录 route 注册；按钮点击时把跳转请求喂给 handler（等价于真站的拦截）。"""

    def __init__(self):
        self.routes = []
        self.unrouted = []
        self.listeners = {}
        self.fired_routes = []
        self.popups = []

    def route(self, pattern, handler):
        self.routes.append((pattern, handler))

    def unroute(self, pattern, handler=None):
        self.unrouted.append(pattern)

    def on(self, event, callback):
        self.listeners.setdefault(event, []).append(callback)

    # --- 测试驱动 -------------------------------------------------------------
    def fire_redirect(self, target: str) -> _FakeRoute:
        route = _FakeRoute(_redirect_url(target))
        self.fired_routes.append(route)
        for pattern, handler in self.routes:
            if "redirect" in pattern:
                handler(route)
        return route

    def fire_popup(self, url: str) -> _FakePopup:
        popup = _FakePopup(url)
        self.popups.append(popup)
        for cb in self.listeners.get("page", []):
            cb(popup)
        return popup


class _FakeLocator:
    def __init__(self, page, selector):
        self._page = page
        self._selector = selector

    @property
    def _items(self):
        return self._page.buttons.get(self._selector, [])

    @property
    def first(self):
        return self.nth(0)

    def nth(self, i):
        return _FakeButton(self._page, self._selector, i)

    def count(self):
        return len(self._items)

    def is_visible(self, timeout=0):
        items = self._items
        return bool(items) and items[0].get("visible", True)


class _FakeButton:
    def __init__(self, page, selector, idx):
        self._page = page
        self._selector = selector
        self._idx = idx

    def is_visible(self, timeout=0):
        return self._page.buttons[self._selector][self._idx].get("visible", True)

    def click(self, timeout=0, **kw):
        item = self._page.buttons[self._selector][self._idx]
        self._page.clicks.append((self._selector, self._idx))
        if item.get("raises"):
            raise RuntimeError("element is not clickable")
        target = item.get("target")
        if target:
            self._page._context.fire_redirect(target)
        elif item.get("popup"):
            self._page._context.fire_popup(item["popup"])
        self._page.url = item.get("url_after", self._page.url)


class _FakeDetailPage:
    def __init__(self, buttons, context=None, html="<html><body>detail</body></html>", url=None):
        self.buttons = buttons  # {selector: [ {visible,target,popup,raises,url_after}, ... ]}
        self._context = context
        self._html = html
        # 搜索页 HTML 默认与 `html` 相同；`_search_page()` 会覆盖它。
        # （`content()` 在 url 含 "search?q=" 时返回它 —— 少了这行，凡是从
        #   搜索页起手的用例都会 AttributeError。）
        self._search_html = html
        self.url = url or "https://www.galgamex.net/game/cbe7d89e"
        self.clicks = []

    @property
    def context(self):
        return self._context

    def locator(self, selector):
        return _FakeLocator(self, selector)

    def goto(self, url, **kw):
        self.url = url
        return type("_R", (), {"status": 200})()

    def wait_for_load_state(self, *a, **kw):
        pass

    def wait_for_timeout(self, *a, **kw):
        pass

    def content(self):
        if "search?q=" in self.url:
            return self._search_html
        return self._html

    def title(self):
        return "夏色四叶草 | 夏色クローバー"

    def evaluate(self, script):
        if "querySelectorAll" in script:
            return []
        return "summer clover"


def _galgamex(selector="a.download-provider", open_sel="button:has-text('资源下载')") -> Site:
    return Site(
        id="galgamex",
        name="Galgamex",
        homepage="https://www.galgamex.net/",
        kinds=["网盘"],
        langs={"zh", "en"},
        url_searchable=True,
        search=SearchSpec(
            mode="url",
            url_template="https://www.galgamex.net/search?q={q}",
            download_flow="popup_redirect",
            detail_open_selector=open_sel,
            download_open_selector=selector,
        ),
    )


# ---- _fetch_popup_redirect_links 单测 ------------------------------------------

def test_route_intercept_yields_the_real_pan_url():
    ctx = _FakeContext()
    page = _FakeDetailPage({"a.p": [{"visible": True, "target": PAN_URL}]}, context=ctx)
    out = _fetch_popup_redirect_links(page, _galgamex("a.p"), 1000, {})
    assert [d.url for d in out] == [PAN_URL]
    assert out[0].kind == "pan"
    assert ctx.routes and "redirect" in ctx.routes[0][0]
    assert ctx.fired_routes[0].aborted is True, "必须 abort，不能真的加载网盘页"
    assert ctx.unrouted, "收尾要 unroute，别把 handler 留在 context 上"


def test_duplicate_providers_are_deduped():
    ctx = _FakeContext()
    page = _FakeDetailPage(
        {"a.p": [{"visible": True, "target": PAN_URL}, {"visible": True, "target": PAN_URL}]},
        context=ctx,
    )
    out = _fetch_popup_redirect_links(page, _galgamex("a.p"), 1000, {})
    assert len(out) == 1


def test_one_broken_button_does_not_block_the_others():
    ctx = _FakeContext()
    page = _FakeDetailPage(
        {
            "a.p": [
                {"visible": True, "raises": True},
                {"visible": True, "target": QUARK_URL},
            ]
        },
        context=ctx,
    )
    extra = {}
    out = _fetch_popup_redirect_links(page, _galgamex("a.p"), 1000, extra)
    assert [d.url for d in out] == [QUARK_URL]
    assert extra["galgamex_errors"], "失败要记进 extra，不能静默吞掉"


def test_popup_fallback_is_used_when_the_route_intercept_misses():
    """真站有时是 window.open：路由没拦住 IP，popup 兜底，并立刻 close。"""
    ctx = _FakeContext()
    page = _FakeDetailPage(
        {"a.p": [{"visible": True, "popup": _redirect_url(QUARK_URL)}]}, context=ctx
    )
    out = _fetch_popup_redirect_links(page, _galgamex("a.p"), 1000, {})
    assert [d.url for d in out] == [QUARK_URL]
    assert ctx.popups and ctx.popups[0].closed is True


def test_direct_pan_url_and_asset_urls_are_handled():
    """不是跳转链的直接网盘链照收；图标/logo 之类的资源链必须过滤掉。"""
    ctx = _FakeContext()
    page = _FakeDetailPage(
        {
            "a.p": [
                {"visible": True, "target": PAN_URL},
                {"visible": True, "target": "https://www.galgamex.net/static/img/logo.png"},
                {"visible": True, "target": "javascript:void(0)"},
                {"visible": True, "target": QUARK_URL},
            ]
        },
        context=ctx,
    )
    out = _fetch_popup_redirect_links(page, _galgamex("a.p"), 1000, {})
    assert [d.url for d in out] == [PAN_URL, QUARK_URL]


def test_no_selector_returns_empty_without_raising():
    ctx = _FakeContext()
    page = _FakeDetailPage({}, context=ctx)
    extra = {}
    assert _fetch_popup_redirect_links(page, _galgamex(""), 1000, extra) == []
    assert extra["galgamex_errors"]


def test_button_cap_limits_clicks():
    ctx = _FakeContext()
    many = [{"visible": True, "target": f"https://pan.baidu.com/s/{i}"} for i in range(30)]
    page = _FakeDetailPage({"a.p": many}, context=ctx)
    out = _fetch_popup_redirect_links(page, _galgamex("a.p"), 1000, {})
    assert len(page.clicks) <= 12, "供应商按钮最多点 N 个，别把页面点爆"
    assert len(out) == len(page.clicks)


# ---- 接进 search_one -----------------------------------------------------------

SEARCH_HTML = '<html><body><a href="/game/cbe7d89e">夏色四叶草</a></body></html>'


def _search_page(detail_page: _FakeDetailPage) -> _FakeDetailPage:
    """同一个假 page 先当搜索页、再当详情页（goto 换 url 后 content 不变）。"""
    detail_page._search_html = SEARCH_HTML
    return detail_page


def test_search_one_popup_redirect_flow_returns_downloads():
    ctx = _FakeContext()
    page = _FakeDetailPage(
        {
            "button:has-text('资源下载')": [{"visible": True}],
            "a.p": [{"visible": True, "target": PAN_URL}, {"visible": True, "target": QUARK_URL}],
        },
        context=ctx,
        html=SEARCH_HTML,
        url="https://www.galgamex.net/search?q=summer%20clover",
    )
    card = search_one(page, _galgamex("a.p"), "summer clover", timeout_ms=500)
    assert card.error is None
    assert [d.url for d in card.downloads] == [PAN_URL, QUARK_URL]


def test_search_one_popup_redirect_without_buttons_reports_no_downloads():
    ctx = _FakeContext()
    page = _FakeDetailPage(
        {"button:has-text('资源下载')": [{"visible": True}]},
        context=ctx,
        html=SEARCH_HTML,
        url="https://www.galgamex.net/search?q=summer%20clover",
    )
    card = search_one(page, _galgamex("a.p"), "summer clover", timeout_ms=500)
    assert card.downloads == []
    assert card.error is not None
