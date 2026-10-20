"""对象存储直链：路径就是文件本体，URL 里没有 download 之类的词。

实测依据（2026-10-18，inarigal `/detail/684` 制服女友）：点「下载资源」后
getdownload API 返回
`https://annnnnnn.soraflie.top/old/PC/%E5%88%B6%E6%9C%8D%E5%A5%B3%E5%8F%8B.rar?Authorization=...`
—— 原 `_classify` 判成 unknown，UI 上它就会被归到"未知类型"。
"""
from __future__ import annotations

import pytest

from finder.detail import _classify

_OBJ = "https://annnnnnn.soraflie.top/old/PC/%E5%88%B6%E6%9C%8D%E5%A5%B3%E5%8F%8B.rar?Authorization=3_20261018104647_410"


@pytest.mark.parametrize(
    "url",
    [
        _OBJ,
        "https://cdn.example.com/files/game.zip",
        "https://cdn.example.com/game.7z",
        "https://cdn.example.com/game.tar.gz",
        "https://cdn.example.com/game.iso",
        "https://cdn.example.com/game.apk",
        "https://cdn.example.com/game.EXE",
        "https://cdn.example.com/game.msi",
        "https://cdn.example.com/game.dmg",
    ],
)
def test_archive_paths_are_direct(url):
    assert _classify(url) == "direct"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/detail/684",          # 详情页
        "https://example.com/page.php?id=1",
        "https://example.com/cover.webp",          # 封面图
        "https://example.com/",                    # 首页
        "https://example.com/rar",                 # 只是路径里出现 rar，没扩展名
    ],
)
def test_non_archives_stay_unknown(url):
    assert _classify(url) != "direct"


def test_pan_and_filehost_are_unaffected():
    assert _classify("https://pan.baidu.com/s/1abc?pwd=x") == "pan"
    assert _classify("magnet:?xt=urn:btih:" + "a" * 40) == "magnet"
    assert _classify("https://rapidgator.net/file/abc/x.rar.html") == "filehost"


@pytest.mark.parametrize(
    "url",
    [
        # galgamex 真机实测（2026-10-20，`/game/cbe7d89e`）：直链成对出现，
        # 第一卷是 `.z01`（7z 分卷），原白名单只认 `.zip`，它被判成 unknown。
        "https://game.galgamex.com/5001-5500/Gamex-005103/%23A8824.z01",
        "https://cdn.example.com/game.7z.001",
        "https://cdn.example.com/game.r00",
        "https://cdn.example.com/game.part3.rar",
        "https://cdn.example.com/game.zip?X-Amz-Signature=abc",
    ],
)
def test_multi_volume_archives_are_direct(url):
    """分卷包（.z01/.r00/.partN）也是下载物，不能落进 unknown。"""
    assert _classify(url) == "direct"


def test_z_prefix_without_digits_is_not_direct():
    """别把 `z` 开头的普通路径误伤成下载（白名单要求 2-3 位数字）。"""
    assert _classify("https://example.com/zeta") != "direct"
    assert _classify("https://example.com/game.z") != "direct"
