"""论坛帖子不能盖过游戏条目页（2026-10-18 kungal 真站实测）。

kungal 的搜索结果是混合的：既有游戏条目 `/galgame/<id>`（有「本体资源下载」
标签页），也有论坛帖子 `/topic/<id>`（纯讨论）。查「千恋万花」时：

    /topic/3887     '千恋万花 十周年 2 个月前 日常 个人随笔'      <- 帖子
    /galgame/15     '266576 93 3 天前 千恋＊万花 柚子软件 7.6'   <- 游戏条目

帖子标题以查询词开头（+12 分 + 位置分满分），条目页标题前面有统计数字
（位置分略低），于是 `pick_best` 选了**讨论帖**，用户拿不到下载链接。

约束：不能一刀切禁掉 `/topic/` —— jidiyouxi 的游戏页正是
`/topic/detail/<id>`（带 `detail`）。只压「纯讨论串」形状：
`/topic/<digits>`、`/post/<digits>`、`/thread/<digits>`、`/forum/<digits>`。
"""
from finder.models import SearchSpec, Site
from finder.search import SearchHit, pick_best


def _site(sid="kungal"):
    return Site(
        id=sid,
        name=sid,
        homepage="https://www.kungal.com/",
        kinds=["论坛网盘"],
        langs={"zh"},
        url_searchable=True,
        search=SearchSpec(
            mode="url", url_template="https://www.kungal.com/search?keywords={q}"
        ),
    )


def test_game_entry_beats_forum_thread_with_same_title_match():
    hits = [
        SearchHit(
            site_id="kungal",
            title="千恋万花 十周年 2 个月前 日常 个人随笔",
            url="https://www.kungal.com/topic/3887",
            score=1.0,
        ),
        SearchHit(
            site_id="kungal",
            title="266576 93 3 天前 千恋＊万花 柚子软件 7.6",
            url="https://www.kungal.com/galgame/15",
            score=1.0,
        ),
    ]
    best = pick_best(hits, "千恋万花")
    assert best is not None
    assert best.url == "https://www.kungal.com/galgame/15", (
        f"选中了讨论帖而不是游戏条目：{best.url}"
    )


def test_jidiyouxi_topic_detail_is_not_treated_as_thread():
    """jidiyouxi 的游戏页就是 /topic/detail/<id>，不能被压分。"""
    hits = [
        SearchHit(
            site_id="jidiyouxi",
            title="剑星中文版学习版免费下载",
            url="https://www.jidiyouxi.com/topic/detail/171085167",
            score=1.0,
        ),
        SearchHit(
            site_id="jidiyouxi",
            title="剑星 讨论帖",
            url="https://www.jidiyouxi.com/post/detail/3054647172",
            score=1.0,
        ),
    ]
    best = pick_best(hits, "剑星")
    assert best is not None
    assert best.url == "https://www.jidiyouxi.com/topic/detail/171085167"


def test_thread_penalty_does_not_override_no_match():
    """只有讨论帖命中查询词时仍要能返回（不能因为压分变成 None）。"""
    hits = [
        SearchHit(
            site_id="kungal",
            title="千恋万花 十周年",
            url="https://www.kungal.com/topic/3887",
            score=1.0,
        )
    ]
    best = pick_best(hits, "千恋万花")
    assert best is not None
    assert best.url == "https://www.kungal.com/topic/3887"
