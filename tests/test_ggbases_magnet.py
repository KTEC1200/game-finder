"""ggbases 两个残留缺陷（2026-10-18 真站实测）。

缺陷 1：空结果的「没有结果」文案没被认出来。
  站点实际输出 `0\xa0個資源`（**不间断空格 U+00A0**），而标记表里写的是
  普通空格 `0 個資源`，永远匹配不上。结果是空结果页掉进
  `NO_RESULTS: pick_best returned None` —— 报错含糊，而且此时页脚的
  法务页还在候选池里。

缺陷 2：磁力链取不到。
  ggbases 的 `kinds: [磁力]`，但详情页 `view.so?id=N` 里没有任何
  `magnet:` 文本；磁力在独立的 `magnet.so?id=N` 页，而那一页的 hash 是
  JS 点「復製磁鏈」后 POST `/magnet.so?downid=<uuid>&json=1&id=N` 拿的：
      {"hash":"e018ad9bb1c7c46b86124f7ff535d1781006857b"}
  `page.request.post` 走独立 TLS 连接会被拒（ECONNRESET / 超时），
  必须用**页面内 fetch**（复用浏览器网络栈 + cookie）才稳定拿到。
"""
import re

from finder.detail import build_magnet_url, parse_magnet_ids
from finder.pipeline import looks_no_results

NBSP = "\u00a0"

EMPTY_PAGE = (
    "<html><head><title>GGBases-enderlilies(0)</title></head><body>"
    "<div>搜索 高級 GGBases &gt; " + f"0{NBSP}個資源" + "</div>"
    "<div>" + f"0{NBSP}個資源" + "</div>"
    "<div>Copyright © 2026 GGBases</div></body></html>"
)


def test_empty_result_marker_survives_nbsp():
    """站点用不间断空格排版，标记必须能认出来。"""
    marker = looks_no_results("GGBases-enderlilies(0)", EMPTY_PAGE)
    assert marker is not None, "空结果页没被认出来（NBSP 没归一化）"


def test_empty_result_marker_with_plain_space_still_works():
    """归一化不能反过来破坏普通空格的写法。"""
    html = "<html><body><div>0 個資源</div></body></html>"
    assert looks_no_results("x", html) is not None


def test_parse_magnet_ids_from_detail_html():
    """详情页里的 magnet.so?id=N 链接要能被抽出来。"""
    html = (
        '<a href="//ggbases.dlgal.com/magnet.so?id=131080" title="磁力鏈結">M</a>'
        '<a href="//ggbases.dlgal.com/down.so?id=131080">B</a>'
        '<a href="//ggbases.dlgal.com/magnet.so?id=91280">M</a>'
        '<a href="//ggbases.dlgal.com/magnet.so?id=131080">dup</a>'
    )
    assert parse_magnet_ids(html) == ["131080", "91280"]


def test_parse_magnet_ids_ignores_plain_magnet_links():
    """已经是 magnet: 的链接不算「需要解析的 id」。"""
    html = '<a href="magnet:?xt=urn:btih:abc123">m</a>'
    assert parse_magnet_ids(html) == []


def test_build_magnet_url():
    h = "e018ad9bb1c7c46b86124f7ff535d1781006857b"
    assert build_magnet_url(h) == f"magnet:?xt=urn:btih:{h}"


def test_build_magnet_url_rejects_junk():
    """hash 必须是 16-64 位十六进制，否则不是磁力。"""
    for bad in ["", "not-a-hash", "xyz", "e018ad9bb1c7c46b86124f7ff535d1781006857b;"]:
        assert build_magnet_url(bad) is None, bad


def test_magnet_id_regex_handles_absolute_and_relative():
    html = (
        '<a href="https://ggbases.dlgal.com/magnet.so?id=42">x</a>'
        '<a href="/magnet.so?id=43">y</a>'
        '<a href="magnet.so?id=44">z</a>'
    )
    assert parse_magnet_ids(html) == ["42", "43", "44"]


