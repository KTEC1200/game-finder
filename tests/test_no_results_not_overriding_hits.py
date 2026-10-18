"""「无结果」文案不能盖掉真实候选。

playzip 的 `No results found, request game` 是**常驻模板**：查
`hollow knight` 解析出 2 条真结果，那个 div 依然 display:block 可见
（2026-10-18 真站实测）。纯文本无法区分「真的没有」与「模板一直在」，
只有「解析出候选」是硬证据。

同一份逻辑也保护了别的站：任何把空态模板留在 DOM 里的站点都不会被误判。
"""
from __future__ import annotations

from finder.pipeline import looks_no_results


def test_marker_text_alone_still_matches():
    """标记本身仍然要能识别（否则真无结果的站会退化成含糊报错）。"""
    assert looks_no_results("", "<div>No results found, request game</div>") is not None


def test_playzip_style_template_is_visibly_present_with_real_hits():
    """真机快照片段：有结果时模板文字仍在，所以不能只靠文本判定。"""
    html = """
      <div class="request"><b>No results found</b>, request game</div>
      <a href="/game/152">Hollow Knight</a>
      <a href="/game/2027">Hollow Knight: Silksong</a>
    """
    # 文本层命中了 —— 这正是必须由「有候选就覆盖」兜住的情形
    assert looks_no_results("", html) is not None
    from finder.search import parse_result_links
    from finder.sites import load_sites
    from pathlib import Path

    sites = {s.id: s for s in load_sites(Path(__file__).resolve().parents[1] / "sites.yaml")}
    hits = parse_result_links(html, "https://playzip.com/?keywords=x", sites["playzip"])
    assert len(hits) == 2, [h.url for h in hits]


def test_transient_network_error_page_is_not_mistaken_for_empty_results():
    """jidiyouxi 实测：站内接口挂掉时正文只有 `游戏专区 (0) … Network Error`。

    这类页面在 4s 后会自己渲染出来，必须重试；判成 NO_RESULTS 会把
    「站点抖一下」写成永久结论（还会进失败缓存）。
    """
    from finder.pipeline import _looks_transient

    broken = (
        "<html><body>首页 PC游戏 0 联机专区 游戏专区 (0) 手游 (0) "
        "无相关搜索 Network Error</body></html>"
    )
    assert _looks_transient(broken) is True


def test_a_real_result_page_is_not_transient():
    from finder.pipeline import _looks_transient

    good = "<html><body>" + ("游戏专区 (1) 黑神话:悟空 130GB 动作 冒险 " * 30) + "</body></html>"
    assert _looks_transient(good) is False
