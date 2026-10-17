"""健康巡检状态机 —— 纯逻辑离线单测，不触网、不碰 data/finder.db。

状态判定的真实依据（Task 11 的 12 站冒烟实测）：
  - flysheep 对不存在的游戏返回 HTTP 200 + WordPress 的 "Nothing Found" 页，
    0 条结果链接。这是「站活着，只是没这个游戏」，不能报 degraded。
  - 0 条链接且**没有任何**无结果文案，才说明搜索可能坏了 → degraded。
"""
from finder.health import classify, probe_word_for, check_site
from finder.models import SearchSpec, Site


def _site(langs, sid="s", mode="url", selector=None):
    return Site(
        id=sid, name=sid, homepage="https://e.com/", kinds=[],
        langs=set(langs), url_searchable=(mode == "url"),
        search=SearchSpec(
            mode=mode,
            url_template="https://e.com/?s={q}" if mode == "url" else None,
            input_selector=selector,
        ),
    )


# ---------- classify: 任务书要求的 6 个状态 ----------

def test_classify_ok():
    assert classify(200, "<html>results</html>", 5) == "ok"


def test_classify_degraded_when_page_ok_but_zero_hits():
    assert classify(200, "<html>nothing</html>", 0) == "degraded"


def test_classify_cloudflare():
    assert classify(403, "<title>Attention Required! | Cloudflare</title>", 0) == "cloudflare_block"


def test_classify_unreachable():
    assert classify(None, "", 0) == "unreachable"


def test_classify_needs_login():
    body = "<html><a href='/login'>请先登录</a></html>"
    assert classify(200, body, 0) == "needs_login"


def test_probe_word_prefers_zh_then_en_then_ja():
    words = {"zh": "终焉之莉莉", "en": "enderlilies", "ja": "制服カノジョ"}
    assert probe_word_for(_site(["zh", "en"]), words) == "终焉之莉莉"
    assert probe_word_for(_site(["en"]), words) == "enderlilies"
    assert probe_word_for(_site(["ja"]), words) == "制服カノジョ"
    assert probe_word_for(_site(["en", "ja"]), words) == "enderlilies"


# ---------- classify: 站活着但没命中（Task 11 新增状态 ok_no_hits）----------

def test_classify_ok_no_hits_on_wordpress_nothing_found():
    """flysheep 实测：HTTP 200 + "Nothing Found" + 0 链接 → 站是活的。"""
    body = (
        "<html><head><title>与终焉之莉莉匹配搜索结果 - flysheep</title></head>"
        "<body><div class='nothing'>Nothing Found</div>"
        "<p>Sorry, but nothing matched your search terms.</p>"
        "<a href='/'>首页</a></body></html>"
    )
    assert classify(200, body, 0) == "ok_no_hits"


def test_classify_ok_no_hits_on_chinese_markers():
    assert classify(200, "<html><p>抱歉，没有找到相关内容</p></html>", 0) == "ok_no_hits"
    assert classify(200, "<html><p>未找到相关结果</p></html>", 0) == "ok_no_hits"


def test_classify_no_results_marker_in_script_is_not_trusted():
    """脚本里出现 no results 不能把 0 链接的正常页判成 ok_no_hits（应 degraded）。"""
    body = "<html><body><p>loading</p><script>var msg='no results';</script></body></html>"
    assert classify(200, body, 0) == "degraded"


def test_classify_cloudflare_script_url_does_not_false_positive():
    """页面引用了 cloudflare 的脚本/CDN，不等于被 Cloudflare 拦。"""
    body = (
        "<html><head><script src='https://static.cloudflareinsights.com/beacon.js'></script>"
        "</head><body><a href='/game/1.html'>x</a></body></html>"
    )
    assert classify(200, body, 3) == "ok"


def test_classify_cloudflare_footer_with_results_stays_ok():
    """正常站点页脚写 "Performance & security by Cloudflare"，有结果就该是 ok。"""
    body = (
        "<html><body><a href='/game/1.html'>x</a>"
        "<footer>Performance &amp; security by Cloudflare</footer></body></html>"
    )
    assert classify(200, body, 2) == "ok"


