"""浏览器层：三条实测硬约束的参数正确性（不需要真启动浏览器）。

约束来源（spec §2.1.1 / §2.1.2 / §2.1.4）：
  1. profile 必须是**非默认**路径，否则 Chrome 155 拒绝开 DevTools
  2. 代理必须**显式**传 http://127.0.0.1:6234，不能依赖 Chrome 继承系统代理
  3. UA 必须**显式**设真实 Chrome UA，headless 默认 UA 会被 Cloudflare 403

真启动的验证在 Task 4 Step 5 的手动冒烟里，不进 pytest。
"""
from pathlib import Path

import pytest
import yaml

from finder.browser import (
    ANTI_BOT_ARGS,
    DEFAULT_CHROME,
    BrowserSession,
    build_user_agent,
    chrome_default_profile_dir,
    is_chrome_default_profile,
    read_chrome_version,
    resolve_profile_dir,
)

PROJECT = Path(__file__).resolve().parent.parent
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def _cfg(**browser_overrides):
    cfg = {
        "browser": {
            "chrome_path": CHROME,
            "profile_dir": "chrome-profile",
            "headless": True,
            "user_agent": "",
        },
        "proxy": {"enabled": True, "server": "http://127.0.0.1:6234"},
    }
    cfg["browser"].update(browser_overrides)
    return cfg


# --------------------------------------------------------------------------
# 纯函数：UA / profile / 版本
# --------------------------------------------------------------------------


def test_build_user_agent_uses_real_version():
    ua = build_user_agent("155.0.8059.80")
    assert "Chrome/155.0.0.0" in ua
    assert "Windows NT 10.0; Win64; x64" in ua
    assert ua.startswith("Mozilla/5.0")
    # 绝不能出现 headless 标记
    assert "Headless" not in ua


def test_build_user_agent_exact_string():
    """spec 要求的就是这条真实 Chrome UA。"""
    assert build_user_agent("155.0.8059.80") == (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/155.0.0.0 Safari/537.36"
    )


def test_build_user_agent_handles_short_version():
    assert "Chrome/155.0.0.0" in build_user_agent("155")
    assert "Chrome/155.0.0.0" in build_user_agent("155.0")


def test_build_user_agent_never_emits_headless_for_any_version():
    for version in ("155.0.8059.80", "155", "140.0.7339.82"):
        assert "Headless" not in build_user_agent(version)


def test_resolve_profile_dir_is_not_chrome_default(tmp_path):
    p = resolve_profile_dir(tmp_path, "chrome-profile")
    assert p == tmp_path / "chrome-profile"
    # 关键：绝不能等于 Chrome 默认 user-data-dir
    default = Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data"
    assert p != default
    assert "Google/Chrome" not in str(p).replace("\\", "/")


def test_resolve_profile_dir_keeps_absolute_path():
    absolute = Path(r"C:\tmp\some-profile")
    assert resolve_profile_dir(Path(r"C:\project"), str(absolute)) == absolute


def test_resolve_profile_dir_joins_relative_against_project_root():
    p = resolve_profile_dir(PROJECT, "chrome-profile")
    assert p == PROJECT / "chrome-profile"
    assert p.is_absolute()


def test_resolve_profile_dir_rejects_chrome_default():
    with pytest.raises(ValueError):
        resolve_profile_dir(PROJECT, str(chrome_default_profile_dir()))


def test_resolve_profile_dir_rejects_subdir_of_chrome_default():
    with pytest.raises(ValueError):
        resolve_profile_dir(
            PROJECT, str(chrome_default_profile_dir() / "Profile 1")
        )


def test_is_chrome_default_profile_detection():
    assert is_chrome_default_profile(chrome_default_profile_dir()) is True
    assert is_chrome_default_profile(PROJECT / "chrome-profile") is False


def test_read_chrome_version_from_real_binary():
    if not Path(CHROME).exists():
        pytest.skip("chrome not installed")
    v = read_chrome_version(CHROME)
    assert v.count(".") >= 2
    assert v.split(".")[0].isdigit()


def test_read_chrome_version_falls_back_when_binary_missing(tmp_path):
    v = read_chrome_version(str(tmp_path / "no-such-chrome.exe"))
    assert v.count(".") >= 2
    assert v.split(".")[0].isdigit()


