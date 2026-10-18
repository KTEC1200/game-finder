"""网络层失败要重试，站点的明确回答不要重试。

实测依据：
  - jidiyouxi 短时间连续搜索后直接 `ERR_CONNECTION_CLOSED`，同一个 URL
    隔几分钟再来就 200 —— 这是限流/抖动，不是「没有结果」
  - ggbases 偶发 `Page.goto: Timeout 45000ms exceeded`，重试即通过
  - HTTP 404/500 是站点的明确回答，重试只会浪费时间
"""
from __future__ import annotations

import pytest

from finder.pipeline import RETRYABLE_NAV, _goto


class _Resp:
    def __init__(self, status):
        self.status = status


class _Page:
    def __init__(self, results):
        self._results = list(results)
        self.calls = 0

    def goto(self, _url, **_kw):
        self.calls += 1
        item = self._results.pop(0)
        if isinstance(item, Exception):
            raise item
        return _Resp(item)

    def wait_for_timeout(self, _ms):
        return None


@pytest.mark.parametrize("marker", list(RETRYABLE_NAV))
def test_every_retryable_marker_is_covered(marker):
    assert marker in RETRYABLE_NAV


def test_connection_closed_is_retried_then_succeeds(monkeypatch):
    monkeypatch.setattr("finder.pipeline._settle", lambda *a, **k: None)
    page = _Page([Exception("Error: net::ERR_CONNECTION_CLOSED"), 200])
    status, err = _goto(page, "https://x/", 1000, retries=2)
    assert (status, err) == (200, None)
    assert page.calls == 2


def test_timeout_is_retried(monkeypatch):
    monkeypatch.setattr("finder.pipeline._settle", lambda *a, **k: None)
    page = _Page([Exception("TimeoutError: Page.goto: Timeout 45000ms exceeded"), 200])
    status, err = _goto(page, "https://x/", 1000, retries=2)
    assert (status, err) == (200, None)


def test_retries_are_bounded(monkeypatch):
    monkeypatch.setattr("finder.pipeline._settle", lambda *a, **k: None)
    page = _Page([Exception("net::ERR_CONNECTION_CLOSED")] * 5)
    status, err = _goto(page, "https://x/", 1000, retries=2)
    assert status is None
    assert "ERR_CONNECTION_CLOSED" in err
    assert page.calls == 3          # 1 次原始 + 2 次重试


def test_non_network_errors_are_not_retried(monkeypatch):
    monkeypatch.setattr("finder.pipeline._settle", lambda *a, **k: None)
    page = _Page([Exception("Error: net::ERR_NAME_NOT_RESOLVED")] * 3)
    status, err = _goto(page, "https://x/", 1000, retries=2)
    assert status is None and "ERR_NAME_NOT_RESOLVED" in err
    assert page.calls == 1


def test_default_retries_zero_keeps_old_behavior(monkeypatch):
    monkeypatch.setattr("finder.pipeline._settle", lambda *a, **k: None)
    page = _Page([Exception("net::ERR_CONNECTION_CLOSED")] * 3)
    status, _ = _goto(page, "https://x/", 1000)
    assert status is None
    assert page.calls == 1
