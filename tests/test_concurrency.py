"""并发搜索：每个 worker 用独立 profile 目录。

实测依据（2026-10-18，probe_concurrent_sep.py）：
  - 同一个 profile 目录并发启动 2 个 persistent context → **只有 1 个成功**，
    另一个 `TargetClosedError`（Chrome 会锁住 user-data-dir）
  - 独立目录并发 3 个 → **3/3 成功，总耗时 5.3s**
  - 从主 profile 播种登录态只要 **0.02s**（只拷 cookies 等小文件，
    不碰 320MB 的 Cache/GPUCache）

所以并发方案 = N 个 worker 槽位 + N 份独立 profile，启动前从主 profile 播种。
"""
from pathlib import Path

import pytest

from finder import pipeline
from finder.browser import seed_worker_profile
from finder.models import GameDetail, SearchSpec, Site


def _site(sid: str, headful: bool = False) -> Site:
    return Site(
        id=sid, name=sid, homepage=f"https://{sid}.test/",
        kinds=["网盘"], langs={"zh"}, url_searchable=True,
        force_headful=headful,
        search=SearchSpec(mode="url", url_template=f"https://{sid}.test/?s={{q}}"),
    )


def test_seed_worker_profile_copies_login_state(tmp_path):
    primary = tmp_path / "primary"
    (primary / "Default" / "Network").mkdir(parents=True)
    (primary / "Default" / "Network" / "Cookies").write_bytes(b"COOKIEDB")
    (primary / "Local State").write_text("{}", encoding="utf-8")
    (primary / "Default" / "Preferences").write_text("{}", encoding="utf-8")
    # 大缓存不该被复制
    (primary / "Default" / "Cache").mkdir()
    (primary / "Default" / "Cache" / "big.bin").write_bytes(b"x" * 10000)

    worker = tmp_path / "w0"
    seed_worker_profile(primary, worker)

    assert (worker / "Default" / "Network" / "Cookies").read_bytes() == b"COOKIEDB"
    assert (worker / "Local State").exists()
    assert (worker / "Default" / "Preferences").exists()
    assert not (worker / "Default" / "Cache").exists(), "Cache 必须跳过"


def test_seed_worker_profile_tolerates_missing_primary(tmp_path):
    """主 profile 还没建（首次运行）时不能炸，建个空目录继续。"""
    worker = tmp_path / "w0"
    seed_worker_profile(tmp_path / "nope", worker)
    assert worker.is_dir()


def test_seed_worker_profile_is_idempotent(tmp_path):
    primary = tmp_path / "primary"
    (primary / "Local State").parent.mkdir(parents=True, exist_ok=True)
    (primary / "Local State").write_text("{}", encoding="utf-8")
    worker = tmp_path / "w0"
    seed_worker_profile(primary, worker)
    (worker / "stale.txt").write_text("old", encoding="utf-8")
    seed_worker_profile(primary, worker)
    assert not (worker / "stale.txt").exists(), "重复播种应清掉旧目录"


def test_worker_profile_dir_is_inside_project(tmp_path):
    from finder.browser import worker_profile_dir
    p = worker_profile_dir(tmp_path, 0)
    assert p == tmp_path / "chrome-profile-w0"
    assert worker_profile_dir(tmp_path, 3) == tmp_path / "chrome-profile-w3"


def test_worker_profile_is_not_chrome_default():
    """worker 目录同样不能落进 Chrome 默认 user-data-dir。"""
    from finder.browser import is_chrome_default_profile, worker_profile_dir
    p = worker_profile_dir(Path(r"C:\some\project"), 0)
    assert not is_chrome_default_profile(p)


# ---- 并发调度 ----

class _RecordingSession:
    """记录每个线程用的是哪个 profile，并返回可用的假 page。"""

    used: list = []

    def __init__(self, config, root, headful_override=False,
                 profile_override=None):
        self._cfg = config
        self._root = root
        self._profile = profile_override

    @classmethod
    def for_site(cls, config, root, site, profile_override=None):
        return cls(config, root, headful_override=site.force_headful,
                   profile_override=profile_override)

    def __enter__(self):
        _RecordingSession.used.append(str(self._profile))
        return self

    def __exit__(self, *exc):
        return False

    def new_page(self):
        return object()


