"""搜索页被重定向到登录页时，必须报 NEEDS_LOGIN，不能报 NO_RESULTS。

实测依据（2026-10-18，galgame.dev）：
`https://galgame.dev/search?term=enderlilies&in=titles` 直接 302 到
`https://galgame.dev/login`，页面上只有「忘记密码？/版块/最新/热门/用户/群组」
这些导航链接 —— 解析器拿到 6 条 0.5 分候选，`pick_best` 返回 None，
旧代码据此报 `NO_RESULTS: pick_best returned None`。

这对用户是误导：他会以为站上没有这款游戏，实际上是**这个站的搜索要登录**。
sites.yaml 里 galgame.dev 本来就标了 `needs_login: true`。
"""
from __future__ import annotations

import pytest

from finder.pipeline import looks_login_wall


@pytest.mark.parametrize(
    "url",
    [
        "https://galgame.dev/login",
        "https://galgame.dev/login?next=/search",
        "https://example.com/signin",
        "https://example.com/sign-in",
        "https://example.com/account/login",
        "https://example.com/auth?return=%2F",
        "https://example.com/Login",
    ],
)
def test_login_urls_are_detected(url):
    assert looks_login_wall(url, "<div>忘记密码？</div>") is not None


@pytest.mark.parametrize(
    "url",
    [
        "https://galgame.dev/search?term=x&in=titles",
        "https://www.gamer520.com/?s=enderlilies",
        "https://example.com/loginfo",      # 前缀相同但不是登录页
        "https://example.com/blog/login-tips",
        "https://example.com/",
    ],
)
def test_ordinary_urls_are_not_login_walls(url):
    assert looks_login_wall(url, "<div>正常页面</div>") is None


def test_search_page_that_only_links_to_login_is_not_a_wall():
    """搜索页上有「登录」入口（导航里到处都有）不算墙 —— 只看落地 URL。"""
    url = "https://www.nekogal.com/?s=enderlilies"
    html = "<nav><a href='/login'>登录</a><a href='/reg'>注册</a></nav>"
    assert looks_login_wall(url, html) is None


def test_message_mentions_login_and_is_actionable():
    msg = looks_login_wall("https://galgame.dev/login", "")
    assert msg.startswith("NEEDS_LOGIN")
    assert "搜索" in msg
