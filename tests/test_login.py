"""「打开浏览器手动登录」——纯逻辑部分（不真的起浏览器）。

背景（实测 2026-10-22）：
  * 程序用**专用** profile，用户在**自己** Chrome 里登录过，程序一点也用不到
    （Chrome 136+ 禁止对默认 user-data-dir 开 DevTools）。
  * galgame.dev 的 `/search?term=...` 未登录会 302 到 `/login`，`/api/search`
    回 401 `{"status":{"code":"not-authorised"}}`。
  * 所以只能「用程序自己的 profile 开一个有头窗口，让用户登一次」。

这里锁三件容易静默坏掉的事：
  1. 登录成功判据不能只看 URL（首页未登录也能打开 → 会误报成功）；
  2. 用户中途关窗口是**正常路径**，不能抛异常、也不能当成失败日志刷屏；
  3. 同一时刻只能开一个登录窗口（profile 是独占资源，Chrome 会锁目录）。
"""
from __future__ import annotations

import pytest

from finder.login import (
    LOGGED_IN_MARKERS,
    LoginResult,
    LoginSession,
    is_login_path,
    login_state,
    login_url_for,
    looks_logged_in,
)
from finder.models import SearchSpec, Site


def _site(**kw) -> Site:
    base = dict(
        id="galgame.dev", name="真红的资源讨论组",
        homepage="https://galgame.dev/",
        kinds=["论坛网盘"], langs={"zh", "en", "ja"},
        url_searchable=True,
        search=SearchSpec(mode="url", url_template="https://galgame.dev/search?term={q}"),
    )
    base.update(kw)
    return Site(**base)


# --- 登录页判据 -------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://galgame.dev/login",
    "https://galgame.dev/login?next=/search",
    "https://e.com/signin",
    "https://e.com/sign-in",
    "https://e.com/account/login",
    "https://e.com/auth",
])
def test_is_login_path_true(url):
    assert is_login_path(url) is True


@pytest.mark.parametrize("url", [
    "https://galgame.dev/",
    "https://galgame.dev/search?term=x",
    "https://galgame.dev/topic/3844/abc",
    "",
    None,
])
def test_is_login_path_false(url):
    assert is_login_path(url) is False


# --- 登录成功判据 -----------------------------------------------------------

def test_logged_in_requires_both_url_and_marker():
    """只看 URL 会误报：galgame.dev 首页未登录也能打开。"""
    assert looks_logged_in("https://galgame.dev/", "", "") is False
    assert looks_logged_in("https://galgame.dev/", "首页", "退出") is True


def test_logged_in_false_while_still_on_login_page():
    """还在登录页上，就算正文有「登录」字样也不算成功。"""
    assert looks_logged_in("https://galgame.dev/login", "登录", "退出") is False


@pytest.mark.parametrize("marker", LOGGED_IN_MARKERS)
def test_every_marker_counts(marker):
    assert looks_logged_in("https://galgame.dev/", "", f"某某 {marker}") is True


def test_site_success_pattern_overrides_markers():
    assert looks_logged_in("https://e.com/", "", "welcome", r"welcome") is True
    assert looks_logged_in("https://e.com/", "", "退出", r"welcome") is False


def test_broken_success_pattern_falls_back_to_markers():
    """配置里的正则写错不能把功能卡死，退回通用判据。"""
    assert looks_logged_in("https://e.com/", "", "退出", r"([unclosed") is True


# --- 登录页地址 -------------------------------------------------------------

def test_login_url_none_when_site_needs_no_login():
    assert login_url_for(_site(needs_login=False)) is None


def test_login_url_from_config():
    assert login_url_for(_site(needs_login=True, login_url="https://galgame.dev/login")) \
        == "https://galgame.dev/login"


def test_login_url_falls_back_to_homepage_plus_login():
    assert login_url_for(_site(needs_login=True)) == "https://galgame.dev/login"


# --- LoginSession 行为 ------------------------------------------------------

