"""ankergames 下载流程：generate-download-url → 中间页 → Turnstile → /link。

真站实测 2026-10-18（无登录、无需人工过盾）：
  POST /generate-download-url/<id>  ->  {"success":true,"download_url":".../download/<payload>/<hash>"}
  中间页 window.agTurnstile.tokenAsync() 静默出 token
  GET  <base>/link?cf-turnstile-response=<token>  ->  {"success":true,"link":"https://tunnel5..."}

这组测试锁住的是「别再用点按钮 + 等标签跳转」这个脆弱路径：
同一次会话里它时成时不成（广告脚本与 Turnstile 抢时序）。
"""
from __future__ import annotations

import json

from finder.models import Download, Site
from finder.pipeline import _fetch_ankergames_link

MID = "https://ankergames.net/download/eyJpZCI6MX0=/abc123"
REAL = "https://tunnel5.dlproxy.uk/download/tok123?sig=xyz"


def _site() -> Site:
    return Site(
        id="ankergames",
        name="ANKERGAMES",
        homepage="https://ankergames.net/",
        kinds=["直链"],
        langs={"en"},
        url_searchable=True,
        search=__import__("finder.models", fromlist=["SearchSpec"]).SearchSpec(
            mode="url",
            url_template="https://ankergames.net/search/{q}",
            download_flow="ankergames",
        ),
    )


class _FakePage:
    """按脚本依次返回 evaluate 结果；goto 记录被访问的 URL。"""

    def __init__(self, scripts: list[str], goto_err: str | None = None):
        self._scripts = list(scripts)
        self._goto_err = goto_err
        self.visited: list[str] = []
        self.url = "https://ankergames.net/game/ender-lilies"

    def evaluate(self, _js, *_args):
        if not self._scripts:
            raise AssertionError("evaluate called more times than scripted")
        return self._scripts.pop(0)

    def wait_for_load_state(self, *_a, **_k):
        return None

    def wait_for_timeout(self, *_a, **_k):
        return None


def _run(monkeypatch, scripts, goto_err=None):
    page = _FakePage(scripts, goto_err)
    monkeypatch.setattr(
        "finder.pipeline._goto",
        lambda p, url, _t: (p.visited.append(url), (200, goto_err))[1],
    )
    monkeypatch.setattr("finder.pipeline._settle", lambda *a, **k: None)
    extra: dict = {}
    return _fetch_ankergames_link(page, _site(), 30000, extra), extra, page


def test_happy_path_returns_the_real_direct_link(monkeypatch):
    gen = json.dumps({"success": True, "download_url": MID})
    link = json.dumps({"success": True, "link": REAL})
    dls, extra, page = _run(monkeypatch, ["1524", gen, link])
    assert dls == [Download(kind="direct", url=REAL, label="直链")]
    assert page.visited == [MID]
    assert extra["ank_download_id"] == "1524"
    assert "no-navigation" not in str(extra.get("ank_errors"))


def test_missing_download_id_is_reported_not_guessed(monkeypatch):
    dls, extra, _ = _run(monkeypatch, [""])
    assert dls == []
    assert extra["ank_errors"] == ["id: not-found"]


def test_generate_returning_no_url_is_reported(monkeypatch):
    dls, extra, _ = _run(monkeypatch, ["1524", json.dumps({"success": True})])
    assert dls == []
    assert extra["ank_errors"] == ["generate: no-download-url"]


def test_turnstile_failure_is_reported(monkeypatch):
    gen = json.dumps({"success": True, "download_url": MID})
    dls, extra, _ = _run(
        monkeypatch, ["1524", gen, json.dumps({"error": "empty-token"})]
    )
    assert dls == []
    assert extra["ank_errors"] == ["link: empty-token"]


def test_link_without_token_is_403_so_empty_result_is_honest(monkeypatch):
    """真站：不带 cf-turnstile-response 调 /link 回 403 且无 link 字段。"""
    gen = json.dumps({"success": True, "download_url": MID})
    dls, extra, _ = _run(monkeypatch, ["1524", gen, json.dumps({"error": "verification"})])
    assert dls == []
    assert "link" not in str(extra.get("ank_link_len"))


def test_goto_error_surfaces_as_mid_error(monkeypatch):
    gen = json.dumps({"success": True, "download_url": MID})
    dls, extra, _ = _run(monkeypatch, ["1524", gen], goto_err="TIMEOUT")
    assert dls == []
    assert extra["ank_errors"] == ["mid: TIMEOUT"]
