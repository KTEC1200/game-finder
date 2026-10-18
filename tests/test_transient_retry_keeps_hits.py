"""暂态重试不许把**已经拿到的结果**重载冲掉。

jidiyouxi 是 JS 渲染页：真正出结果时 `_visible_text` 也只有 ~250 字，低于
`_TRANSIENT_TEXT_MIN = 300` → 被判成「暂态」→ 老代码会 `_goto` 重载，
把已经解析出来的候选冲掉，还要重新碰站点的随机空响应。

2026-10-18 真站实测对照：
  - 单纯轮询同一个页面：**+4.0s 就 hits=1**（两次都如此）
  - 走老 `search_one`：3 次里 1 次 dl=2、2 次 `NO_RESULTS: 无相关搜索`
    （其中一次还被误当成详情页报 WRONG_GAME，已由
    tests/test_search_url_is_not_detail.py 单独盖住）

「解析出候选」是硬证据，与「候选覆盖无结果标记」同一条原则。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from finder.models import GameDetail
from finder.pipeline import search_one
from finder.sites import load_sites

ROOT = Path(__file__).resolve().parents[1]
SITES = {s.id: s for s in load_sites(ROOT / "sites.yaml")}

# 出结果、但正文很短 —— 正是会被误判成暂态的那一页
HIT_HTML = (
    '<html><body><a href="/topic/detail/959615543">终焉之莉莉：骑士寂夜</a></body></html>'
)
# 真·空壳：站点接口抖掉时的样子（短 + Network Error）
BROKEN_HTML = (
    "<html><body>首页 PC游戏 0 联机专区 游戏专区 (0) 手游 (0) "
    "无相关搜索 Network Error</body></html>"
)


class _Resp:
    status = 200


class _Page:
    def __init__(self, html: str):
        self._html = html
        self.url = ""
        self.gotos: list[str] = []

    def goto(self, url, **_kw):
        self.gotos.append(url)
        self.url = url
        return _Resp()

    def wait_for_timeout(self, _ms):
        return None

    def content(self):
        return self._html

    def title(self):
        return "玩游戏来机地"


@pytest.fixture
def _no_wait(monkeypatch):
    monkeypatch.setattr("finder.pipeline._settle", lambda *a, **k: None)
    monkeypatch.setattr("finder.pipeline._open_collapsed_box", lambda *a, **k: None)


def test_a_page_with_hits_is_never_reloaded(_no_wait, monkeypatch):
    """核心断言：有候选时一次导航都不许多发。"""
    calls = []

    def _fake_extract(page, site, q, detail_url, timeout_ms, extra):
        calls.append(detail_url)
        return GameDetail(site_id=site.id, url=detail_url, title="终焉之莉莉：骑士寂夜")

    monkeypatch.setattr("finder.pipeline._extract_detail", _fake_extract)
    page = _Page(HIT_HTML)
    card = search_one(page, SITES["jidiyouxi"], "终焉之莉莉")

    # 搜索 URL 会被 build_search_url 百分号编码，只比对导航次数与路径形状
    assert len(page.gotos) == 1, page.gotos
    assert "/search/detail/" in page.gotos[0]
    assert calls == ["https://www.jidiyouxi.com/topic/detail/959615543"]
    assert card.error is None


def test_a_broken_empty_page_is_still_retried(_no_wait, monkeypatch):
    """反向保护：真的空壳还必须重试，否则会把站点抖动记成永久结论。"""
    monkeypatch.setattr(
        "finder.pipeline._extract_detail",
        lambda *a, **k: GameDetail(site_id="x", url="", title=""),
    )
    page = _Page(BROKEN_HTML)
    card = search_one(page, SITES["jidiyouxi"], "终焉之莉莉")
    assert len(page.gotos) > 1, "空壳页面应当重试导航"
    assert card.error is not None and card.error.startswith("NO_RESULTS")
