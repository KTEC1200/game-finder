"""UI + 接口：「打开浏览器手动登录」的接线。

静态结构断言（与 test_ui_engines.py / test_ui_hint.py 同一范式）。
这里锁的是**真机上会静默坏掉**的接线：
  1. 按钮只出现在 needs_login 的站点卡片上（别的站冒出来就是骚扰）；
  2. 判断用 d.outcome，**不许在 JS 里解析 error 字串**（test_result_order 已锁死这条）；
  3. 登录成功后必须强制刷新搜索（缓存里还留着 NEEDS_LOGIN，不刷就还是旧结果）；
  4. /api/sites 必须带 needs_login + login_url，否则前端根本没数据可判。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

HTML = Path(__file__).resolve().parent.parent / "finder" / "web" / "static" / "index.html"


@pytest.fixture(scope="module")
def src() -> str:
    return HTML.read_text(encoding="utf-8")


# --- 前端 -------------------------------------------------------------------

def test_login_block_only_for_sites_that_need_login(src):
    m = re.search(r"function renderLogin\((.*?)\n\}", src, re.S)
    assert m, "找不到 renderLogin()"
    body = m.group(1)
    assert "site.needs_login" in body, "必须先判 needs_login，否则每个卡片都会长出登录框"
    assert re.search(r"if \(!site\.needs_login\) return;", body)


def test_login_block_keys_off_outcome_not_error_string(src):
    m = re.search(r"function renderLogin\((.*?)\n\}", src, re.S)
    body = m.group(1)
    assert "d.outcome" in body, "分档必须用后端给的 d.outcome"
    assert "error" not in body, "不许在 JS 里读 error 字串（test_result_order 锁死了这条）"


def test_login_block_skips_cards_that_already_have_links(src):
    m = re.search(r"function renderLogin\((.*?)\n\}", src, re.S)
    body = m.group(1)
    assert "'not_found'" in body and "'no_links'" in body
    assert "'direct'" not in body and "'pan'" not in body, "有链接的卡片不该劝登录"


def test_login_button_posts_site_id(src):
    m = re.search(r"function renderLogin\((.*?)\n\}", src, re.S)
    body = m.group(1)
    assert "fetch('/api/login'" in body
    assert "site_id: d.site_id" in body
    assert "method:'POST'" in body or "method: 'POST'" in body


def test_login_success_forces_a_refresh(src):
    """登录态刚写进 profile，缓存里的 NEEDS_LOGIN 已过时 —— 必须绕缓存重搜。"""
    m = re.search(r"function renderLogin\((.*?)\n\}", src, re.S)
    body = m.group(1)
    assert re.search(r"search\(true\)", body), "登录成功后必须 search(true) 强制刷新"


def test_login_button_is_disabled_while_waiting(src):
    """点一次要等用户在浏览器里操作，期间不能重复点（profile 独占）。"""
    m = re.search(r"function renderLogin\((.*?)\n\}", src, re.S)
    body = m.group(1)
    assert "btn.disabled = true" in body
    assert re.search(r"btn\.disabled\s*=\s*false", body), "失败后要恢复可点"


def test_login_text_is_constant_not_site_data(src):
    """提示文案是常量；站点返回的 message 只进 textContent（el()）。"""
    for name in ("LOGIN_HINT", "LOGIN_BTN", "LOGIN_WAIT", "LOGIN_DONE", "LOGIN_FAIL"):
        assert re.search(rf"const {name}\s*=", src), f"缺常量 {name}"
    assert ".innerHTML" not in re.search(
        r"function renderLogin\((.*?)\n\}", src, re.S).group(1), (
        "登录框里不许用 innerHTML（站点文案会进 DOM）"
    )


def test_sites_table_carries_login_flags(src):
    assert "needs_login:s.needs_login" in src.replace(" ", "") or \
           "needs_login: s.needs_login" in src
    assert "login_url:s.login_url" in src.replace(" ", "") or \
           "login_url: s.login_url" in src


# --- 接口 -------------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    from finder.web import server as srv
    monkeypatch.setattr(srv, "_run_pipeline", lambda *a, **k: [])
    return TestClient(srv.create_app())


def test_api_sites_exposes_login_url_only_for_login_sites(client):
    data = {s["id"]: s for s in client.get("/api/sites").json()}
    assert "login_url" in data["galgame.dev"]
    assert data["galgame.dev"]["login_url"] == "https://galgame.dev/login"
    assert data["galgame.dev"]["needs_login"] is True
    # 不需要登录的站不能给入口
    assert data["nyaa"]["login_url"] is None
    assert data["nyaa"]["needs_login"] is False


def test_api_login_rejects_unknown_site(client):
    r = client.post("/api/login", json={"site_id": "no-such-site"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "no-such-site" in body["message"]


def test_api_login_rejects_site_that_needs_no_login(client):
    r = client.post("/api/login", json={"site_id": "nyaa"})
    body = r.json()
    assert body["ok"] is False
    assert "不需要登录" in body["message"]


def test_api_login_returns_ok_when_session_succeeds(client, monkeypatch):
    from finder import login as login_mod

    class _Fake:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def wait_for_login(self):
            return login_mod.LoginResult(
                ok=True, site_id="galgame.dev", url="https://galgame.dev/",
                message="登录成功，登录态已保存", elapsed_s=3.2,
            )

    monkeypatch.setattr(login_mod, "LoginSession", _Fake)
    from finder.web import server as srv
    monkeypatch.setattr(srv, "LoginSession", _Fake)
    body = client.post("/api/login", json={"site_id": "galgame.dev"}).json()
    assert body["ok"] is True
    assert body["site_id"] == "galgame.dev"
    assert body["url"] == "https://galgame.dev/"


def test_api_login_reports_busy_window_instead_of_crashing(client, monkeypatch):
    """第二个窗口：profile 被占，必须回一句人话而不是 500。"""
    from finder.web import server as srv

    class _Busy:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            raise RuntimeError("已经有一个登录窗口开着。请先在那边登录完（或关掉它）再试。")

        def __exit__(self, *exc):
            return None

    monkeypatch.setattr(srv, "LoginSession", _Busy)
    r = client.post("/api/login", json={"site_id": "galgame.dev"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "已经有一个登录窗口" in body["message"]


def test_api_login_state_endpoint(client, monkeypatch):
    from finder.web import server as srv
    monkeypatch.setattr(
        srv, "login_state",
        lambda config, root, site: {"site_id": site.id, "logged_in": True,
                                    "hosts": [".galgame.dev"], "reason": "cookie found"},
    )
    body = client.get("/api/login/state", params={"site_id": "galgame.dev"}).json()
    assert body["logged_in"] is True
    assert body["site_id"] == "galgame.dev"


def test_api_login_state_unknown_site_is_false_not_500(client):
    body = client.get("/api/login/state", params={"site_id": "nope"}).json()
    assert body["logged_in"] is False