class _FakePage:
    """url / title / text 由序列驱动，模拟「用户正在输密码 → 登完」。"""

    def __init__(self, frames, close_error=False):
        self._frames = list(frames)
        self._i = 0
        self._close_error = close_error
        self.visited = []
        self.waits = 0

    @property
    def _cur(self):
        return self._frames[min(self._i, len(self._frames) - 1)]

    @property
    def url(self):
        if self._close_error and self._i >= len(self._frames) - 1:
            raise RuntimeError("Target page, context or browser has been closed")
        return self._cur[0]

    def title(self):
        return self._cur[1]

    def evaluate(self, _script):
        return self._cur[2]

    def goto(self, url, **_kw):
        self.visited.append(url)

    def wait_for_timeout(self, ms):
        self.waits += 1
        self._i += 1


class _FakeSess:
    def __init__(self, page, on_close=None):
        self.page = page
        self.closed = False
        self._on_close = on_close

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True
        if self._on_close:
            self._on_close()


class _FakeFactory:
    def __init__(self, page, on_enter=None):
        self.page = page
        self.kwargs = {}
        self._on_enter = on_enter

    def __call__(self, *a, **kw):
        self.kwargs = kw
        return self

    def __enter__(self):
        return _FakeSess(self.page, self._on_enter)

    def __exit__(self, *exc):
        return None


def _session(frames, site=None, on_enter=None, on_close=None, timeout_s=5):
    page = _FakePage(frames, close_error=(on_close is None and False))
    factory = _FakeFactory(page, on_enter=on_enter)
    sess = LoginSession(
        {"browser": {"headless": True}}, __import__("pathlib").Path("."),
        site or _site(needs_login=True),
        timeout_s=timeout_s, poll_ms=0, session_factory=factory,
    )
    sess._page = page
    sess._factory = factory
    return sess, page, factory


def test_wait_for_login_succeeds_after_user_logs_in():
    sess, page, _ = _session([
        ("https://galgame.dev/login", "登录帐号", "请登录"),
        ("https://galgame.dev/", "首页", "退出"),
    ])
    with sess:
        result = sess.wait_for_login()
    assert isinstance(result, LoginResult)
    assert result.ok is True
    assert result.site_id == "galgame.dev"
    assert result.url == "https://galgame.dev/"


def test_wait_for_login_times_out_without_login():
    sess, page, _ = _session(
        [("https://galgame.dev/login", "登录帐号", "请登录")], timeout_s=0,
    )
    with sess:
        result = sess.wait_for_login()
    assert result.ok is False
    assert result.cancelled is False
    assert "仍未检测到登录" in result.message


def test_closing_the_window_is_cancelled_not_failed():
    """用户嫌麻烦直接关窗口 —— 这是正常路径，返回 cancelled。"""
    page = _FakePage([
        ("https://galgame.dev/login", "登录", "请登录"),
        ("https://galgame.dev/login", "登录", "请登录"),
    ], close_error=True)
    sess = LoginSession(
        {"browser": {}}, __import__("pathlib").Path("."), _site(needs_login=True),
        timeout_s=5, poll_ms=0, session_factory=_FakeFactory(page),
    )
    sess._page = page
    with sess:
        result = sess.wait_for_login()
    assert result.ok is False
    assert result.cancelled is True


def test_session_opens_headful_on_the_login_page():
    """登录必须看得见窗口；且一开就落在登录页，用户不用自己找入口。"""
    sess, page, factory = _session([("https://galgame.dev/", "首页", "退出")])
    with sess:
        pass
    assert factory.kwargs.get("headful_override") is True
    assert page.visited == ["https://galgame.dev/login"]


def test_second_session_is_refused_while_one_is_open():
    """profile 独占：两个窗口抢同一个 user-data-dir 必有一个崩。"""
    first, _p, _f = _session([("https://galgame.dev/login", "登录", "")], timeout_s=0)
    with first:
        second, _p2, _f2 = _session([("https://galgame.dev/login", "登录", "")])
        with pytest.raises(RuntimeError, match="已经有一个登录窗口"):
            second.__enter__()


