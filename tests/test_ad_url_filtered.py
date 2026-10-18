"""广告/客户端安装包不能算下载。

jidiyouxi 实测（2026-10-18）：详情页 appState 的下载区块里混着迅雷游戏助手
安装包 `https://bj-file-xlas-down-al-game.xunlei.com/winapp/installer/Installer-1.13.0-release-100010.exe`。
它满足 `.exe` 直链形状，被 `_classify` 判成 direct 后混进下载列表 —— 用户点
「下载」会拿到一个迅雷安装器，这是最糟糕的一类失败。
"""
from __future__ import annotations

from pathlib import Path

from finder.detail import AD_URL_RE, extract_downloads

FIX = Path(__file__).resolve().parent / "fixtures" / "jidiyouxi" / "detail_xingxing.html"


def test_xunlei_installer_matches_ad_pattern():
    url = (
        "https://bj-file-xlas-down-al-game.xunlei.com/winapp/installer/"
        "Installer-1.13.0-release-100010.exe"
    )
    assert AD_URL_RE.search(url)


def test_real_pan_links_do_not_match_ad_pattern():
    for url in (
        "https://pan.baidu.com/s/1Uf4KDyLPwWFvGUbp1U3jBw?pwd=h2bb",
        "https://pan.xunlei.com/s/VOlOf6vQ2HJFuTSD6CCA5NpEA1?pwd=63w5",
        "https://pan.quark.cn/s/58a8238da8ba?pwd=yr58",
    ):
        assert not AD_URL_RE.search(url)


def test_jidiyouxi_fixture_has_no_installer_in_downloads():
    html = FIX.read_text(encoding="utf-8")
    dl = extract_downloads(html, "https://www.jidiyouxi.com/topic/detail/171085167")
    assert dl, "fixture 应该能抽出网盘链"
    assert all("winapp/installer" not in d.url for d in dl)
    assert all(d.kind == "pan" for d in dl), [(d.kind, d.url) for d in dl]
