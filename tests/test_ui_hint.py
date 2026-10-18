"""UI 换名提示：**一个站点都没出下载**时必须出现，并给出按语种定制的例子。

用户要求（原文，m00629）：
  「设计的时候，提前告知用户如果中文名搜索不到可以再尝试英文名和日文名」

真实缺陷（2026-10-18 复核）：旧触发条件是 `if (!gotAny)`，而 `gotAny` 只要收到
过任一 `result` 帧就为 true —— 每个站（哪怕 `NO_RESULTS`）都会回一帧，所以这个
提示在两次真站查询里**一次都没出现过**。真正该提示的是「无任何站点出下载」，
即 `done` 帧的 `data.ok === 0`。

这里做的是**静态结构断言**（index.html 是单文件内联 JS，没有构建、没有 JS 测试
运行器）：内容真实性由 `.superpowers/sdd/.../verify_ui_hint.py` 用真 Chrome 驱动
live 服务验（查一个必然 0 结果的词，断言提示真的显示出来）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

HTML = Path(__file__).resolve().parent.parent / "finder" / "web" / "static" / "index.html"


@pytest.fixture(scope="module")
def src() -> str:
    return HTML.read_text(encoding="utf-8")


def test_hint_triggers_on_zero_downloads_not_on_any_frame(src):
    assert "data.ok === 0" in src, (
        "提示必须在「无站点出下载」时出现；只看 !gotAny 会让它永不显示"
    )


def test_hint_is_empty_by_default(src):
    """提示容器初始必须为空 —— 否则会显示一条与本次查询无关的旧文案。"""
    m = re.search(r'<div class="hint" id="hint">(.*?)</div>', src, re.S)
    assert m, "找不到 #hint 容器"
    assert m.group(1).strip() == "", f"#hint 初始不该有内容，实际 {m.group(1)!r}"


def test_hint_map_covers_all_three_languages(src):
    m = re.search(r"const HINT_BY_LANG = \{(.*?)\n\};", src, re.S)
    assert m, "找不到 HINT_BY_LANG"
    body = m.group(1)
    for lang in ("zh", "en", "ja"):
        assert re.search(rf"\b{lang}:", body), f"HINT_BY_LANG 缺 {lang}"
    # 中文名搜不到是最常见的场景，必须给出英/日两种替代写法
    assert "Ender Lilies" in body and "制服カノジョ" in body


def test_hint_selection_falls_back_for_unknown_lang(src):
    """语种识别不到时不能拼出 undefined，要有兜底文案。"""
    assert "HINT_BY_LANG[lang] || HINT_FALLBACK" in src


def test_hint_never_interpolates_site_data(src):
    """提示文案只能来自常量表 —— 站点返回的字符串一律不许进 innerHTML。

    其余 UI 走 `el()`（textContent）转义；提示是唯一的 innerHTML 用法，
    所以它的右值必须严格是 HINT_BY_LANG[...] 或 HINT_FALLBACK。
    """
    rhs = re.findall(r"hint\.innerHTML\s*=\s*([^;]+);", src)
    assert rhs, "没找到 hint.innerHTML 赋值"
    for r in rhs:
        r = r.strip()
        assert r.startswith("HINT_BY_LANG[") or r == "HINT_FALLBACK", (
            f"hint.innerHTML 右值必须来自常量表，实际 {r!r}"
        )


def test_note_is_shown_up_front(src):
    """「提前告知」：输入框下面常驻一条换名提示，不用等搜不到才说。"""
    m = re.search(r'<div class="note" id="note">(.*?)</div>', src, re.S)
    assert m, "找不到常驻提示 #note"
    text = m.group(1)
    assert "英文名" in text and "日文原名" in text
    css = re.search(r"\.note \{(.*?)\}", src, re.S)
    assert css, "找不到 .note 样式"
    assert "display:none" not in css.group(1), "常驻提示不能默认隐藏"
