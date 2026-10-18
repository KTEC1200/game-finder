"""站内搜索 URL 不能被当成「搜索即跳详情」的详情页。

jidiyouxi 的搜索模板是 `https://www.jidiyouxi.com/search/detail/{q}` —— 路径
形状跟详情页一模一样。站点抖动、搜索页渲染成空壳时 hits=0，而
`_looks_detail_page` 只看路径形状 → 把**搜索页本身**认成详情页 → 进去抽卡、
内容证据为 0 → 用户拿到 `WRONG_GAME: no query evidence in page`。

2026-10-18 真站实测：同一查询 3 次里 1 次 dl=2、1 次 `NO_RESULTS: 无相关搜索`、
1 次就是这个错误的 `WRONG_GAME`。前两种是站点的诚实结论，第三种是误导。
"""
from __future__ import annotations

from pathlib import Path

from finder.pipeline import _is_site_search_url, _looks_detail_page
from finder.sites import load_sites

ROOT = Path(__file__).resolve().parents[1]
SITES = {s.id: s for s in load_sites(ROOT / "sites.yaml")}

JIDI_SEARCH = "https://www.jidiyouxi.com/search/detail/终焉之莉莉"


def test_jidiyouxi_search_url_is_recognised_as_search_url():
    assert _is_site_search_url(SITES["jidiyouxi"], JIDI_SEARCH) is True


def test_jidiyouxi_search_url_is_never_a_detail_page():
    """这就是缺陷本身：搜索页看着像详情页，也不能当详情页。"""
    assert _looks_detail_page(SITES["jidiyouxi"], JIDI_SEARCH) is False


def test_search_shaped_path_is_never_a_detail_page():
    """通用兜底：路径里有 /search 段就不是详情页（站点模板认不出时用）。"""
    assert _looks_detail_page(SITES["gamer520"], "https://x.example/search/detail/999") is False


def test_inarigal_redirect_target_is_still_a_detail_page():
    """回归：不能为了修 jidiyouxi 把「搜索即跳详情」这个真功能打掉。

    inarigal 实测 `?search=千恋万花` 直接 302 到 `/detail/64`；这一条必须
    仍然被认成详情页，否则该站会从 dl=1 退回 NO_RESULTS。
    """
    assert _looks_detail_page(SITES["inarigal"], "https://inarigal.com/detail/64") is True


def test_a_plain_detail_url_is_still_a_detail_page():
    assert _looks_detail_page(SITES["gamer520"], "https://www.gamer520.com/18974.html") is True