def test_classify_cloudflare_weak_marker_counts_when_zero_hits():
    """0 结果 + 只有 Cloudflare 字样、且没有无结果文案 → 按拦截处理。"""
    assert classify(200, "<html><body>Cloudflare</body></html>", 0) == "cloudflare_block"


def test_classify_nothing_found_beats_cloudflare_footer():
    """flysheep 类是 Cloudflare 托管站：页脚带 "Cloudflare" + "Nothing Found"。

    无结果文案是更具体的证据，必须判 ok_no_hits 而不是 cloudflare_block，
    否则「站活着但没这个游戏」会被误报成「被拦」——正是本任务要修的错误。
    """
    body = (
        "<html><body><h1>Nothing Found</h1>"
        "<p>Sorry, but nothing matched your search terms.</p></body>"
        "<footer>Performance &amp; security by Cloudflare</footer></html>"
    )
    assert classify(200, body, 0) == "ok_no_hits"


def test_classify_noise_links_plus_nothing_found_is_ok_no_hits():
    """实测 flysheep：'Nothing Found' 页仍能抽出 2 条页脚/导航链接（score=0.5）。

    有明确无结果文案 + 命中里没有一条详情形状 → 站活着但没这个游戏。
    """
    body = "<html><body><h1>Nothing Found</h1><a href='/x'>nav</a></body></html>"
    assert classify(200, body, 2, detail_hits=0) == "ok_no_hits"


def test_classify_real_hits_win_even_if_marker_present():
    """真有详情链接时，页面里残留的无结果文案不能把 ok 判成 ok_no_hits。"""
    assert classify(200, "<html><body>Nothing Found<a href='/game/12345'>x</a></body></html>",
                    3, detail_hits=3) == "ok"


def test_check_site_flysheep_style_noise_links_is_ok_no_hits():
    """check_site 端到端：无结果页 + 页脚导航链接（0.5 分）→ ok_no_hits，不是 ok。"""
    html = (
        "<html><body><h1>Nothing Found</h1>"
        "<p>Sorry, but nothing matched your search terms.</p>"
        "<a href='/about-us'>about</a><a href='/game-list'>list</a></body></html>"
    )
    rec = check_site(_FakePage(200, html), _site(["en"]), {"en": "enderlilies"}, timeout_ms=1000)
    assert rec.status == "ok_no_hits"


def test_classify_real_gamer520_page_with_challenge_script_is_ok():
    """真实 fixture（gamer520）：Cloudflare 托管站会往**正常**页注入
    /cdn-cgi/challenge-platform/scripts/jsd/main.js。有结果时必须仍是 ok。

    这条是实测反例，不是假想：validate 时它一度被判成 cloudflare_block。
    """
    from pathlib import Path

    from finder.search import parse_result_links
    from finder.sites import load_sites

    root = Path(__file__).resolve().parent.parent
    html = (root / "tests" / "fixtures" / "gamer520" / "search_ai.html").read_text(
        encoding="utf-8", errors="replace"
    )
    assert "challenge-platform" in html  # fixture 确实带 CF 注入脚本
    site = {s.id: s for s in load_sites(root / "sites.yaml")}["gamer520"]
    hits = parse_result_links(html, "https://www.gamer520.com/?s=AI", site)
    assert len(hits) > 0
    assert classify(200, html, len(hits)) == "ok"


def test_classify_hits_win_over_login_link_in_nav():
    """有结果链接就说明搜索可用，导航里的登录入口不能覆盖成 needs_login。"""
    body = "<html><a href='/login'>登录</a><a href='/game/9.html'>终焉之莉莉</a></html>"
    assert classify(200, body, 1) == "ok"


def test_classify_http_error_is_unreachable_even_with_body():
    assert classify(503, "<html>service unavailable</html>", 0) == "unreachable"


