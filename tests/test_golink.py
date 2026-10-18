r"""`?golink=<base64>` 是网盘跳板，必须解码成真链。

实测 2026-10-18（nekogal，Zibll 主题）：详情页「资源下载」区里是
    <a class="file-download-btn" href="https://www.nekogal.com/?golink=aHR0cHM6Ly9wYW4ubmVrb2dhbC50b3Avcy9rQVpIYQ==&nonce=bb77">下载</a>
base64 解出来才是真网盘地址 `https://pan.nekogal.top/s/kAZHa`。
不解码的话整页 0 条下载链接（该站因此一直 NO_DOWNLOADS）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from finder.detail import decode_golink, extract_downloads  # noqa: E402


def test_decode_golink_base64():
    html = (
        '<a class="file-download-btn" '
        'href="https://www.nekogal.com/?golink=aHR0cHM6Ly9wYW4ubmVrb2dhbC50b3Avcy9rQVpIYQ=='
        '&amp;nonce=bb775b42e8">下载</a>'
    )
    urls = decode_golink(html)
    assert "https://pan.nekogal.top/s/kAZHa" in urls, urls


def test_golink_wrapper_itself_is_not_a_download():
    """跳板 URL 本身不该出现在下载列表里（点它只是 302）。"""
    html = (
        '<a href="https://www.nekogal.com/?golink=aHR0cHM6Ly9wYW4ubmVrb2dhbC50b3Avcy9rQVpIYQ==">下载</a>'
    )
    urls = [d.url for d in extract_downloads(html, "https://www.nekogal.com/archives/67")]
    assert not any("golink=" in u for u in urls), urls
    assert any("pan.nekogal.top/s/" in u for u in urls), urls


def test_golink_decodes_to_pan_kind():
    html = (
        '<a href="https://www.nekogal.com/?golink=aHR0cHM6Ly9wYW4ubmVrb2dhbC50b3Avcy9rQVpIYQ==">下载</a>'
    )
    dl = {d.url: d for d in extract_downloads(html, "https://www.nekogal.com/archives/67")}
    d = dl["https://pan.nekogal.top/s/kAZHa"]
    assert d.kind == "pan", d


def test_non_golink_base64_is_ignored():
    """别的参数里恰好有 base64 也不能乱解。"""
    html = '<a href="https://x.com/?nonce=aHR0cHM6Ly9ldmlsLmNvbS8=">x</a>'
    assert decode_golink(html) == []


def test_cover_images_behind_share_host_are_not_downloads():
    """封面图也在 `pan.nekogal.top` 上，但它们是 `/f/xxx.webp`，不是网盘分享。

    实测 2026-10-18：把「主机名以 pan. 开头」当网盘后，封面图
    `pan.nekogal.top/f/xwdiR/千恋万花.webp&summary=...`（后缀被分享参数污染）
    也混进了下载列表。真分享是 `/s/<id>`。
    """
    html = """
    <img src="https://pan.nekogal.top/f/xwdiR/%E5%8D%83%E6%81%8B%E4%B8%87%E8%8A%B1.webp&summary=x">
    <img src="https://pan.nekogal.top/f/5QRhn/%E5%8D%83%E6%81%8B%E4%B8%87%E8%8A%B102.webp">
    <a href="https://www.nekogal.com/?golink=aHR0cHM6Ly9wYW4ubmVrb2dhbC50b3Avcy9rQVpIYQ==">下载</a>
    """
    urls = [d.url for d in extract_downloads(html, "https://www.nekogal.com/archives/67")]
    assert not any("/f/" in u for u in urls), urls
    assert "https://pan.nekogal.top/s/kAZHa" in urls, urls


def test_golink_to_official_site_is_not_a_download():
    """「游戏官网」也是 golink 包装，但它不是下载链接。"""
    html = (
        '<a href="https://www.nekogal.com/?golink='
        'aHR0cHM6Ly93d3cueXV6dS1zb2Z0LmNvbS9wcm9kdWN0cy9zZW5yZW4v">游戏官网</a>'
    )
    urls = [d.url for d in extract_downloads(html, "https://www.nekogal.com/archives/67")]
    assert not any("yuzu-soft" in u for u in urls), urls
