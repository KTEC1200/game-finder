from pathlib import Path
import pytest
from finder.sites import load_sites

PROJECT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def sites():
    return load_sites(PROJECT / "sites.yaml")


def test_loads_all_22_sites(sites):
    assert len(sites) == 22


def test_ids_are_unique(sites):
    ids = [s.id for s in sites]
    assert len(ids) == len(set(ids))


def test_mode_counts_match_spec(sites):
    url = [s for s in sites if s.search.mode == "url"]
    form = [s for s in sites if s.search.mode == "form"]
    assert len(url) == 17, f"expected 17 url-mode, got {len(url)}: {[s.id for s in url]}"
    assert len(form) == 5, f"expected 5 form-mode, got {len(form)}: {[s.id for s in form]}"
    assert {s.id for s in form} == {
        "gamebounty", "sayafx", "touchgal", "zi0", "anime-sharing"
    }


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
    """spec §2.1.5 已核算：zh=17 / en=18 / ja=12。"""
    for lang, expected in (("zh", 17), ("en", 18), ("ja", 12)):
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
    assert len(part) == 12
    assert len(part) + len(skipped) == 22
    assert all("ja" in s.langs for s in part)
    assert all("ja" not in s.langs for s in skipped)
