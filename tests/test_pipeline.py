"""pipeline 的离线单测 —— 只测纯函数与决策逻辑，不碰网络。

真站行为由 tools/smoke_live.py 负责（不进 pytest）；
这里锁住的是「哪一层失败该报哪个错误」这条判定链。
"""
from finder.pipeline import (
    looks_blocked,
    looks_no_results,
    match_strength,
    _find_gate_links,
    _visible_text,
)


def test_looks_blocked_detects_cloudflare_access_denied():
    html = "<html><body><h1>Access denied</h1></body></html>"
    assert looks_blocked("Access denied", html) == "access denied"


def test_looks_blocked_detects_just_a_moment():
    assert looks_blocked("Just a moment...", "") == "just a moment"
    assert looks_blocked("", "<div id='cf-error-details'>x</div>") == "cf-error-details"


def test_looks_blocked_ignores_normal_page():
    html = "<html><body><h1>终焉之莉莉</h1><p>正常内容</p></body></html>"
    assert looks_blocked("终焉之莉莉 - 某某站", html) is None


def test_looks_no_results_detects_wordpress_nothing_found():
    """flysheep 实测：无结果时页面是 WordPress 的 "Nothing Found"。"""
    html = (
        "<html><body><h1>与终焉之莉莉匹配搜索结果 - flysheep</h1>"
        "<div class='nothing'>Nothing Found</div>"
        "<p>Sorry, but nothing matched your search terms.</p>"
        "<a href='/'>首页</a></body></html>"
    )
    assert looks_no_results("与终焉之莉莉匹配搜索结果", html) == "nothing found"


def test_looks_no_results_detects_chinese_markers():
    html = "<html><body><p>抱歉，没有找到相关内容</p></body></html>"
    assert looks_no_results("", html) is not None


def test_looks_no_results_ignores_normal_page():
    html = "<html><body><h1>终焉之莉莉：骑士寂夜</h1><p>下载地址如下</p></body></html>"
    assert looks_no_results("终焉之莉莉：骑士寂夜", html) is None


def test_visible_text_drops_scripts_and_styles():
    html = (
        "<html><head><style>.a{color:red}</style>"
        "<script>var x='Nothing Found';</script></head>"
        "<body><p>真实正文</p></body></html>"
    )
    text = _visible_text(html)
    assert "真实正文" in text
    assert "Nothing Found" not in text          # script 里的文案不算
    assert "color:red" not in text


def test_looks_no_results_does_not_fire_on_script_only_marker():
    """脚本里出现 "no results" 不能把正常页面判成无结果。"""
    html = "<html><body><p>结果如下</p><script>var msg='no results';</script></body></html>"
    assert looks_no_results("结果", html) is None


def test_match_strength_strong_when_query_in_title():
    rate, strength = match_strength("终焉之莉莉", "终焉之莉莉：骑士寂夜 中文版")
    assert strength == "strong"
    assert rate == 1.0


def test_match_strength_reports_weak_for_translated_title():
    """同一游戏不同译名：只命中一个字 → weak，但不该被当成失败。"""
    rate, strength = match_strength("终焉之莉莉", "终结的百合花 骑士们的救赎")
    assert strength in {"weak", "none"}
    assert rate < 1.0


def test_find_gate_links_extracts_go_jump():
    """gamer520 详情页只有一个 /go?post_id= 跳板，链接不在详情页 HTML 里。"""
    html = '<a href="https://www.gamer520.com/go?post_id=18985">立即下载</a>'
    gates = _find_gate_links(html, "https://www.gamer520.com/18985.html")
    assert gates == ["https://www.gamer520.com/go?post_id=18985"]


def test_find_gate_links_handles_relative_and_none():
    html = '<a href="/go?post_id=1">x</a><a href="/wp-content/a.css">css</a>'
    gates = _find_gate_links(html, "https://www.gamer520.com/1.html")
    assert gates == ["https://www.gamer520.com/go?post_id=1"]
    assert _find_gate_links("", "https://e.com/") == []
