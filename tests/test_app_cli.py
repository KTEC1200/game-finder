"""启动器 CLI：`--port` 覆盖 config，且端口被占时仍会往后找。

真机踩到的坑（2026-10-21）：打包版验证脚本用 `--port` 指定端口，但 `app.py`
没有这个参数 → `game-finder.exe: error: unrecognized arguments: --port 8795`，
打包验收脚本直接卡在「服务没起来」。测试只锁参数解析与端口选择，
**不真的起 uvicorn**（`uvicorn.run` 被 monkeypatch 掉）。
"""
from __future__ import annotations

import socket

import pytest

import app as app_mod


def test_pick_port_returns_preferred_when_free():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    assert app_mod._pick_port("127.0.0.1", free) == free


def test_pick_port_moves_on_when_occupied():
    held = socket.socket()
    try:
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        busy = held.getsockname()[1]
        assert app_mod._pick_port("127.0.0.1", busy) != busy
    finally:
        held.close()


def test_main_accepts_port_override(monkeypatch):
    """`--port 8795` 必须真的被采用（打包验收脚本依赖它）。"""
    seen: dict = {}

    def fake_run(app, host, port, **kw):
        seen["host"] = host
        seen["port"] = port

    monkeypatch.setattr(app_mod.uvicorn, "run", fake_run)
    monkeypatch.setattr(app_mod, "_preflight", lambda cfg: None)
    monkeypatch.setattr(app_mod, "_setup_logging", lambda root: None)
    app_mod.main(["--no-browser", "--port", "8795"])
    assert seen["port"] == 8795


def test_main_without_port_uses_config(monkeypatch):
    seen: dict = {}

    def fake_run(app, host, port, **kw):
        seen["port"] = port

    monkeypatch.setattr(app_mod.uvicorn, "run", fake_run)
    monkeypatch.setattr(app_mod, "_preflight", lambda cfg: None)
    monkeypatch.setattr(app_mod, "_setup_logging", lambda root: None)
    app_mod.main(["--no-browser"])
    import yaml

    from finder import paths

    cfg = yaml.safe_load(paths.config_path(paths.app_root()).read_text(encoding="utf-8"))
    assert seen["port"] == int(cfg["server"]["port"])


def test_check_mode_does_not_start_server(monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("--check 不该启动服务")

    monkeypatch.setattr(app_mod.uvicorn, "run", boom)
    monkeypatch.setattr(app_mod, "_setup_logging", lambda root: None)
    app_mod.main(["--check"])
    out = capsys.readouterr().out
    assert "app_root" in out or "frozen" in out


def test_no_browser_flag_skips_webbrowser(monkeypatch):
    """`--no-browser` 必须真的不开浏览器（探针脚本靠它避免弹窗）。"""
    opened: list[str] = []

    class FakeTimer:
        def __init__(self, delay, fn):
            self.delay = delay
            self.fn = fn

        def start(self):
            opened.append("started")

    monkeypatch.setattr(app_mod.threading, "Timer", FakeTimer)
    monkeypatch.setattr(app_mod.webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(app_mod.uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(app_mod, "_preflight", lambda cfg: None)
    monkeypatch.setattr(app_mod, "_setup_logging", lambda root: None)
    app_mod.main(["--no-browser"])
    assert opened == [], f"--no-browser 却启动了浏览器：{opened}"
