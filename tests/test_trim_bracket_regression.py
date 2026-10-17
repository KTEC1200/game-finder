"""Verify the '[' regression: sayafx direct URLs legally contain '['."""
from finder.detail import _trim_url


def test_trim_keeps_square_brackets_in_legal_path():
    """sayafx 实测：/Cloudflare/part1/[200214][ゆずソフト] 千恋... 是合法直链。

    早期版本在 '[' 处截断，把 7 条下载砍到 5 条（2026-10-18 真站复验发现）。
    """
    url = ("https://dl.sayafx.vip/Cloudflare/part1/"
           "[200214][%E3%82%86%E3%81%9A%E3%82%BD%E3%83%95%E3%83%88]%20%E5%8D%83"
           "%E6%81%8B.zip")
    assert _trim_url(url) == url


def test_trim_still_cuts_markdown_link_form():
    assert _trim_url(
        "https://pan.quark.cn/s/7c51265e86f2](https://pan.quark.cn/s/7c51265e86f2"
    ) == "https://pan.quark.cn/s/7c51265e86f2"
