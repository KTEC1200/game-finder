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
