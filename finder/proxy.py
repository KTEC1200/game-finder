"""本地代理可用性探测。

背景（实测，2026-10-21）：19 个目标站里 **18 个直连就能开**，只有
nyaa(sukebei.nyaa.si) 直连超时。而 config.yaml 里 `proxy.enabled: true` +
固定 `http://127.0.0.1:6234` 意味着「代理没开 → 全部站点失败」，这是最常见的
第一次运行失败原因。

所以默认行为改成「自动探测 + 回退直连」：
  * `proxy.enabled: false`          → 永不使用代理
  * `proxy.enabled: true` + `auto_detect: true`（默认）
        → 先探 server 的 TCP 端口；活着就用代理，死了就直连（并说明原因）
  * `proxy.enabled: true` + `auto_detect: false`
        → 无条件使用代理（旧行为，留给需要强制走代理的场景）

探测只做一次 TCP connect，不做 HTTP 请求：0.5s 超时，结果在进程内缓存，
因为每次 run() 都会为每个 worker 建 BrowserSession，逐个探测会平白多花时间。
"""
from __future__ import annotations

import logging
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

log = logging.getLogger("gamefinder.proxy")

DEFAULT_TIMEOUT = 0.5

# 探测结果缓存：key = (host, port, timeout)，value = 是否可用。
# 进程内缓存是刻意的 —— 用户中途打开代理的情况，重启程序即可重新探测。
_CACHE: dict[tuple[str, int, float], bool] = {}


@dataclass(frozen=True)
class ProxyDecision:
    """一次代理决策的结果，便于日志与测试断言。"""

    server: str | None
    reason: str

    @property
    def using_proxy(self) -> bool:
        return self.server is not None


def parse_server(server: str) -> tuple[str, int] | None:
    """`http://127.0.0.1:6234` -> ("127.0.0.1", 6234)；解析不出端口返回 None。"""
    if not server:
        return None
    raw = server if "//" in server else f"//{server}"
    parsed = urlparse(raw)
    host = parsed.hostname
    try:
        port = parsed.port
    except ValueError:  # 端口越界/非数字
        return None
    if not host or port is None:
        return None
    return host, port


def probe_alive(server: str, timeout: float = DEFAULT_TIMEOUT) -> bool:
    """TCP 连一下代理端口，连上就算活着。异常一律视为「不可用」。"""
    parsed = parse_server(server)
    if parsed is None:
        return False
    host, port = parsed
    key = (host, port, float(timeout))
    if key in _CACHE:
        return _CACHE[key]
    try:
        with socket.create_connection((host, port), timeout=timeout):
            alive = True
    except OSError:
        alive = False
    _CACHE[key] = alive
    return alive


def clear_cache() -> None:
    """测试与「重新探测」用。"""
    _CACHE.clear()


def resolve(config: dict, *, timeout: float = DEFAULT_TIMEOUT) -> ProxyDecision:
    """根据 config 的 proxy 段决定这次会话要不要用代理。

    永远不抛异常：探测失败只是退回直连，绝不能因此让整个搜索崩掉。
    """
    px = (config or {}).get("proxy") or {}
    server = str(px.get("server") or "").strip()

    if not px.get("enabled"):
        return ProxyDecision(None, "proxy disabled in config")
    if not server:
        return ProxyDecision(None, "proxy enabled but server is empty")

    # auto_detect 缺省为 True：绝大多数用户既没有本地代理，也不该为此失败。
    if not bool(px.get("auto_detect", True)):
        return ProxyDecision(server, f"proxy forced: {server}")

    if probe_alive(server, timeout):
        return ProxyDecision(server, f"proxy reachable: {server}")
    return ProxyDecision(
        None,
        f"proxy {server} unreachable, falling back to direct connection",
    )


def apply(config: dict, *, timeout: float = DEFAULT_TIMEOUT) -> ProxyDecision:
    """resolve 的带日志版本：给 BrowserSession 用。"""
    decision = resolve(config, timeout=timeout)
    if decision.server is None:
        log.warning("direct connection: %s", decision.reason)
    else:
        log.info("%s", decision.reason)
    return decision
