"""kungal（鲲 Galgame）详情页要「点标签页才出下载链」（2026-10-18 真站实测）。

站点形状：`/galgame/{id}` 是 SPA 式标签页，四个 tab：
    游戏介绍 / 本体资源下载 / 补丁资源下载 / 评论区
默认停在「游戏介绍」，正文里**一条网盘链都没有**；点「本体资源下载」后
同页渲染出资源列表（百度 40 / 夸克 32 / 移动云盘 11 / 123云盘 3 / 迅雷 12 /
其他 23），每条带「获取资源」按钮。

关键区别（这是本文件要守住的约束）：
  与 touchgal 不同，kungal **不跳转**——链接就在同一页渲染出来。
  现有 `_follow_detail_gate` 要求配了 `detail_follow_pattern` 才会动作，
  所以 kungal 这种「只点不开」的站它完全不会触发，结果永远是
  NO_DOWNLOADS。必须允许「只配 detail_open_selector、不配 follow_pattern」。
"""
import re


class _FakeLocator:
    def __init__(self, visible=True):
        self._visible = visible
        self.clicked = 0

    def count(self):
        return 1 if self._visible else 0

    def is_visible(self, timeout=None):
        return self._visible

    def click(self, timeout=None):
        self.clicked += 1

    # `_first_visible` 会调 nth(i)（真实 Playwright 也有），假对象必须提供，
    # 否则 hasattr(loc, "nth") 为 False，走 loc.first 分支直接抛错 → 返回 None。
    def nth(self, i):
        return self

    @property
    def first(self):
        return self


class _FakePage:
    """点标签页后同页内容变化的假页面（不导航）。"""

    def __init__(self, html_before, html_after, selector_visible=True):
        self._before = html_before
        self._after = html_after
        self._clicked = False
        self.locator_obj = _FakeLocator(selector_visible)
        self.url = "https://www.kungal.com/galgame/15"

    def locator(self, selector):
        return self.locator_obj

    def get_by_role(self, *a, **k):
        return self.locator_obj

    def wait_for_timeout(self, ms):
        return None

    def wait_for_load_state(self, *a, **k):
        return None

    def content(self):
        return self._after if self.locator_obj.clicked else self._before

    def evaluate(self, script, arg=None):
        return ""


KUNGAL_BEFORE = """
<html><head><title>千恋＊万花 - 鲲 Galgame 论坛</title></head><body>
<div>千恋＊万花</div>
<div>Senren * Banka</div>
<div>游戏介绍 本体资源下载 补丁资源下载 评论区</div>
<div>游玩时长 33 小时 30 分钟</div>
</body></html>
"""

KUNGAL_AFTER = """
<html><head><title>千恋＊万花 - 鲲 Galgame 论坛</title></head><body>
<div>千恋＊万花</div>
<div>Galgame 资源链接</div>
<div>百度网盘 (40) 夸克网盘 (32) 迅雷云盘 (12)</div>
<div>游戏本体 28.06 GB Windows 电脑版 简体中文</div>
<a href="https://pan.baidu.com/s/1Dau8DVO5_HcMjOD4nFA4Qg?pwd=t7cp">百度网盘</a>
<a href="https://pan.baidu.com/s/1g9Thiv__2Krm2n1-fEp9Sw?pwd=62r5">百度网盘</a>
<a href="https://pan.xunlei.com/s/VOyhbhDXJvGeldVp6UCpq61aA1?pwd=s4uc">迅雷云盘</a>
</body></html>
"""


def _kungal_site():
    from finder.models import SearchSpec, Site

    return Site(
        id="kungal",
        name="鲲 Galgame",
        homepage="https://www.kungal.com/",
        kinds=["论坛网盘"],
        langs={"zh", "en", "ja"},
        url_searchable=True,
        search=SearchSpec(
            mode="url",
            url_template="https://www.kungal.com/search?keywords={q}",
            detail_open_selector="text=本体资源下载",
        ),
    )


def test_reveal_clicks_tab_and_extracts_downloads_from_same_page():
    """只配 open_selector、不配 follow_pattern 也要能出下载链。"""
    from finder.pipeline import _follow_detail_gate

    page = _FakePage(KUNGAL_BEFORE, KUNGAL_AFTER)
    extra = {}
    card = _follow_detail_gate(
        page, _kungal_site(), "https://www.kungal.com/galgame/15", 30000, extra
    )
    assert card is not None, "点了标签页就该返回卡片，不该退回 None"
    assert page.locator_obj.clicked == 1, "必须真的点了标签页"
    assert len(card.downloads) == 3
    assert card.downloads[0].kind == "pan"
    assert "pan.baidu.com" in card.downloads[0].url
    assert extra.get("detail_revealed") is True


def test_reveal_returns_none_when_tab_missing():
    """标签页不在页面上时不能假装成功（宁可 None 让上层报 NO_DOWNLOADS）。"""
    from finder.pipeline import _follow_detail_gate

    page = _FakePage(KUNGAL_BEFORE, KUNGAL_AFTER, selector_visible=False)
    extra = {}
    card = _follow_detail_gate(
        page, _kungal_site(), "https://www.kungal.com/galgame/15", 30000, extra
    )
    assert card is None
    assert extra.get("detail_open_error") or extra.get("detail_reveal_missing")


def test_reveal_does_not_invent_links_when_tab_reveals_nothing():
    """点了但页面仍是「暂无」——不能把标签文字当链接。"""
    from finder.pipeline import _follow_detail_gate

    empty_after = KUNGAL_BEFORE.replace("游戏介绍", "暂无")
    page = _FakePage(KUNGAL_BEFORE, empty_after)
    extra = {}
    card = _follow_detail_gate(
        page, _kungal_site(), "https://www.kungal.com/galgame/15", 30000, extra
    )
    if card is not None:
        assert card.downloads == []
        # 文案是「暂无」→ 归到「站点自己标注内容不可用」，比裸 NO_DOWNLOADS 更准确
        assert card.error and card.error.startswith("NO_DOWNLOADS")


def test_site_with_follow_pattern_still_navigates():
    """配了 follow_pattern 的站（touchgal）行为不能被改坏。"""
    from finder.models import SearchSpec, Site

    site = Site(
        id="touchgal",
        name="TouchGal",
        homepage="https://www.touchgal.ink/",
        kinds=["直链", "网盘"],
        langs={"zh"},
        url_searchable=False,
        search=SearchSpec(
            mode="form",
            form_url="https://www.touchgal.ink/search",
            input_selector="input",
            detail_open_selector="button:has-text('下载')",
            detail_follow_pattern=r"/resource/\d+",
        ),
    )
    # 有 follow_pattern 时仍走原来的「找链接再跳」路径
    assert site.search.detail_follow_pattern is not None
    assert re.search(site.search.detail_follow_pattern, "/game/x/resource/123")
