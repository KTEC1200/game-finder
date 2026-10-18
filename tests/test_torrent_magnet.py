r"""`.torrent` 文件 → 磁力链（byrutgame 实测）。

2026-10-18：byrutgame 详情页的下载按钮是
    https://byrutgame.org/index.php?do=download&id=150587
点它返回 `application/x-bittorrent` 的种子文件（55625 字节），
种子本身不是「下载链接」，用户要的是磁力链。info hash 就是 info 字典
的 SHA1，磁力链 = `magnet:?xt=urn:btih:<sha1>`。

该站 `kinds` 声明是 [直链, 磁力]，但整页 HTML 里没有任何 magnet: 文本，
所以只能取到种子、本地算 hash。
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from finder.detail import build_magnet_from_torrent, torrent_info_hash  # noqa: E402


def _torrent(info: bytes, extra: bytes = b"") -> bytes:
    """拼一个最小合法 torrent：d 8:announce… 4:info<info> e"""
    return b"d8:announce" + str(len(b"http://t/a")).encode() + b":http://t/a" + extra + b"4:info" + info + b"e"


def test_info_hash_matches_manual_sha1():
    info = b"d6:lengthi42e4:name4:test12:piece lengthi16384e6:pieces20:aaaaaaaaaaaaaaaaaaaae"
    data = _torrent(info)
    assert torrent_info_hash(data) == hashlib.sha1(info).hexdigest()


def test_build_magnet_from_torrent():
    info = b"d6:lengthi42e4:name4:teste"
    m = build_magnet_from_torrent(_torrent(info))
    assert m == "magnet:?xt=urn:btih:" + hashlib.sha1(info).hexdigest()


def test_garbage_bytes_return_none():
    assert torrent_info_hash(b"not a torrent at all") is None
    assert build_magnet_from_torrent(b"") is None


def test_truncated_torrent_returns_none():
    """下载被截断（只有头部）时必须返回 None，不能算出一个假 hash。"""
    info = b"d6:lengthi42e4:name4:teste"
    data = _torrent(info)
    assert torrent_info_hash(data[: len(data) // 2]) is None


def test_nested_dict_inside_info_is_handled():
    """info 里常有嵌套 dict/list，必须按 bencode 结构跳过而不是找字符串。"""
    info = (
        b"d5:filesd4:testd6:lengthi1eee"
        b"4:name4:test12:piece lengthi16384e6:pieces20:aaaaaaaaaaaaaaaaaaaae"
    )
    data = _torrent(info)
    assert torrent_info_hash(data) == hashlib.sha1(info).hexdigest()