def test_lock_is_released_even_if_opening_fails():
    class _Boom:
        def __call__(self, *a, **kw):
            return self

        def __enter__(self):
            raise OSError("chrome exploded")

        def __exit__(self, *exc):
            return None

    bad = LoginSession(
        {"browser": {}}, __import__("pathlib").Path("."), _site(needs_login=True),
        session_factory=_Boom(),
    )
    with pytest.raises(OSError):
        bad.__enter__()
    # 锁必须已释放，否则一次失败会让后续登录永久卡住
    ok, _p, _f = _session([("https://galgame.dev/", "", "退出")])
    with ok:
        assert ok.wait_for_login().ok is True


# --- profile 里的 Cookie 探测（只读） ---------------------------------------

def test_login_state_without_profile(tmp_path):
    st = login_state({"browser": {"profile_dir": "chrome-profile"}}, tmp_path, _site())
    assert st["logged_in"] is False
    assert st["site_id"] == "galgame.dev"


def test_login_state_reads_cookie_hosts(tmp_path):
    import sqlite3

    prof = tmp_path / "chrome-profile" / "Default" / "Network"
    prof.mkdir(parents=True)
    con = sqlite3.connect(str(prof / "Cookies"))
    con.execute(
        "CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT, "
        "path TEXT, expires_utc INTEGER)"
    )
    con.execute("INSERT INTO cookies VALUES ('.galgame.dev','express.sid','x','/',0)")
    con.commit()
    con.close()

    st = login_state({"browser": {"profile_dir": "chrome-profile"}}, tmp_path, _site())
    assert st["logged_in"] is True
    assert ".galgame.dev" in st["hosts"]


def test_login_state_ignores_other_sites_cookies(tmp_path):
    import sqlite3

    prof = tmp_path / "chrome-profile" / "Default" / "Network"
    prof.mkdir(parents=True)
    con = sqlite3.connect(str(prof / "Cookies"))
    con.execute(
        "CREATE TABLE cookies (host_key TEXT, name TEXT, value TEXT, "
        "path TEXT, expires_utc INTEGER)"
    )
    con.execute("INSERT INTO cookies VALUES ('.baidu.com','BDUSS','x','/',0)")
    con.commit()
    con.close()

    st = login_state({"browser": {"profile_dir": "chrome-profile"}}, tmp_path, _site())
    assert st["logged_in"] is False


def test_login_state_never_raises_on_broken_cookie_db(tmp_path):
    """Cookie 库可能被 Chrome 锁住或损坏 —— 探测失败只能当「没有」。"""
    prof = tmp_path / "chrome-profile" / "Default" / "Network"
    prof.mkdir(parents=True)
    (prof / "Cookies").write_bytes(b"not a sqlite file")
    st = login_state({"browser": {"profile_dir": "chrome-profile"}}, tmp_path, _site())
    assert st["logged_in"] is False
    assert "reason" in st


# --- 登录态必须能流到并发 worker -------------------------------------------
# 最容易静默坏掉的一条：登录写进「主 profile」，搜索却跑在
# chrome-profile-w0/1/2 上。两者对不上时，用户登完还是搜不到，
# 而且没有任何报错 —— 只有一条「登录成功」的假喜报。

def test_login_writes_to_the_profile_that_workers_are_seeded_from():
    from pathlib import Path

    from finder.browser import resolve_profile_dir
    from finder.pipeline import resolve_worker_primary

    root = Path(".")
    cfg = {"browser": {"profile_dir": "chrome-profile"}}
    assert resolve_worker_primary(cfg, root) == resolve_profile_dir(root, "chrome-profile")


