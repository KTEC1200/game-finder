from pathlib import Path
import pytest
from finder.sites import load_sites

PROJECT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def sites():
    return load_sites(PROJECT / "sites.yaml")


def test_loads_all_21_sites(sites):
    """zi0 因实测无站内搜索被移出注册表（2026-10-18）。"""
    assert len(sites) == 21


def test_ids_are_unique(sites):
    ids = [s.id for s in sites]
    assert len(ids) == len(set(ids))


def test_mode_counts_match_spec(sites):
    """三种 mode 的归属是 2026-10-18 逐站实测的结论，不是估算。

    url:   地址栏模板直接可用（含 gamebounty /zh/search 与 anime-sharing /search/1）
    index: 站点下发客户端搜索索引，本地过滤（sayafx /search.xml）
    form:  只能进站内搜索页填框（touchgal）
    """
    url = [s for s in sites if s.search.mode == "url"]
    form = [s for s in sites if s.search.mode == "form"]
    index = [s for s in sites if s.search.mode == "index"]
    assert len(url) == 19, f"expected 19 url-mode, got {len(url)}: {[s.id for s in url]}"
    assert len(form) == 1, f"expected 1 form-mode, got {len(form)}: {[s.id for s in form]}"
    assert len(index) == 1, f"expected 1 index-mode, got {len(index)}: {[s.id for s in index]}"
    assert {s.id for s in form} == {"touchgal"}
    assert {s.id for s in index} == {"sayafx"}
    assert "zi0" not in {s.id for s in sites}


def test_url_mode_always_has_template(sites):
    for s in sites:
        if s.search.mode == "url":
            assert s.search.url_template, f"{s.id} url mode needs url_template"
            assert "{q}" in s.search.url_template, f"{s.id} template needs {{q}}"


def test_url_searchable_agrees_with_mode(sites):
    for s in sites:
        assert s.url_searchable == (s.search.mode == "url"), f"{s.id} mismatch"


def test_langs_are_valid(sites):
    for s in sites:
        assert s.langs, f"{s.id} needs at least one lang"
        assert s.langs <= {"zh", "en", "ja"}, f"{s.id} bad langs {s.langs}"


def test_language_coverage_counts(sites):
    """移出 zi0 后的实测覆盖：zh=16 / en=17 / ja=11（总 21）。"""
    for lang, expected in (("zh", 16), ("en", 17), ("ja", 11)):
        got = sum(1 for s in sites if lang in s.langs)
        assert got == expected, f"{lang}: expected {expected}, got {got}"


def test_known_specials(sites):
    by_id = {s.id: s for s in sites}
    assert by_id["acggw"].max_query_len == 10, "ACG 港湾 搜索词 ≤10"
    assert by_id["galgame.dev"].needs_login is True, "真红需登录"
    assert "jidiyouxi" in by_id and by_id["jidiyouxi"].langs == {"zh"}


def test_filter_by_lang_returns_participating_and_skipped(sites):
    from finder.sites import filter_sites_by_lang
    part, skipped = filter_sites_by_lang(sites, "ja")
    assert len(part) == 11
    assert len(part) + len(skipped) == 21
    assert all("ja" in s.langs for s in part)
    assert all("ja" not in s.langs for s in skipped)
