from finder.models import Site, SearchSpec, Download, GameDetail


def test_site_langs_is_a_set_of_supported_codes():
    s = Site(
        id="gamer520", name="Gamer520", homepage="https://www.gamer520.com/",
        kinds=["网盘"], langs={"zh", "en"}, url_searchable=True,
        search=SearchSpec(mode="url", url_template="https://www.gamer520.com/?s={q}"),
    )
    assert s.langs == {"zh", "en"}
    assert s.adapter_status == "untested"   # 默认值
    assert s.needs_login is False           # 默认值
    assert s.max_query_len is None          # 默认值


def test_search_spec_form_mode_allows_no_template():
    spec = SearchSpec(mode="form", input_selector="input#s")
    assert spec.mode == "form"
    assert spec.url_template is None


def test_download_kind_is_constrained():
    d = Download(kind="pan", url="https://pan.baidu.com/s/abc", label="百度网盘", code="1234")
    assert d.kind == "pan"
    assert d.code == "1234"


def test_game_detail_defaults():
    g = GameDetail(site_id="x", url="https://e.com/1", title="t")
    assert g.downloads == []
    assert g.intro is None
    assert g.extra == {}
