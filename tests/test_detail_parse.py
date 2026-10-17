from pathlib import Path

import pytest

from finder.detail import extract_card, extract_downloads, decode_qr_pan_links

FIX = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="module")
def jidi_html():
    return (FIX / "jidiyouxi" / "detail_xingxing.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def g520_landing_html():
    return (FIX / "gamer520" / "go_landing_sample.html").read_text(encoding="utf-8")


def test_jidi_downloads_found_outside_anchor_tags(jidi_html):
    """核心回归：链接在整页 HTML 里，不在 <a> 标签里。"""
    dl = extract_downloads(jidi_html, "https://www.jidiyouxi.com/topic/detail/171085167")
    assert len(dl) >= 10, f"expected many pan links, got {len(dl)}"
    assert all(d.kind == "pan" for d in dl)
    assert any("pan.baidu.com" in d.url for d in dl)
    assert any("pan.quark.cn" in d.url for d in dl)


def test_jidi_download_urls_have_pwd_or_code(jidi_html):
    dl = extract_downloads(jidi_html, "https://www.jidiyouxi.com/topic/detail/171085167")
    with_pwd = [d for d in dl if "pwd=" in d.url]
    assert with_pwd, "expected ?pwd= on baidu/xunlei links"


def test_jidi_cover_is_not_the_broken_og_image(jidi_html):
    """og:image 是 '[object Object]'，必须回退到 preload link。"""
    card = extract_card(jidi_html, "https://www.jidiyouxi.com/topic/detail/171085167",
                        "jidiyouxi")
    assert card.cover_url is not None
    assert "[object Object]" not in card.cover_url
    assert card.cover_url.startswith("http")


def test_jidi_card_has_title_and_intro(jidi_html):
    card = extract_card(jidi_html, "https://www.jidiyouxi.com/topic/detail/171085167",
                        "jidiyouxi")
    assert card.title and len(card.title) > 4
    assert card.intro and len(card.intro) > 20
    assert card.site_id == "jidiyouxi"


def test_g520_landing_links_extracted(g520_landing_html):
    dl = extract_downloads(g520_landing_html, "https://520.gamers520.com/41170.html")
    assert dl, "landing page must yield download links"
    kinds = {d.kind for d in dl}
    assert "pan" in kinds


def test_qr_encoded_pan_links_are_decoded(g520_landing_html):
    """gamer520 用 api.qrserver.com?...&data=<urlencoded> 藏链接。"""
    urls = decode_qr_pan_links(g520_landing_html)
    assert urls, "expected QR-embedded pan urls"
    assert any("pan.baidu.com" in u or "pan.quark.cn" in u for u in urls)


def test_empty_html_is_safe():
    card = extract_card("<html><body></body></html>", "https://x.com/", "x")
    assert card.downloads == []
    assert card.title == ""
