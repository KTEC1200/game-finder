"""语种判定 —— 纯函数，无网络无 IO，可离线单测。

规则（与 spec §2.1.5 一致）：
  含日文假名            -> "ja"
  否则含 CJK 汉字       -> "zh"
  否则                  -> "en"
假名优先于汉字，因为日文常混用汉字；中英混排无假名时判为中文。
"""
from __future__ import annotations

import re

# 平假名 U+3040-U+309F + 片假名 U+30A0-U+30FF
KANA_RE = re.compile(r"[\u3040-\u30ff]")
# CJK 统一表意文字
CJK_RE = re.compile(r"[\u4e00-\u9fff]")

SUPPORTED_LANGS = ("zh", "en", "ja")


def detect_lang(text: str) -> str:
    """判定输入文本的语种，返回 'zh' | 'en' | 'ja'。"""
    if not text:
        return "en"
    if KANA_RE.search(text):
        return "ja"
    if CJK_RE.search(text):
        return "zh"
    return "en"
