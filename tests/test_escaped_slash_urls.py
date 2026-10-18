"""页面内嵌 JSON 里的 `\\u002F` 转义斜杠必须还原（2026-10-18 kungal 实测）。

kungal 的资源页把正文存成 Nuxt 的 payload（一个巨大的内联 JSON 数组），
链接写成：

    "https:\\u002F\\u002Fpan.baidu.com\\u002Fs\\u002F1Dau8DVO5_HcMjOD4nFA4Qg?pwd=t7cp"

`URL_RE = r"https?://[^\\s\\"'<>\\\\]+"` 明确排除了反斜杠，所以
`https:\u002F\u002F...` 连开头 `https://` 都匹配不上 —— 整页 685 处
`\\u002F` 一条下载链接都抽不出来，卡片永远 NO_DOWNLOADS。

注意与已有转义的先后关系：
  - `&amp;` 由 `html_mod.unescape` 处理（QR 链接那一课）
  - `\\u002F` 是 **JSON** 转义，html.unescape 不动它，必须单独还原
只替换 `\\u002F` / `\\u002f` 这两个斜杠形态，不要整体 json.loads（payload
里混着非 JSON 片段）。
"""
from finder.detail import extract_downloads

KUNGAL_PAYLOAD = (
    '<html><head><title>千恋＊万花 游戏本体资源下载</title></head><body>'
    '<script>window.__NUXT__=[{"object":119,"url":120,"children":121},'
    '"link","https:\\u002F\\u002Fpan.baidu.com\\u002Fs\\u002F1Dau8DVO5_HcMjOD4nFA4Qg?pwd=t7cp",'
    '"https:\\u002F\\u002Fpan.quark.cn\\u002Fs\\u002F7c51265e86f2",'
    '"https:\\u002F\\u002Fpan.xunlei.com\\u002Fs\\u002FVOyhbhDXJvGeldVp6UCpq61aA1?pwd=s4uc"]'
    "</script></body></html>"
)


def test_escaped_slashes_in_inline_json_are_decoded():
    dl = extract_downloads(KUNGAL_PAYLOAD, "https://www.kungal.com/galgame/resource/46246")
    urls = [d.url for d in dl]
    assert urls, f"\\u002F 转义链接一条都没抽出来：{urls}"
    baidu = [u for u in urls if "pan.baidu.com" in u]
    assert baidu, urls
    assert baidu[0].endswith("?pwd=t7cp"), baidu[0]
    assert "\\u002F" not in baidu[0], f"转义没还原干净：{baidu[0]}"
    assert all(d.kind == "pan" for d in dl)


def test_escaped_slashes_do_not_break_normal_links():
    """普通（未转义）链接仍然正常，且不会重复。"""
    html = (
        '<a href="https://pan.baidu.com/s/normalcase?pwd=aaaa">x</a>'
        + KUNGAL_PAYLOAD
    )
    dl = extract_downloads(html, "https://www.kungal.com/galgame/resource/1")
    urls = [d.url for d in dl]
    assert "https://pan.baidu.com/s/normalcase?pwd=aaaa" in urls
    assert len(urls) == len(set(urls)), f"有重复链接：{urls}"


def test_magnet_with_escaped_slashes_still_parsed():
    """磁力链不涉及斜杠转义，不能被新逻辑破坏。"""
    html = (
        "<div>magnet:?xt=urn:btih:e018ad9bb1c7c46b86124f7ff535d1781006857b</div>"
    )
    dl = extract_downloads(html, "https://example.com/x")
    assert [d.kind for d in dl] == ["magnet"]