def test_run_uses_one_worker_per_group_when_workers_1(monkeypatch, tmp_path):
    """workers=1 时退回串行：只用主 profile，行为与旧版一致。"""
    monkeypatch.setattr("finder.browser.BrowserSession", _RecordingSession)
    _RecordingSession.used = []

    seen: list[str] = []

    def fake(page, site, query, timeout_ms=45000):
        seen.append(site.id)
        return GameDetail(site_id=site.id, url="u", title="t")

    monkeypatch.setattr(pipeline, "search_one", fake)
    sites = [_site("a"), _site("b"), _site("c")]

    pipeline.run({}, sites, "q", tmp_path, workers=1)

    assert seen == ["a", "b", "c"], "串行必须保持传入顺序"
    # 串行路径每站一个会话，全部走主 profile（profile_override=None）
    assert _RecordingSession.used == ["None"] * 3, (
        f"串行不该给 worker profile，实际 {_RecordingSession.used}"
    )


def test_run_parallel_preserves_input_order(monkeypatch, tmp_path):
    """并发跑完仍按传入顺序返回——UI 依赖这个顺序稳定。"""
    import time as _t

    monkeypatch.setattr("finder.browser.BrowserSession", _RecordingSession)
    _RecordingSession.used = []

    def fake(page, site, query, timeout_ms=45000):
        # 让靠前的站更慢，制造乱序完成
        _t.sleep(0.05 if site.id == "a" else 0.01)
        return GameDetail(site_id=site.id, url=f"https://{site.id}/", title=site.id)

    monkeypatch.setattr(pipeline, "search_one", fake)
    sites = [_site("a"), _site("b"), _site("c"), _site("d")]

    out = pipeline.run({}, sites, "q", tmp_path, workers=3)

    assert [d.site_id for d in out] == ["a", "b", "c", "d"]


def test_run_parallel_is_actually_concurrent(monkeypatch, tmp_path):
    """4 个站各睡 0.2s：串行要 0.8s，并发 4 应显著更快。"""
    import time as _t

    monkeypatch.setattr("finder.browser.BrowserSession", _RecordingSession)
    _RecordingSession.used = []

    def fake(page, site, query, timeout_ms=45000):
        _t.sleep(0.2)
        return GameDetail(site_id=site.id, url="u", title="t")

    monkeypatch.setattr(pipeline, "search_one", fake)
    sites = [_site(x) for x in ("a", "b", "c", "d")]

    t0 = _t.time()
    pipeline.run({}, sites, "q", tmp_path, workers=4)
    elapsed = _t.time() - t0
    assert elapsed < 0.5, f"并发没生效，耗时 {elapsed:.2f}s（串行约 0.8s）"


def test_run_parallel_survives_one_site_raising(monkeypatch, tmp_path):
    """单站抛异常不能拖垮整批——其他站的结果必须照常返回。"""
    monkeypatch.setattr("finder.browser.BrowserSession", _RecordingSession)
    _RecordingSession.used = []

    def fake(page, site, query, timeout_ms=45000):
        if site.id == "b":
            raise RuntimeError("boom")
        return GameDetail(site_id=site.id, url="u", title="ok")

    monkeypatch.setattr(pipeline, "search_one", fake)
    out = pipeline.run({}, [_site(x) for x in ("a", "b", "c")], "q",
                       tmp_path, workers=2)

    assert out[0].title == "ok"
    assert out[1].error and "boom" in out[1].error
    assert out[2].title == "ok"


