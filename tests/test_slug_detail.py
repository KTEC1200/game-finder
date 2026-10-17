"""slug 型详情页识别（gamebounty / touchgal 实测的两条曾被判 0.5 分）。"""
from finder.models import SearchSpec, Site
from finder.search import parse_result_links, pick_best


def _site() -> Site:
    return Site(
        id="sluggy",
        name="Sluggy",
        homepage="https://sluggy.test/",
        kinds=["直链"],
        langs={"en"},
        url_searchable=True,
        search=SearchSpec(mode="url", url_template="https://sluggy.test/?q={q}"),
    )


def test_slug_download_path_is_detail_shape():
    """gamebounty 实测：/ender-lilies-...-free-pc-download 曾被判 0.5 分而选不中。"""
    html = (
        '<html><body>'
        '<a href="/ender-lilies-quietus-of-the-knights-free-pc-download">'
        "ENDER LILIES: Quietus of the Knights</a>"
        '<a href="/zh/support">捐赠</a>'
        "</body></html>"
    )
    hits = parse_result_links(html, "https://sluggy.test/zh/search?q=x", _site())
    by_url = {h.url: h for h in hits}
    target = "https://sluggy.test/ender-lilies-quietus-of-the-knights-free-pc-download"
    assert by_url[target].score == 1.0
    assert pick_best(hits, "enderlilies") is not None


def test_hex_id_path_is_detail_shape():
    """touchgal 实测：/6a4e9cad 这种 8 位十六进制 id 是详情页，曾被判 0.5 分。"""
    html = '<html><body><a href="/6a4e9cad">终焉之莉莉：骑士寂夜</a></body></html>'
    hits = parse_result_links(html, "https://sluggy.test/search", _site())
    assert hits[0].score == 1.0
    assert pick_best(hits, "终焉之莉莉") is not None


def test_nav_paths_stay_non_detail():
    """收窄校验：导航/分类路径不能被当成详情页。"""
    html = (
        '<html><body>'
        '<a href="/zh/support">捐赠</a>'
        '<a href="/about-us">关于</a>'
        "</body></html>"
    )
    hits = parse_result_links(html, "https://sluggy.test/", _site())
    assert all(h.score == 0.5 for h in hits), [(h.url, h.score) for h in hits]
    assert pick_best(hits, "enderlilies") is None
