"""UI：搜索引擎兜底块（结果区上方单独一块）。

用户要求（原文，m01166）：
  「如果出来的结果少于三个，在必应、百度、谷歌、Yandex也进行搜索和整合，
    不过不用给出结果，给跳转链接就行」

确认过的位置（m01187）：「结果区上方单独一块」，不混进卡片列表。

和 `test_ui_hint.py` 一样是**静态结构断言**（单文件内联 JS，没有构建、
没有 JS 测试运行器）。这里锁三件在真机上会静默坏掉的事：
  1. 容器必须在 `<main id="out">` **之前**，且默认隐藏；
  2. 每次新搜索必须清空旧块（否则上一次查询的引擎链接会残留）；
  3. 链接只来自后端 `engines` 帧、且必须过 `safeUrl()`（防 javascript:）。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

HTML = Path(__file__).resolve().parent.parent / "finder" / "web" / "static" / "index.html"


@pytest.fixture(scope="module")
def src() -> str:
    return HTML.read_text(encoding="utf-8")


def test_engines_block_exists_before_results(src):
    i_block = src.index('id="engines"')
    i_main = src.index('<main id="out">')
    assert i_block < i_main, "兜底块必须在结果列表之前（用户要求「结果区上方」）"


def test_engines_block_is_empty_and_hidden_by_default(src):
    m = re.search(r'<div class="engines" id="engines"[^>]*>(.*?)</div>\s*(?=<main|<div)',
                  src, re.S)
    assert m, "找不到 #engines 容器"
    assert m.group(1).strip() == "", f"#engines 初始不该有内容，实际 {m.group(1)!r}"
    css = re.search(r"\.engines \{(.*?)\}", src, re.S)
    assert css, "找不到 .engines 样式"
    assert "display:none" in css.group(1), "默认必须隐藏，收到 engines 帧才显示"


def test_engines_block_is_cleared_on_every_search(src):
    """新搜索开始时必须清空，否则上一次的引擎链接会留在页面上。"""
    m = re.search(r"async function search\(refresh\) \{(.*?)\n\}", src, re.S)
    assert m, "找不到 search() 函数"
    body = m.group(1)
    assert re.search(r"engines\.innerHTML\s*=\s*''", body), "search() 里没清空 #engines"
    assert re.search(r"engines\.style\.display\s*=\s*'none'", body), (
        "search() 里没把 #engines 重新藏起来"
    )


def test_engines_frame_is_rendered(src):
    assert re.search(r"ev === 'engines'", src), "前端没有处理 engines 帧"
    # 四档 outcome 的分支之后必须还有 engines 分支，不能只处理 result/done
    assert src.index("ev === 'engines'") > src.index("ev === 'start'")


def test_engine_links_go_through_safeUrl(src):
    """URL 来自后端（最终来自用户输入拼的），绝不能直接赋 href。"""
    m = re.search(r"function renderEngines\((.*?)\n\}", src, re.S)
    assert m, "找不到 renderEngines()"
    body = m.group(1)
    assert "safeUrl(" in body, "引擎链接必须过 safeUrl()"
    assert re.search(r"a\.target\s*=\s*'_blank'", body)
    assert re.search(r"a\.rel\s*=\s*'noopener noreferrer'", body)


def test_engine_link_text_comes_from_backend_names(src):
    """按钮文案用后端给的 name（必应/百度/谷歌/Yandex），不在 JS 里再抄一份。"""
    m = re.search(r"function renderEngines\((.*?)\n\}", src, re.S)
    assert m, "找不到 renderEngines()"
    body = m.group(1)
    assert "x.name" in body or "link.name" in body


def test_engines_never_interpolate_site_data_into_innerHTML(src):
    """兜底块的说明文字是常量；引擎名字走 textContent（el()）。"""
    for rhs in re.findall(r"engines\.innerHTML\s*=\s*([^;]+);", src):
        rhs = rhs.strip()
        assert rhs == "''" or rhs.startswith("ENGINES_TITLE"), (
            f"engines.innerHTML 只允许清空或常量，实际 {rhs!r}"
        )
