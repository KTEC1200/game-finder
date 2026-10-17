import pytest
from finder.lang import detect_lang


@pytest.mark.parametrize("text,expected", [
    # 中文：CJK 汉字，无假名
    ("终焉之莉莉", "zh"),
    ("千恋万花", "zh"),
    ("赛博朋克2077", "zh"),
    # 英文：无 CJK 无假名
    ("enderlilies", "en"),
    ("ENDER LILIES", "en"),
    ("Ender-Lilies", "en"),
    ("café 123", "en"),
    # 日文：含假名（优先于 CJK）
    ("終焉のリリィ", "ja"),
    ("リリィ", "ja"),
    ("サクラノ詩", "ja"),
    # 混排：假名优先 → ja
    ("ENDER LILIES 終焉のリリィ", "ja"),
    # 混排：中英无假名 → zh（CJK 优先于拉丁）
    ("Ender Lilies 终焉之莉莉", "zh"),
    # 边界：空与纯空白 → en（无 CJK 特征）
    ("", "en"),
    ("   ", "en"),
    ("123", "en"),
])
def test_detect_lang(text, expected):
    assert detect_lang(text) == expected


def test_detect_lang_accepts_none_like_whitespace():
    """前后空白不影响判定。"""
    assert detect_lang("  终焉之莉莉  ") == "zh"
