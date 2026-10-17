"""URL 尾巴裁剪（touchgal 实测的 Markdown 污染）。"""
from finder.detail import _trim_url, extract_downloads


def test_trim_url_cuts_markdown_suffix():
    assert _trim_url(
        "https://pan.quark.cn/s/7c51265e86f2](https://pan.quark.cn/s/7c51265e86f2"
    ) == "https://pan.quark.cn/s/7c51265e86f2"


def test_trim_url_cuts_trailing_punctuation():
    assert _trim_url("https://pan.baidu.com/s/abc).") == "https://pan.baidu.com/s/abc"


def test_trim_url_leaves_clean_url_alone():
    assert _trim_url("https://pan.quark.cn/s/92f5c6d27e54") == \
        "https://pan.quark.cn/s/92f5c6d27e54"


def test_extract_downloads_dedupes_markdown_duplicates():
    """touchgal 实测：同一个夸克链接在正文里出现两次（纯文本 + Markdown 形式），
    剥壳后必须只剩 1 条，不能是 2 条畸形串。"""
    html = (
        "<html><body>"
        "<p>下载 https://pan.quark.cn/s/92f5c6d27e54</p>"
        "<p>工具 [链接](https://pan.quark.cn/s/92f5c6d27e54)</p>"
        "</body></html>"
    )
    dl = extract_downloads(html, "https://www.touchgal.ink/x/resource/1")
    quarks = [d.url for d in dl if "pan.quark.cn" in d.url]
    assert quarks == ["https://pan.quark.cn/s/92f5c6d27e54"], quarks


def test_extract_downloads_recognises_datanodes():
    html = '<html><body><a href="https://datanodes.to/femnrlftvkqg">x</a></body></html>'
    dl = extract_downloads(html, "https://gamebounty.world/x")
    assert [d.kind for d in dl] == ["filehost"]
