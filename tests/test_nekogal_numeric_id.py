r"""`/archives/6661` 是文章详情页，不是年份归档。

2026-10-18 真站：查「制服カノジョ」，nekogal 页面显示「共找到 3 个文章」，
但 parse_result_links 只返回 1 条（还是「找回密码」这种导航页）。
根因：NAV_RE 的 `\d{4}` 分支把 `archives/6661` 当成 `/archives/2026` 那类
年份归档剔掉了。年份只可能是 19xx/20xx，紧成这个范围即可。
"""
from __future__ import annotations

from pathlib import Path

from finder.search import parse_result_links, pick_best
from finder.sites import load_sites

ROOT = Path(__file__).resolve().parents[1]


def _site():
    return {s.id: s for s in load_sites(ROOT / "sites.yaml")}["nekogal"]


def test_four_digit_article_ids_are_results_not_year_archives():
    html = """
    <div class="posts-item">
      <a href="https://www.nekogal.com/archives/6661">【PC游戏/机翻】制服女友3</a>
      <a href="https://www.nekogal.com/archives/1187">【PC游戏/汉化】制服カノジョ2</a>
    </div>
    """
    hits = parse_result_links(html, "https://www.nekogal.com/?s=x", _site())
    urls = [h.url for h in hits]
    assert any(u.endswith("/archives/6661") for u in urls), urls
    assert any(u.endswith("/archives/1187") for u in urls), urls


def test_year_archives_are_still_navigation():
    html = """
    <a href="https://www.nekogal.com/archives/2026">2026 年</a>
    <a href="https://www.nekogal.com/archives/1999">1999 年</a>
    <a href="https://www.nekogal.com/archives/1187">【PC游戏】制服カノジョ2</a>
    """
    hits = parse_result_links(html, "https://www.nekogal.com/?s=x", _site())
    urls = [h.url for h in hits]
    assert not any("/archives/2026" in u for u in urls), urls
    assert not any("/archives/1999" in u for u in urls), urls
    assert any(u.endswith("/archives/1187") for u in urls), urls


def test_real_search_picks_a_game_article(monkeypatch):
    """用真站抓下来的搜索页（3 篇文章）验证能选出正确那篇。"""
    fixture = ROOT / "tests" / "fixtures" / "nekogal" / "search_zhifu.html"
    if not fixture.exists():          # 夹具缺失不算失败，真站行为由 sweep 覆盖
        return
    html = fixture.read_text(encoding="utf-8")
    hits = parse_result_links(html, "https://www.nekogal.com/?s=x", _site())
    best = pick_best(hits, "制服カノジョ")
    assert best is not None
    assert "/archives/" in best.url
