import time

from finder.models import Download, GameDetail, HealthRecord
from finder.store import Store


def test_put_and_get_roundtrip(tmp_path):
    db = tmp_path / "t.db"
    with Store(db, ttl_hours=12) as st:
        d = GameDetail(site_id="s", url="https://e.com/1", title="t",
                       downloads=[Download(kind="pan", url="https://pan.baidu.com/s/x")])
        st.put_cached("q", d)
        got = st.get_cached("q", "s")
    assert got is not None
    assert got.title == "t"
    assert len(got.downloads) == 1
    assert got.downloads[0].kind == "pan"


def test_cache_miss_returns_none(tmp_path):
    with Store(tmp_path / "t.db", ttl_hours=12) as st:
        assert st.get_cached("nope", "s") is None


def test_expired_cache_returns_none(tmp_path):
    db = tmp_path / "t.db"
    with Store(db, ttl_hours=0) as st:
        st.put_cached("q", GameDetail(site_id="s", url="u", title="t"))
        time.sleep(0.01)
        assert st.get_cached("q", "s") is None


def test_health_record_and_latest(tmp_path):
    with Store(tmp_path / "t.db", ttl_hours=12) as st:
        st.record_health(HealthRecord(site_id="a", status="ok", latency_ms=100,
                                      checked_at="2026-10-17T00:00:00"))
        st.record_health(HealthRecord(site_id="a", status="degraded", latency_ms=200,
                                      checked_at="2026-10-17T01:00:00"))
        latest = st.health_latest()
    assert latest["a"].status == "degraded"   # 取最新
    assert latest["a"].latency_ms == 200


def test_extra_dict_roundtrips(tmp_path):
    with Store(tmp_path / "t.db", ttl_hours=12) as st:
        d = GameDetail(
            site_id="s", url="u", title="t",
            extra={"truncated": True, "query_used": "abc", "match": "weak", "hits": 3},
        )
        st.put_cached("q", d)
        got = st.get_cached("q", "s")
    assert got is not None
    assert got.extra == {"truncated": True, "query_used": "abc", "match": "weak", "hits": 3}


def test_health_latest_one_record_per_site_even_on_ties(tmp_path):
    with Store(tmp_path / "t.db", ttl_hours=12) as st:
        st.record_health(HealthRecord(site_id="a", status="ok", latency_ms=10,
                                      checked_at="2026-10-17T00:00:00"))
        st.record_health(HealthRecord(site_id="a", status="degraded", latency_ms=20,
                                      checked_at="2026-10-17T00:00:00"))
        st.record_health(HealthRecord(site_id="b", status="ok", latency_ms=30,
                                      checked_at="2026-10-17T02:00:00"))
        latest = st.health_latest()
    assert set(latest) == {"a", "b"}
    assert latest["b"].latency_ms == 30
