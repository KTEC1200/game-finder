r"""论坛帖的 slug 型 URL 必须仍算「详情形状」。

实测 2026-10-18（anime-sharing）：搜索结果 URL 形如
    https://www.anime-sharing.com/threads/new-release-260910-%E3%82%A8.../
    https://www.anime-sharing.com/threads/260910-%E6%A0%AA%E5%BC%8F.../
路径里没有 `/数字`（数字埋在 slug 中间），也没有 `.html` 后缀。
`DETAILISH_RE` 收紧 `/\d{2,}(?:/|$|\?|#)` 之后（为的是别把 ggbases 的
`/2257.so` 法务页认成详情页），这些帖子全部掉到 0.5 分，
`pick_best` 的 `score >= 1.0` 候选池直接空了 —— 该站从 dl=10 退化成
`NO_RESULTS: pick_best returned None`。这是我自己引入的回归。

判据收窄：只认 `/threads/` 这一种论坛路径（XenForo 全站形状），
不放开 `/数字`，也不碰 `/members/<name>.<id>/`（用户页同样 0.5 分才对）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from finder.search import DETAILISH_RE, parse_result_links, pick_best  # noqa: E402
from finder.models import SearchSpec, Site  # noqa: E402


def _site() -> Site:
    return Site(
        id="anime-sharing",
        name="Anime-Sharing",
        homepage="https://www.anime-sharing.com/",
        kinds=["直链"],
        langs={"ja", "en"},
        url_searchable=True,
        search=SearchSpec(
            mode="url",
            url_template="https://www.anime-sharing.com/search/1/?q={q}",
        ),
    )


def test_thread_slug_url_is_detail_shape():
    """anime-sharing 真站帖子 URL（数字在 slug 中间，无扩展名）。"""
    assert DETAILISH_RE.search(
        "/threads/new-release-260910-%E3%82%A8%E3%83%B3%E3%82%BF%E3%83%BC/"
    )
    assert DETAILISH_RE.search("/threads/260910-%E6%A0%AA%E5%BC%8F-3/")


def test_member_profile_is_not_detail_shape():
    """用户页 `/members/<name>.<id>/` 不该被当成详情页 —— 它不是资源。"""
    assert not DETAILISH_RE.search("/members/ramori.6400/")


def test_legal_page_still_not_detail_shape():
    """回归保护：ggbases 的 `/2257.so` 必须仍是 0.5（不是详情形状）。"""
    assert not DETAILISH_RE.search("/2257.so")


def test_anime_sharing_thread_wins_over_member_pages():
    """真站形状：帖子与用户页混排，pick_best 必须选中帖子。"""
    html = """
    <ul class="block-rowList">
      <li><a href="/threads/new-release-260910-%E3%82%A8/">[New Release][260910][エンターグラム] 制服カノジョ 3 めいか初恋BOX</a></li>
      <li><a href="/members/flowertradewinds.6343/">FlowerTradeWinds</a></li>
      <li><a href="/threads/260910-%E6%A0%AA/">[260910][株式会社エンターグラム] 制服カノジョ ３ + 特典</a></li>
      <li><a href="/members/ramori.6400/">ramori</a></li>
    </ul>
    """
    url = "https://www.anime-sharing.com/search/1/?q=x"
    hits = parse_result_links(html, url, _site())
    thread_hits = [h for h in hits if "/threads/" in h.url]
    assert thread_hits, "帖子链接应被解析出来"
    assert all(h.score >= 1.0 for h in thread_hits), [h.score for h in thread_hits]

    best = pick_best(hits, "制服カノジョ")
    assert best is not None, "pick_best 不该返回 None"
    assert "/threads/" in best.url, f"选中了非帖子页：{best.url}"
    assert "制服カノジョ" in best.title


def test_request_thread_loses_to_release_thread():
    """求资源帖不是资源。

    实测 2026-10-18（anime-sharing，查「制服カノジョ」）：候选里混着
        [Request] 制服カノジョ 2                       <- 有人在求这款游戏
        [260910][株式会社エンターグラム] 制服カノジョ ３ + 特典   <- 真发布帖
    求资源帖的标题以查询词开头（位置分拿满），发布帖前面有日期/厂商前缀，
    位置分略低 —— 于是选中求资源帖，抽出 0 条下载链接，报 NO_DOWNLOADS。
    """
    html = """
    <ul class="block-rowList">
      <li><a href="/threads/request-x/">[Request] 制服カノジョ 2</a></li>
      <li><a href="/threads/260910-enter/">[260910][株式会社エンターグラム] 制服カノジョ ３ + 特典</a></li>
    </ul>
    """
    url = "https://www.anime-sharing.com/search/1/?q=x"
    hits = parse_result_links(html, url, _site())
    best = pick_best(hits, "制服カノジョ")
    assert best is not None
    assert "request-x" not in best.url, f"选中了求资源帖：{best.title!r}"


def test_request_thread_still_returned_when_only_candidate():
    """压分不是排除：只有求资源帖命中时仍要返回，别报 NO_RESULTS。"""
    html = '<a href="/threads/request-y/">[Request] 制服カノジョ 2</a>'
    url = "https://www.anime-sharing.com/search/1/?q=x"
    hits = parse_result_links(html, url, _site())
    best = pick_best(hits, "制服カノジョ")
    assert best is not None and "request-y" in best.url


def test_favicon_and_proxy_image_are_not_downloads():
    """页面装饰资源不是下载链接。

    实测 2026-10-18（anime-sharing 帖子页）：整页 HTML 里除了真链，还有
        https://assets.katfile.com/favicon.ico          <- 图标
        https://p.anime-sharing.com/proxy.php?image=... <- 图片代理
    两者都因为域名/路径里带 filehost 关键字或 /file 而被判成下载。
    """
    from finder.detail import extract_downloads

    html = """
    <img src="https://assets.katfile.com/favicon.ico">
    <img src="https://p.anime-sharing.com/proxy.php?image=https%3A%2F%2Fassets.katfile.com%2Ff.png">
    <a href="https://rapidgator.net/file/5eed3a4e/Seifuku_Kanojo_v01.part1.rar.html">RG</a>
    <a href="https://krakenfiles.com/view/hCE8SjcxdJ/file.html">KF</a>
    """
    urls = [d.url for d in extract_downloads(html, "https://www.anime-sharing.com/threads/x/")]
    assert not any("favicon" in u for u in urls), urls
    assert not any("proxy.php" in u for u in urls), urls
    assert any("rapidgator.net/file/" in u for u in urls), urls
    assert any("krakenfiles.com/view/" in u for u in urls), urls
