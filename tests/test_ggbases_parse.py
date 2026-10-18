r"""ggbases 结果页的两个解析缺陷（2026-10-18 真站实测）。

站上真实结构（`search.so?p=0&title=制服カノジョ`）：
    <tr class="dtr t_trusted">
      <td>...<a href="//ggbases.dlgal.com/magnet.so?id=131080">M</a></td>
      <td class="t-l">
        <a index="0" id="bid131080" name="title" href="//ggbases.dlgal.com/view.so?id=131080">
          <a class="keya bc1" href="...title=2D.G.F." title="2D.G.F.">2D.G.F.</a>
          <a class="keya bc2" title="260910">260910</a>
          ...
          <b>制服カノジョ3 めいか初恋BOX パッケージ版 + 同梱特典 [3112MB]</b>
        </a>
      </td>
    </tr>

缺陷 1：标题被嵌套锚点的 title= 抢走。
  `_anchor_title` 在 `attrs + body[:400]` 上找 title=/alt=，命中的是内层
  `<a class="keya" title="2D.G.F.">` 的**上传者名**，游戏名丢失 →
  pick_best 拿不到任何查询词命中，全部候选同分。

缺陷 2：`view.so?id=131080` 被判成 0.5 分。
  路径里既没有 `/数字` 也没有 `.html`，`DETAILISH_RE` 不认；
  而 `/2257.so`（站点法务页）反而被 `/\d{2,}` 认成详情页并给 1.0。
  结果 pick_best 在 1.0 池里只剩法务页可选 → 三语全部 WRONG_GAME。
"""
from finder.models import Site
from finder.search import _anchor_title, parse_result_links, pick_best


def _site() -> Site:
    from finder.models import SearchSpec
    return Site(
        id="ggbases", name="GGBases", homepage="https://ggbases.dlgal.com/",
        kinds=["磁力"], langs={"ja"}, url_searchable=True,
        search=SearchSpec(mode="url",
                          url_template="https://ggbases.dlgal.com/search.so?p=0&title={q}"),
    )


ROW_HTML = """
<table><tr><th>#</th><th>標題</th></tr>
<tr class="dtr t_trusted" pub="mikocon" title="x">
  <td class="bt_path1">
    <a href="//ggbases.dlgal.com/down.so?id=131080" title="BT 文件"><span>B</span></a>
    <a href="//ggbases.dlgal.com/magnet.so?id=131080" title="磁力鏈結"><span>M</span></a>
  </td>
  <td class="t-l">
    <a index="0" id="bid131080" name="title" target="_blank"
       href="//ggbases.dlgal.com/view.so?id=131080"><a class="keya bc1"
       href="//ggbases.dlgal.com/search.so?title=2D.G.F." title="2D.G.F.">2D.G.F.</a><a
       class="keya bc2" href="//ggbases.dlgal.com/search.so?title=260910"
       title="260910">260910</a><b> 制服カノジョ3 めいか初恋BOX パッケージ版 + 同梱特典
       [3112MB]</b></a>
  </td>
  <td class="t-l"><span>3.04 G</span></td>
</tr></table>
"""


def test_nested_anchor_title_does_not_override_real_title():
    """内层 <a title="上传者"> 不能当成详情链接的标题。"""
    attrs = (' index="0" id="bid131080" name="title" target="_blank" '
             'href="//ggbases.dlgal.com/view.so?id=131080"')
    body = ('<a class="keya bc1" href="x" title="2D.G.F.">2D.G.F.</a>'
            '<b> 制服カノジョ3 めいか初恋BOX</b></a>')
    title = _anchor_title(attrs, body)
    assert "制服カノジョ" in title, f"真实游戏名丢失，取到的是 {title!r}"
    assert title != "2D.G.F."


def test_nested_img_alt_still_works():
    """内层 <img alt=> 是常见的封面标题写法，不能被上面那条修复误伤。"""
    attrs = ' href="/game/123"'
    body = '<img src="c.jpg" alt="Ender Lilies Quietus"></a>'
    assert "Ender Lilies" in _anchor_title(attrs, body)


def test_own_title_attr_still_wins():
    """锚点自身的 title= 优先（很多站用它当标题）。"""
    attrs = ' href="/game/1" title="剑星 完整版"'
    assert _anchor_title(attrs, "<img alt='无关'></a>") == "剑星 完整版"


def test_ggbases_detail_link_is_recognized_as_detail_shape():
    """`view.so?id=131080` 必须被认成详情页，否则 pick_best 选不到它。"""
    hits = parse_result_links(ROW_HTML, "https://ggbases.dlgal.com/search.so?p=0&title=x",
                              _site())
    by_url = {h.url: h for h in hits}
    detail = [u for u in by_url if "view.so?id=131080" in u]
    assert detail, f"详情链接没被解析出来：{list(by_url)}"
    assert by_url[detail[0]].score >= 1.0, "详情链接被判成了非详情形状"


def test_ggbases_pick_best_returns_the_real_game_not_legal_page():
    """复现真站症状：法务页 `/2257.so` 混进候选时，仍要选中真游戏。"""
    html = ROW_HTML + '<a href="//ggbases.dlgal.com/2257.so">18 U.S.C. 2257 Statement</a>'
    hits = parse_result_links(html, "https://ggbases.dlgal.com/search.so?p=0&title=x",
                              _site())
    best = pick_best(hits, "制服カノジョ")
    assert best is not None
    assert "view.so?id=131080" in best.url, f"选错了：{best.url} / {best.title!r}"
    assert "制服カノジョ" in best.title