def test_each_concurrent_worker_gets_a_distinct_profile(monkeypatch, tmp_path):
    """Chrome 锁 user-data-dir：并发时**任何时刻**两个线程都不能共用一个目录。

    真实缺陷（2026-10-18 真站实测）：按下标取模分配 profile，11 站 3 槽时
    有线程同时拿到同一个目录 → 3 站报 TargetClosedError，并发整批 0 成功。
    """
    import threading
    import time as _t

    active: dict[str, int] = {}
    lock = threading.Lock()
    overlap: list[str] = []

    class _ExclusiveSession(_RecordingSession):
        def __enter__(self):
            key = str(self._profile)
            with lock:
                active[key] = active.get(key, 0) + 1
                if active[key] > 1:
                    overlap.append(key)
            return self

        def __exit__(self, *exc):
            key = str(self._profile)
            with lock:
                active[key] -= 1
            return False

    monkeypatch.setattr("finder.browser.BrowserSession", _ExclusiveSession)

    def fake(page, site, query, timeout_ms=45000):
        _t.sleep(0.05)   # 加宽窗口，让共用目录一定被抓到
        return GameDetail(site_id=site.id, url="u", title="t")

    monkeypatch.setattr(pipeline, "search_one", fake)
    sites = [_site(x) for x in "abcdefghijkl"]   # 12 站
    pipeline.run({}, sites, "q", tmp_path, workers=3)

    assert not overlap, f"这些目录被并发共用了：{sorted(set(overlap))}"


def test_run_keeps_headful_sites_out_of_headless_workers(monkeypatch, tmp_path):
    """force_headful 站不能混进普通 worker 组，否则它拿不到 headful 会话。"""
    monkeypatch.setattr("finder.browser.BrowserSession", _RecordingSession)
    _RecordingSession.used = []

    def fake(page, site, query, timeout_ms=45000):
        return GameDetail(site_id=site.id, url="u", title="t")

    monkeypatch.setattr(pipeline, "search_one", fake)
    sites = [_site("a"), _site("hf", headful=True), _site("b")]
    out = pipeline.run({}, sites, "q", tmp_path, workers=2)

    assert [d.site_id for d in out] == ["a", "hf", "b"]


# ---- 显式 profile：让同机多个进程互不抢目录 ----

def test_run_with_explicit_profile_forces_serial(monkeypatch, tmp_path):
    """显式 profile 时必须串行——那个目录只允许一个 Chrome 进程。

    真实缺陷（2026-10-18 真站实测）：清扫脚本给每个子进程指定独立 profile，
    但 1 个站的 run() 会把 n_workers 夹到 1 后给 _safe 传 None，于是所有
    子进程都去开主 profile → 全部 TargetClosedError，表现为整批假失败。
    """
    monkeypatch.setattr("finder.browser.BrowserSession", _RecordingSession)
    _RecordingSession.used = []

    def fake(page, site, query, timeout_ms=45000):
        return GameDetail(site_id=site.id, url="u", title="t")

    monkeypatch.setattr(pipeline, "search_one", fake)
    sites = [_site(x) for x in ("a", "b", "c")]
    pinned = tmp_path / "chrome-profile-sweep0"

    pipeline.run({}, sites, "q", tmp_path, workers=3, profile=pinned)

    assert _RecordingSession.used == [str(pinned)] * 3, (
        f"每站都该用指定 profile，实际 {_RecordingSession.used}"
    )


def test_run_with_explicit_profile_seeds_nothing(monkeypatch, tmp_path):
    """指定 profile 时不该再去建 worker 槽位（否则白拷一份登录态）。"""
    monkeypatch.setattr("finder.browser.BrowserSession", _RecordingSession)
    _RecordingSession.used = []
    calls: list = []
    monkeypatch.setattr("finder.browser.seed_worker_profile",
                        lambda *a, **k: calls.append(a))

    def fake(page, site, query, timeout_ms=45000):
        return GameDetail(site_id=site.id, url="u", title="t")

    monkeypatch.setattr(pipeline, "search_one", fake)
    pipeline.run({}, [_site("a")], "q", tmp_path, workers=3,
                 profile=tmp_path / "pinned")

    assert calls == [], f"指定 profile 时不该播种 worker，实际 {calls}"