def test_config_proxy_is_the_measured_6234():
    """spec §2.1.2：显式 6234 是唯一 5/5 可达的配置。"""
    cfg = yaml.safe_load((PROJECT / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["proxy"]["enabled"] is True
    assert cfg["proxy"]["server"] == "http://127.0.0.1:6234"


def test_config_profile_dir_resolves_under_project_root():
    """config.yaml 的 browser.profile_dir 是相对路径 "chrome-profile"。"""
    cfg = yaml.safe_load((PROJECT / "config.yaml").read_text(encoding="utf-8"))
    configured = cfg["browser"]["profile_dir"]
    p = resolve_profile_dir(PROJECT, configured)
    assert p == PROJECT / configured
    assert not is_chrome_default_profile(p)


def test_anti_bot_args_present():
    assert "--disable-blink-features=AutomationControlled" in ANTI_BOT_ARGS


def test_default_chrome_path_is_the_measured_one():
    assert DEFAULT_CHROME == CHROME


# --------------------------------------------------------------------------
# BrowserSession 生命周期（替身，不启动真浏览器）
# --------------------------------------------------------------------------


class _FakeContext:
    def __init__(self, fail_close: bool = False):
        self.closed = 0
        self.pages = 0
        self._fail_close = fail_close

    def new_page(self):
        self.pages += 1
        return object()

    def close(self):
        self.closed += 1
        if self._fail_close:
            raise RuntimeError("close blew up")


class _FakePlaywright:
    def __init__(self):
        self.stopped = 0
        self.kwargs = None
        self.ctx = _FakeContext()
        self.chromium = self

    def launch_persistent_context(self, **kwargs):
        self.kwargs = kwargs
        return self.ctx

    def stop(self):
        self.stopped += 1

    def start(self):
        return self


@pytest.fixture
def fake_pw(monkeypatch):
    """把 sync_playwright / read_chrome_version 换成替身。"""
    import finder.browser as browser_mod

    fake = _FakePlaywright()
    monkeypatch.setattr(browser_mod, "sync_playwright", lambda: fake)
    # 固定版本，避免测试结果依赖本机 Chrome 是否升级
    monkeypatch.setattr(browser_mod, "read_chrome_version", lambda _p: "155.0.8059.80")
    return fake


def test_session_injects_profile_ua_proxy(fake_pw, tmp_path):
    sess = BrowserSession(_cfg(), tmp_path)
    sess.__enter__()
    kwargs = fake_pw.kwargs

    # 约束 1：profile 是非默认路径，且落在 project_root 下
    assert kwargs["user_data_dir"] == str(tmp_path / "chrome-profile")
    assert "Google" not in kwargs["user_data_dir"].split("\\")

    # 约束 2：代理显式传入
    assert kwargs["proxy"] == {"server": "http://127.0.0.1:6234"}

    # 约束 3：UA 显式且真实
    assert "Chrome/155.0.0.0" in kwargs["user_agent"]
    assert "Headless" not in kwargs["user_agent"]

    assert kwargs["headless"] is True
    assert kwargs["channel"] == "chrome"
    assert kwargs["executable_path"] == CHROME
    sess.close()


def test_session_from_real_config(fake_pw, tmp_path):
    """config.yaml + 本机路径 → 三条约束一次性验证（不真启动）。"""
    cfg = yaml.safe_load((PROJECT / "config.yaml").read_text(encoding="utf-8"))
    sess = BrowserSession(cfg, tmp_path)
    sess.__enter__()
    kwargs = fake_pw.kwargs

    assert kwargs["user_data_dir"] == str(tmp_path / "chrome-profile")
    assert kwargs["proxy"] == {"server": "http://127.0.0.1:6234"}
    assert "Chrome/155" in kwargs["user_agent"]
    assert "Headless" not in kwargs["user_agent"]
    assert kwargs["headless"] is True
    sess.close()


def test_session_honours_configured_user_agent(fake_pw, tmp_path):
    sess = BrowserSession(_cfg(user_agent="custom-agent/1.0"), tmp_path)
    sess.__enter__()
    assert fake_pw.kwargs["user_agent"] == "custom-agent/1.0"
    sess.close()


def test_session_headful_override(fake_pw, tmp_path):
    sess = BrowserSession(_cfg(), tmp_path, headful_override=True)
    sess.__enter__()
    assert fake_pw.kwargs["headless"] is False
    sess.close()


def test_session_for_site_uses_force_headful(fake_pw, tmp_path):
    from finder.models import SearchSpec, Site

    site = Site(
        id="x", name="X", homepage="https://example.com", kinds=[],
        langs={"zh"}, url_searchable=True, search=SearchSpec(mode="url", url_template="https://example.com/?q={q}"),
        force_headful=True,
    )
    sess = BrowserSession.for_site(_cfg(), tmp_path, site)
    sess.__enter__()
    assert fake_pw.kwargs["headless"] is False
    sess.close()


def test_session_without_proxy_when_disabled(fake_pw, tmp_path):
    cfg = _cfg()
    cfg["proxy"] = {"enabled": False, "server": "http://127.0.0.1:6234"}
    sess = BrowserSession(cfg, tmp_path)
    sess.__enter__()
    assert "proxy" not in fake_pw.kwargs
    sess.close()


def test_session_raises_when_chrome_missing(fake_pw, tmp_path):
    cfg = _cfg(chrome_path=str(tmp_path / "nope.exe"))
    with pytest.raises(FileNotFoundError):
        BrowserSession(cfg, tmp_path).__enter__()


def test_close_closes_context_and_stops_playwright(fake_pw, tmp_path):
    sess = BrowserSession(_cfg(), tmp_path)
    sess.__enter__()
    sess.close()
    assert fake_pw.ctx.closed == 1
    assert fake_pw.stopped == 1


def test_close_is_idempotent(fake_pw, tmp_path):
    sess = BrowserSession(_cfg(), tmp_path)
    sess.__enter__()
    sess.close()
    sess.close()
    assert fake_pw.ctx.closed == 1
    assert fake_pw.stopped == 1


def test_exit_closes_context_and_stops_playwright_even_if_close_raises(fake_pw, tmp_path):
    sess = BrowserSession(_cfg(), tmp_path)
    sess.__enter__()
    fake_pw.ctx._fail_close = True
    # close() 抛异常；__exit__ 必须仍然 stop 掉 playwright
    with pytest.raises(RuntimeError):
        sess.__exit__(None, None, None)
    assert fake_pw.ctx.closed == 1
    assert fake_pw.stopped == 1


def test_new_page_delegates_to_context(fake_pw, tmp_path):
    sess = BrowserSession(_cfg(), tmp_path)
    sess.__enter__()
    sess.new_page()
    sess.new_page()
    assert sess.context is fake_pw.ctx
    assert fake_pw.ctx.pages == 2
    sess.close()


def test_new_page_before_start_raises(fake_pw, tmp_path):
    sess = BrowserSession(_cfg(), tmp_path)
    with pytest.raises(RuntimeError):
        sess.new_page()
