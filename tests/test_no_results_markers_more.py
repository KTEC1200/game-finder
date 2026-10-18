"""各站自己的「真的没有」文案必须被认出来。

认不出来时错误会退化成 `NO_RESULTS: pick_best returned None`，看起来像
解析器坏了，实际是站点本来就没有这款游戏 —— 这个区别对用户和排查都很重要。
每条都来自 2026-10-18 在真站上实际抓到的文本。
"""
from __future__ import annotations

import pytest

from finder.pipeline import looks_no_results


@pytest.mark.parametrize(
    "html, expect",
    [
        # gamebounty 中文界面（实测 q=千恋万花 / 赛博朋克 / 艾尔登法环）
        ('<div>没有关于“千恋万花”的结果</div>', "没有关于"),
        # gamebounty 英文界面（"no results" 已先命中，返它即可）
        ("<div>No results for \u201cenderlilies\u201d</div>", "no results"),
        # ggbases 繁体 + 不间断空格
        ("<div>GGBases&nbsp;&gt;&nbsp; 0&nbsp;個資源</div>", "0 個資源"),
        # acggw
        ("<div>搜索结果 没有内容</div>", "搜索结果 没有内容"),
        # nekogal
        ("<div>共找到 0 个文章</div>", "共找到 0 个"),
        # galgamex
        ("<div>暂无游戏收录</div>", "暂无游戏收录"),
    ],
)
def test_real_empty_result_copy_is_recognized(html, expect):
    assert looks_no_results("", html) == expect


def test_a_real_result_page_is_not_flagged():
    html = (
        "<title>ENDER LILIES: Quietus of the Knights - Free PC Download</title>"
        "<div>9 个结果</div><a href='/ender-lilies-free-pc-download'>ENDER LILIES</a>"
    )
    assert looks_no_results("", html) is None
