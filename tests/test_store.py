import sqlite3
import time

from finder.models import Download, GameDetail
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


def test_schema_no_longer_creates_health_history(tmp_path):
    """健康巡检已整体拆除：建表脚本里不能再有 health_history。"""
    db = tmp_path / "t.db"
    with Store(db, ttl_hours=12):
        pass
    con = sqlite3.connect(str(db))
    try:
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()
    assert "health_history" not in tables
    assert "search_cache" in tables
