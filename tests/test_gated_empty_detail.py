"""抽不到下载链接时要报出**具体原因**，不能一律 NO_DOWNLOADS。

实测依据（2026-10-18，iacg `https://iacg.love/56681.html`）：
正文写着「此处内容已隐藏，请评论后刷新页面查看.」，页脚另有
「请登录后查看评论内容」——必须先登录、再评论，才看得到隐藏内容。
旧代码报 NO_DOWNLOADS，用户会以为站点真的没这个资源。
"""
from __future__ import annotations

import pytest

from finder.pipeline import _classify_empty_detail


def test_login_plus_comment_gate():
    html = "<div>此处内容已隐藏，请评论后刷新页面查看.</div><div>请登录后查看评论内容</div>"
    err = _classify_empty_detail(html)
    assert err.startswith("NEEDS_LOGIN")
    assert "评论" in err


def test_comment_only_gate():
    html = "<div>此处内容已隐藏，请评论后刷新页面查看.</div>"
    err = _classify_empty_detail(html)
    assert err.startswith("NEEDS_COMMENT")


@pytest.mark.parametrize(
    "html",
    [
        "<div>请登录后查看下载地址</div>",
        "<div>You must be logged in to view this content</div>",
        "<div>Login to view</div>",
    ],
)
def test_login_only_gate(html):
    assert _classify_empty_detail(html).startswith("NEEDS_LOGIN")


@pytest.mark.parametrize(
    "html",
    [
        "<div>资源已失效</div>",
        "<div>链接已失效，请等待补档</div>",
        "<div>暂无</div>",
        "<div>This file has been removed</div>",
    ],
)
def test_closed_content(html):
    assert _classify_empty_detail(html).startswith("NO_DOWNLOADS")


def test_plain_empty_page_stays_plain_no_downloads():
    """没有门槛文案时保持裸 NO_DOWNLOADS —— 不要凭空造原因。"""
    assert _classify_empty_detail("<div>这是一个游戏介绍页面</div>") == "NO_DOWNLOADS"


def test_comment_marker_wins_over_bare_login():
    """同时有「评论后可见」和「登录」时，报更具体的那个。"""
    html = "<div>此处内容已隐藏，请评论后刷新页面查看.</div><div>登录 注册</div>"
    assert _classify_empty_detail(html).startswith("NEEDS_COMMENT")


# ---- 只有站内跳板、没有直链 ----
#
# 实测依据（2026-10-18，gamer520 中文查「终焉之莉莉」）：
# 详情页 `https://www.gamer520.com/18985.html` 有 0 条网盘链接，只有
# `/go?post_id=18985`。跟随它两次结果逐字节一致，但落地页是第三方聚合站的
# 用户上传帖 `520.gamers520.com/8191.html`（面包屑 `… > 322369521 > 5009 牛夫人`），
# 正文 716 字里游戏名出现 0 次；它的百度盘链接还出现在**另一个帖子**的落地页上。
# → 归属无法确认，不能自动跟进，但也不能报成「站点没有资源」。

def test_gate_only_page_is_reported_as_needs_gate():
    err = _classify_empty_detail("<div>这是一个游戏介绍页面</div>",
                                 ["https://www.gamer520.com/go?post_id=18985"])
    assert err.startswith("NEEDS_GATE")
    assert "1" in err


def test_no_gate_links_keeps_plain_no_downloads():
    """没有跳板证据时不许升格成 NEEDS_GATE（否则每个空页都变成跳板）。"""
    assert _classify_empty_detail("<div>介绍页</div>", []) == "NO_DOWNLOADS"
    assert _classify_empty_detail("<div>介绍页</div>") == "NO_DOWNLOADS"


def test_login_gate_still_wins_over_gate_links():
    """登录/评论门槛比「有跳板」更具体，优先级更高。"""
    err = _classify_empty_detail("<div>请登录后查看下载地址</div>",
                                 ["https://x.test/go?post_id=1"])
    assert err.startswith("NEEDS_LOGIN")
