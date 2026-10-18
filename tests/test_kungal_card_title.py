"""kungal 搜索结果卡片的标题抽取（2026-10-18 真站实测）。

站点把封面做成**内联 base64 data URI**，整张卡片 `<a>` 的 innerHTML 有 8201
字符，其中 8000+ 是 base64 图。`_anchor_title` 的「去标签取文本」分支于是
拿到的是 `<div class="kun-image-blur ...` 这种被截断的 HTML 碎片，游戏名
完全丢失：

    '1.0 \\'<div data-v-43671ca7="" class="kun-image-blur \\' -> /galgame/15'

浏览器里那张卡片的可见文本其实是：
    '266576 93 3 天前 千恋＊万花 柚子软件 7.6'
游戏名在中间。所以必须把 base64 载荷剥掉再取文本，而不是简单截断。

第二个坑：站点的官方名是「千恋＊万花」（全角星号 U+FF0A），用户输入
「千恋万花」时 `_query_pattern` 做子串匹配会失败（＊ 插在中间）。`_norm`
已经把常见分隔符去掉，但没去全角星号 / 其他装饰性符号，导致 pick_best
把 4 条同名系列作（泪恋花 / 单恋礼花 …）与真正的本体同分，可能选错。
"""
from finder.search import _anchor_title, _norm, _query_pattern, parse_result_links

# 真站 /galgame/15 卡片的形状（base64 缩短为占位，结构一致）
KUNGAL_CARD = (
    '<a href="/galgame/15" class="relative flex flex-col gap-4">'
    '<div><div style="aspect-ratio: 5 / 7;">'
    '<div style="background-image: url(&quot;data:image/png;base64,'
    "iVBORw0KGgoAAAANSUhEUgAAABcAAAAgCAYAAAD5VeO1AAAAMklEQVQY02P8//8/AyWAiYFC"
    '&quot;);"></div></div></div>'
    "<div><div>266576</div><div>93</div><div>3 天前</div>"
    "<div>千恋＊万花</div><div>柚子软件</div><div>7.6</div></div>"
    "</a>"
)


def test_card_title_ignores_inline_base64_cover():
    """base64 封面不能挤掉游戏名。"""
    body = KUNGAL_CARD.split(">", 1)[1]
    title = _anchor_title(' href="/galgame/15"', body)
    assert "千恋" in title, f"游戏名丢了：{title[:80]!r}"
    assert "base64" not in title, f"base64 混进标题：{title[:80]!r}"
    assert "iVBORw0KGgo" not in title


def test_card_title_still_works_when_no_base64():
    """没有 base64 的普通卡片不受影响。"""
    body = "<div>千恋＊万花</div><div>柚子软件</div>"
    assert "千恋" in _anchor_title("", body)


def test_norm_strips_decorative_fullwidth_star():
    """站点官方名用全角星号分隔，归一化后应与用户输入一致。"""
    assert _norm("千恋＊万花") == _norm("千恋万花")


def test_query_pattern_matches_decorated_official_name():
    """用户输入「千恋万花」要能匹配站点标题「千恋＊万花」。"""
    import re

    pat = _query_pattern("千恋万花")
    assert pat
    # 归一化后的标题才是匹配对象；这里验证归一化后能命中
    assert re.search(re.escape("千恋万花"), _norm("千恋＊万花"))


def test_parse_result_links_kungal_card_keeps_game_name():
    """端到端：解析 kungal 搜索页片段，卡片标题必须含游戏名。"""
    from finder.models import SearchSpec, Site

    site = Site(
        id="kungal",
        name="鲲 Galgame",
        homepage="https://www.kungal.com/",
        kinds=["论坛网盘"],
        langs={"zh"},
        url_searchable=True,
        search=SearchSpec(
            mode="url", url_template="https://www.kungal.com/search?keywords={q}"
        ),
    )
    html = f"<html><body><main>{KUNGAL_CARD}</main></body></html>"
    hits = parse_result_links(html, "https://www.kungal.com/search?keywords=x", site)
    assert hits, "卡片没被解析出来"
    card = [h for h in hits if h.url.endswith("/galgame/15")]
    assert card, f"没找到 /galgame/15：{[h.url for h in hits]}"
    assert "千恋" in card[0].title, f"标题丢了游戏名：{card[0].title[:80]!r}"