def test_magnet_id_comes_from_detail_url_when_html_has_none():
    """真站关键形状：详情页里没有 magnet.so?id= 的 href。

    磁力是 JS 按钮 `.dbutton[bt=3]`，点击时才拼 URL，所以 id 只能从
    详情页自己的 `?id=N` 拿。HTML 里一个链接都没有也必须能取到。
    """
    detail_url = "https://ggbases.dlgal.com/view.so?id=91280"
    assert parse_magnet_ids("<html><body>no links here</body></html>", detail_url) == ["91280"]


def test_magnet_id_prefers_detail_url_over_stray_links():
    """详情页 URL 的 id 排在最前（它才是当前条目）。"""
    detail_url = "https://ggbases.dlgal.com/view.so?id=91280"
    html = '<a href="/magnet.so?id=999">other</a>'
    assert parse_magnet_ids(html, detail_url) == ["91280", "999"]


# --------------------------------------------------------------------------
# 取 hash 的流程（假 page，不需要浏览器）
# --------------------------------------------------------------------------


class _FakePage:
    """模拟 ggbases 的两步取 hash：goto 磁力页 → 页面内 fetch POST。"""

    def __init__(self, downid="8061342e-dd8e-416b-98b0-5cca853eabe8",
                 hash_="e018ad9bb1c7c46b86124f7ff535d1781006857b",
                 goto_error=None, post_error=None):
        self.downid = downid
        self.hash_ = hash_
        self.goto_error = goto_error
        self.post_error = post_error
        self.visited = []
        self.url = ""

    def goto(self, url, timeout=None, wait_until=None):
        self.visited.append(url)
        if self.goto_error:
            raise self.goto_error
        self.url = url
        return type("R", (), {"status": 200})()

    def wait_for_load_state(self, *a, **k):
        return None

    def wait_for_timeout(self, ms):
        return None

    def content(self):
        if "magnet.so" in self.url:
            # 真站形状：downid 出现在内联 JS 里，**不带引号**
            # （probe 实测 re.findall(r"downid=([0-9a-fA-F\-]{36})", html) 直接命中）
            return (
                "<html><script>var u='magnet.so?downid=%s&id=1';"
                "</script><a class='dbutton'>復製磁鏈</a></html>" % self.downid
            )
        return "<html>detail</html>"

    def evaluate(self, script, arg):
        if self.post_error:
            raise self.post_error
        return '{"hash":"%s"}' % self.hash_


def test_fetch_magnets_happy_path():
    from finder.pipeline import _fetch_ggbases_magnets

    page = _FakePage()
    extra = {}
    dl = _fetch_ggbases_magnets(
        page, "<html>detail</html>",
        "https://ggbases.dlgal.com/view.so?id=91280", 30000, extra,
    )
    assert len(dl) == 1
    assert dl[0].kind == "magnet"
    assert dl[0].url == "magnet:?xt=urn:btih:e018ad9bb1c7c46b86124f7ff535d1781006857b"
    # 必须真的先打开磁力页（downid 在那页才生成）
    assert any("magnet.so?id=91280" in v for v in page.visited)
    assert extra["gg_magnet_errors"] if "gg_magnet_errors" in extra else True


def test_fetch_magnets_reports_goto_failure_without_crashing():
    from finder.pipeline import _fetch_ggbases_magnets

    page = _FakePage(goto_error=RuntimeError("boom"))
    extra = {}
    dl = _fetch_ggbases_magnets(
        page, "<html>d</html>",
        "https://ggbases.dlgal.com/view.so?id=1", 30000, extra,
    )
    assert dl == []
    assert extra["gg_magnet_errors"], "失败必须留证据，不能静默返回空"


def test_fetch_magnets_reports_post_failure():
    from finder.pipeline import _fetch_ggbases_magnets

    page = _FakePage(post_error=RuntimeError("fetch blocked"))
    extra = {}
    dl = _fetch_ggbases_magnets(
        page, "<html>d</html>",
        "https://ggbases.dlgal.com/view.so?id=1", 30000, extra,
    )
    assert dl == []
    assert any("post(" in e for e in extra["gg_magnet_errors"])


def test_fetch_magnets_skips_when_no_id():
    from finder.pipeline import _fetch_ggbases_magnets

    page = _FakePage()
    extra = {}
    dl = _fetch_ggbases_magnets(page, "<html>d</html>", "https://x/y", 30000, extra)
    assert dl == []
    assert page.visited == [], "没有 id 就不该发任何请求"
