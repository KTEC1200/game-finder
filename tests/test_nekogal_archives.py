r"""`/archives/<id>` 是详情页，不是归档列表。

实测 2026-10-18（nekogal）：搜索「千恋万花」命中 1 个文章，链接形如
    https://www.nekogal.com/archives/67
但 `NAV_RE` 里的 `archives?` 分支把整条路径当导航剔除了 —— 该站
永远 `NO_RESULTS: pick_best returned None`，即使站上确实有这款游戏。

区分方式：`/archives/<id>` 是详情页；`/archives/category/...`、
`/archives/tag/...` 才是列表页（这两条已由 NAV_RE 的 category/tag 覆盖）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from finder.search import parse_result_links, pick_best  # noqa: E402
from finder.models import SearchSpec, Site  # noqa: E402


def _site() -> Site:
    return Site(
        id="nekogal",
        name="NekoGAL",
        homepage="https://www.nekogal.com/",
        kinds=["直链"],
        langs={"zh"},
        url_searchable=True,
        search=SearchSpec(
            mode="url",
            url_template="https://www.nekogal.com/?s={q}",
        ),
    )


def test_archives_detail_page_is_a_result():
    html = """
    <div class="posts">
      <posts class="posts-item list ajax-item flex">
        <div class="post-graphic"><div class="item-thumbnail">
          <a target="_blank" href="https://www.nekogal.com/archives/67"><img src="x.webp" alt="封面"></a>
        </div></div>
        <a href="https://www.nekogal.com/archives/67">【PC游戏/模拟器/汉化】千恋万花</a>
      </posts>
    </div>
    """
    url = "https://www.nekogal.com/?s=x"
    hits = parse_result_links(html, url, _site())
    urls = [h.url for h in hits]
    assert any(u.endswith("/archives/67") for u in urls), urls
    assert all(h.score >= 1.0 for h in hits if "archives/67" in h.url)

    best = pick_best(hits, "千恋万花")
    assert best is not None
    assert best.url.endswith("/archives/67")


def test_archives_category_list_is_still_nav():
    """列表页 `/archives/category/...` 与 `/archives/tag/...` 必须仍被剔除。"""
    html = """
    <a href="https://www.nekogal.com/archives/category/pcgame">PC资源</a>
    <a href="https://www.nekogal.com/archives/tag/adv"># ADV</a>
    <a href="https://www.nekogal.com/archives/67">【PC游戏】千恋万花</a>
    """
    url = "https://www.nekogal.com/?s=x"
    urls = [h.url for h in parse_result_links(html, url, _site())]
    assert not any("/archives/category/" in u for u in urls), urls
    assert not any("/archives/tag/" in u for u in urls), urls
    assert any(u.endswith("/archives/67") for u in urls), urls