# ---------- check_site: 永不抛异常，失败降级为 HealthRecord ----------

class _Resp:
    def __init__(self, status):
        self.status = status


class _Box:
    def fill(self, *a, **kw):
        raise TimeoutError("Locator.fill: Timeout 10000ms exceeded")

    def press(self, *a, **kw):
        raise TimeoutError("Locator.press: Timeout")


class _Locator:
    @property
    def first(self):
        return _Box()


class _FakePage:
    """最小 page 替身：只实现 check_site 用到的 Playwright 接口。"""

    def __init__(self, status=200, html="<html></html>", goto_exc=None, fill_ok=True):
        self._status = status
        self._html = html
        self._goto_exc = goto_exc
        self._fill_ok = fill_ok
        self.url = "https://e.com/"

    def goto(self, url, **kw):
        if self._goto_exc:
            raise self._goto_exc
        self.url = url
        return _Resp(self._status)

    def wait_for_timeout(self, ms):
        pass

    def wait_for_load_state(self, *a, **kw):
        pass

    def content(self):
        return self._html

    def locator(self, sel):
        return _Locator() if not self._fill_ok else _OKLocator()


class _OKBox:
    def fill(self, *a, **kw):
        pass

    def press(self, *a, **kw):
        pass


class _OKLocator:
    @property
    def first(self):
        return _OKBox()


def test_check_site_url_mode_ok():
    html = "<html><a href='/game/12345'>终焉之莉莉</a></html>"
    rec = check_site(_FakePage(200, html), _site(["zh"]), {"zh": "终焉之莉莉"}, timeout_ms=1000)
    assert rec.status == "ok"
    assert rec.site_id == "s"
    assert rec.latency_ms >= 0
    assert rec.checked_at


def test_check_site_nav_failure_is_unreachable_and_never_raises():
    page = _FakePage(goto_exc=RuntimeError("net::ERR_NAME_NOT_RESOLVED"))
    rec = check_site(page, _site(["zh"]), {"zh": "终焉之莉莉"}, timeout_ms=1000)
    assert rec.status == "unreachable"
    assert "ERR_NAME_NOT_RESOLVED" in rec.reason


def test_check_site_form_fill_timeout_is_degraded_not_raised():
    """实测：部分 form 站的搜索框匹配不到 → fill 超时，必须降级而非让巡检崩掉。"""
    page = _FakePage(200, "<html>home</html>", fill_ok=False)
    rec = check_site(page, _site(["zh"], mode="form"), {"zh": "终焉之莉莉"}, timeout_ms=1000)
    assert rec.status == "degraded"
    assert "FORM_FAILED" in rec.reason


def test_check_site_form_mode_homepage_404_is_unreachable():
    """form 模式的首页 HTTP >= 400 → 站点不可达，不能因为「没抛异常」就算活着。"""
    page = _FakePage(404, "<html>not found</html>")
    rec = check_site(page, _site(["zh"], mode="form"), {"zh": "终焉之莉莉"}, timeout_ms=1000)
    assert rec.status == "unreachable"
    assert "404" in rec.reason


def test_check_site_no_hits_with_marker_is_ok_no_hits():
    html = "<html><body><p>Nothing Found</p></body></html>"
    rec = check_site(_FakePage(200, html), _site(["en"]), {"en": "enderlilies"}, timeout_ms=1000)
    assert rec.status == "ok_no_hits"
    assert "no_results=" in rec.reason      # 面板能看出为什么是 0 命中
    assert rec.reason.startswith("hits=")   # 链接数如实记录，不硬写成 0


def test_check_site_zero_hits_without_marker_is_degraded():
    """0 链接且页面没有任何无结果文案 → 搜索可能坏了。"""
    rec = check_site(_FakePage(200, "<html><body><p>hi</p></body></html>"),
                     _site(["zh"]), {"zh": "终焉之莉莉"}, timeout_ms=1000)
    assert rec.status == "degraded"
    assert rec.reason == "hits=0"
