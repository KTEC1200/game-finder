"""Store 必须跨线程可用（并发 pipeline 会从 worker 线程读写缓存）。

真实缺陷（2026-10-18 真站实测）：sqlite3 默认 check_same_thread=True，
主线程建的连接在 worker 线程里用会抛
  ProgrammingError: SQLite objects created in a thread can only be used in
  that same thread.
该异常被单站兜底吞成 .error，表现为「并发整批 0 成功、0.5s 结束」——
基准脚本里几乎无法定位。
"""
import threading

from finder.models import Download, GameDetail, HealthRecord
from finder.store import Store


def test_get_cached_works_from_another_thread(tmp_path):
    with Store(tmp_path / "c.db", ttl_hours=12) as st:
        st.put_cached("q", GameDetail(site_id="a", url="u", title="t",
                                      downloads=[Download(kind="pan", url="https://p/1")]))
        out: list = []
        err: list = []

        def read():
            try:
                out.append(st.get_cached("q", "a"))
            except BaseException as exc:  # noqa: BLE001
                err.append(exc)

        t = threading.Thread(target=read)
        t.start()
        t.join(timeout=10)

    assert not err, f"跨线程读失败：{err}"
    assert out and out[0] is not None
    assert out[0].downloads[0].url == "https://p/1"


def test_put_cached_works_from_another_thread(tmp_path):
    with Store(tmp_path / "c.db", ttl_hours=12) as st:
        err: list = []

        def write():
            try:
                st.put_cached("q", GameDetail(site_id="a", url="u", title="t"))
            except BaseException as exc:  # noqa: BLE001
                err.append(exc)

        t = threading.Thread(target=write)
        t.start()
        t.join(timeout=10)

        assert not err, f"跨线程写失败：{err}"
        assert st.get_cached("q", "a") is not None


def test_concurrent_writes_do_not_lose_rows(tmp_path):
    """多线程同时写不同站：一条都不能丢（sqlite 连接被并发写会出问题）。"""
    sites = [f"s{i}" for i in range(12)]
    with Store(tmp_path / "c.db", ttl_hours=12) as st:
        err: list = []

        def write(sid: str):
            try:
                st.put_cached("q", GameDetail(site_id=sid, url="u", title=sid))
            except BaseException as exc:  # noqa: BLE001
                err.append((sid, exc))

        threads = [threading.Thread(target=write, args=(s,)) for s in sites]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

        assert not err, f"并发写失败：{err}"
        got = [st.get_cached("q", s) for s in sites]
    assert all(g is not None for g in got), "有行被并发写丢掉了"


def test_health_works_from_another_thread(tmp_path):
    with Store(tmp_path / "c.db", ttl_hours=12) as st:
        st.record_health(HealthRecord(site_id="a", status="ok", latency_ms=1,
                                      checked_at="2026-10-18T00:00:00"))
        err: list = []
        out: list = []

        def read():
            try:
                out.append(st.health_latest())
            except BaseException as exc:  # noqa: BLE001
                err.append(exc)

        t = threading.Thread(target=read)
        t.start()
        t.join(timeout=10)

    assert not err, f"跨线程读健康历史失败：{err}"
    assert out[0]["a"].status == "ok"