def test_login_session_opens_on_that_same_profile(monkeypatch):
    """LoginSession 不许自己另挑一个 profile。"""
    from pathlib import Path

    import finder.browser as browser_mod

    seen = {}

    class _Spy:
        def __init__(self, config, project_root, **kw):
            seen["profile"] = kw.get("profile_override")
            seen["headful"] = kw.get("headful_override")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def new_page(self):
            return _FakePage([("https://galgame.dev/login", "登录", "")])

        def close(self):
            pass

    monkeypatch.setattr(browser_mod, "BrowserSession", _Spy)
    sess = LoginSession(
        {"browser": {"profile_dir": "chrome-profile"}}, Path("."),
        _site(needs_login=True), session_factory=_Spy,
    )
    with sess:
        pass
    assert seen["headful"] is True, "登录窗口必须有头，否则用户没法操作"
    assert seen["profile"] is None, (
        "不该传 profile_override —— 默认就用主 profile，worker 从它播种"
    )


def test_seed_entries_include_the_cookie_db():
    """播种清单里没有 Cookies 的话，worker 永远拿不到登录态。"""
    from finder.browser import SEED_ENTRIES

    assert "Default/Network/Cookies" in SEED_ENTRIES
    assert "Local State" in SEED_ENTRIES, "缺 Local State 会导致 Cookies 解不开"


# --- 超时/轮询间隔要能在 config.yaml 里调 --------------------------------
# 打包验收与真机探针必须用短超时（默认 600s 会把自动化卡死 10 分钟）。

def test_timeout_and_poll_come_from_config():
    sess = LoginSession(
        {"login": {"timeout_s": 12, "poll_ms": 250}}, __import__("pathlib").Path("."),
        _site(needs_login=True),
    )
    assert sess.timeout_s == 12
    assert sess.poll_ms == 250


def test_explicit_argument_beats_config():
    sess = LoginSession(
        {"login": {"timeout_s": 600}}, __import__("pathlib").Path("."),
        _site(needs_login=True), timeout_s=3,
    )
    assert sess.timeout_s == 3


def test_bad_config_values_fall_back_to_defaults():
    """配置写成字符串/None 不能把登录卡死或抛异常。"""
    for bad in ("abc", None, {}, [], 0):
        sess = LoginSession(
            {"login": {"timeout_s": bad, "poll_ms": bad}},
            __import__("pathlib").Path("."), _site(needs_login=True),
        )
        assert sess.timeout_s > 0
        assert sess.poll_ms > 0


# --- 关窗前必须确认 Cookie 真的落盘 ---------------------------------------
# 页面显示「退出」不等于磁盘上有 Cookie。用户登完立刻关窗口时，
# Chrome 可能还没刷盘 —— 这时重搜仍是登录墙，用户会以为功能坏了。

class _FakeCtx:
    def __init__(self, cookies):
        self._cookies = cookies

    def cookies(self):
        return self._cookies


def test_cookie_snapshot_reports_site_cookies():
    sess, page, _ = _session([("https://galgame.dev/", "", "退出")])
    sess._sess = type("S", (), {"context": _FakeCtx([
        {"domain": ".galgame.dev", "name": "express.sid"},
        {"domain": "galgame.dev", "name": "csrf"},
        {"domain": ".baidu.com", "name": "BDUSS"},
    ])})()
    snap = sess.cookie_snapshot()
    assert snap["ok"] is True
    assert snap["count"] == 2, "只数本站的 Cookie"
    assert set(snap["names"]) == {"express.sid", "csrf"}


def test_cookie_snapshot_before_open_is_not_ok():
    sess = LoginSession({"browser": {}}, __import__("pathlib").Path("."),
                        _site(needs_login=True))
    assert sess.cookie_snapshot()["ok"] is False


def test_cookie_snapshot_survives_broken_context():
    sess, _p, _f = _session([("https://galgame.dev/", "", "")])

    class _Boom:
        def cookies(self):
            raise RuntimeError("context closed")

    sess._sess = type("S", (), {"context": _Boom()})()
    snap = sess.cookie_snapshot()
    assert snap["ok"] is False
    assert "context closed" in snap["reason"]
