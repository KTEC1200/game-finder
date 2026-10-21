"""代理自动探测：不开代理也要能跑（实测 18/19 站直连可用）。

契约：
  * enabled=false            → 永不代理
  * enabled=true + auto_detect 缺省/true → 探活，连不上就直连
  * enabled=true + auto_detect=false     → 无条件代理（旧行为）
  * 探测永远不抛异常：网络/端口问题只能降级，不能让搜索崩掉
"""
from __future__ import annotations

import socket

import pytest

from finder import proxy


@pytest.fixture(autouse=True)
def _clear():
    proxy.clear_cache()
    yield
    proxy.clear_cache()


def _cfg(**px):
    base = {"enabled": True, "server": "http://127.0.0.1:6234"}
    base.update(px)
    return {"proxy": base}


# --------------------------------------------------------------------------
# parse_server
# --------------------------------------------------------------------------


def test_parse_server_extracts_host_and_port():
    assert proxy.parse_server("http://127.0.0.1:6234") == ("127.0.0.1", 6234)


def test_parse_server_accepts_scheme_less():
    assert proxy.parse_server("127.0.0.1:6234") == ("127.0.0.1", 6234)


def test_parse_server_returns_none_without_port():
    assert proxy.parse_server("http://127.0.0.1") is None


def test_parse_server_returns_none_for_empty_or_garbage():
    assert proxy.parse_server("") is None
    assert proxy.parse_server("http://:not-a-port") is None


# --------------------------------------------------------------------------
# probe_alive：用真 socket，不 mock —— 这个函数的价值就在于真的连得上
# --------------------------------------------------------------------------


def test_probe_alive_true_for_a_listening_socket():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert proxy.probe_alive(f"http://127.0.0.1:{port}", timeout=1.0) is True
    finally:
        srv.close()


def test_probe_alive_false_for_closed_port():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.close()  # 关掉：这个端口现在没人听
    assert proxy.probe_alive(f"http://127.0.0.1:{port}", timeout=0.5) is False


def test_probe_alive_is_cached(monkeypatch):
    calls = []

    def fake_create_connection(addr, timeout=None):
        calls.append(addr)
        raise OSError("nope")

    monkeypatch.setattr(proxy.socket, "create_connection", fake_create_connection)
    assert proxy.probe_alive("http://127.0.0.1:6234") is False
    assert proxy.probe_alive("http://127.0.0.1:6234") is False
    assert len(calls) == 1, "同一 (host, port) 只该探一次"


# --------------------------------------------------------------------------
# resolve：三种模式
# --------------------------------------------------------------------------


def test_disabled_never_proxies_even_if_port_is_alive():
    d = proxy.resolve(_cfg(enabled=False))
    assert d.using_proxy is False
    assert d.server is None
    assert "disabled" in d.reason


def test_enabled_with_auto_detect_falls_back_when_dead(monkeypatch):
    monkeypatch.setattr(proxy, "probe_alive", lambda *a, **k: False)
    d = proxy.resolve(_cfg(auto_detect=True))
    assert d.server is None
    assert "unreachable" in d.reason
    assert "direct" in d.reason


def test_enabled_with_auto_detect_uses_proxy_when_alive(monkeypatch):
    monkeypatch.setattr(proxy, "probe_alive", lambda *a, **k: True)
    d = proxy.resolve(_cfg(auto_detect=True))
    assert d.server == "http://127.0.0.1:6234"


def test_auto_detect_defaults_to_true(monkeypatch):
    """配置里没写 auto_detect 时也必须是「探活」而不是「无条件代理」。"""
    monkeypatch.setattr(proxy, "probe_alive", lambda *a, **k: False)
    d = proxy.resolve({"proxy": {"enabled": True,
                                 "server": "http://127.0.0.1:6234"}})
    assert d.server is None


def test_auto_detect_off_forces_proxy_even_when_dead(monkeypatch):
    monkeypatch.setattr(proxy, "probe_alive", lambda *a, **k: False)
    d = proxy.resolve(_cfg(auto_detect=False))
    assert d.server == "http://127.0.0.1:6234"
    assert "forced" in d.reason


def test_enabled_without_server_falls_back():
    d = proxy.resolve({"proxy": {"enabled": True, "server": ""}})
    assert d.server is None


def test_empty_config_means_direct():
    assert proxy.resolve({}).server is None
    assert proxy.resolve(None).server is None


def test_resolve_never_raises_on_garbage_server(monkeypatch):
    """端口越界这类解析错误不能把搜索搞崩，只能降级直连。"""
    d = proxy.resolve({"proxy": {"enabled": True,
                                 "server": "http://127.0.0.1:99999"}})
    assert d.server is None


def test_real_config_has_auto_detect_on():
    """config.yaml 必须保留手动开关，且默认走自动探测。"""
    import yaml

    from tests.test_browser import PROJECT

    cfg = yaml.safe_load((PROJECT / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["proxy"]["enabled"] is True
    assert cfg["proxy"]["server"] == "http://127.0.0.1:6234"
    assert cfg["proxy"]["auto_detect"] is True
