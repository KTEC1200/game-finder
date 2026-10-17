"""SQLite 缓存与健康历史。纯标准库，无 ORM。"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Download, GameDetail, HealthRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS search_cache (
    query_norm TEXT NOT NULL,
    site_id    TEXT NOT NULL,
    payload    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (query_norm, site_id)
);
CREATE TABLE IF NOT EXISTS health_history (
    site_id    TEXT NOT NULL,
    status     TEXT NOT NULL,
    latency_ms INTEGER NOT NULL,
    reason     TEXT NOT NULL,
    checked_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_health_site ON health_history(site_id, checked_at);
"""

# dataclass 字段名集合：用于丢弃 payload 里未来版本才有的键，避免 GameDetail(**data) 炸掉
_DETAIL_KEYS = {f.name for f in fields(GameDetail)}
_DOWNLOAD_KEYS = {f.name for f in fields(Download)}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Store:
    """search_cache（带 TTL）+ health_history 的薄封装，可作上下文管理器。"""

    def __init__(self, db_path: Path | str, ttl_hours: int = 12):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl = timedelta(hours=ttl_hours)
        self._con = sqlite3.connect(str(self.path))
        self._con.executescript(SCHEMA)
        self._con.commit()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self._con.close()

    def close(self) -> None:
        self._con.close()

    def put_cached(self, query_norm: str, detail: GameDetail) -> None:
        self._con.execute(
            "INSERT OR REPLACE INTO search_cache VALUES (?,?,?,?)",
            (query_norm, detail.site_id,
             json.dumps(asdict(detail), ensure_ascii=False),
             _now().isoformat()),
        )
        self._con.commit()

    def get_cached(self, query_norm: str, site_id: str) -> GameDetail | None:
        row = self._con.execute(
            "SELECT payload, created_at FROM search_cache WHERE query_norm=? AND site_id=?",
            (query_norm, site_id),
        ).fetchone()
        if not row:
            return None
        payload, created = row
        try:
            created_dt = datetime.fromisoformat(created)
            data = json.loads(payload)
        except (ValueError, TypeError):
            return None
        if created_dt.tzinfo is None:
            # 兼容旧数据：无时区按 UTC 解释
            created_dt = created_dt.replace(tzinfo=timezone.utc)
        # 严格大于：ttl_hours=0 时任何正的时间流逝都算过期
        if _now() - created_dt > self.ttl:
            return None
        try:
            data["downloads"] = [
                Download(**{k: v for k, v in d.items() if k in _DOWNLOAD_KEYS})
                for d in data.get("downloads", [])
            ]
            return GameDetail(**{k: v for k, v in data.items() if k in _DETAIL_KEYS})
        except (TypeError, AttributeError):
            return None

    def record_health(self, rec: HealthRecord) -> None:
        self._con.execute(
            "INSERT INTO health_history VALUES (?,?,?,?,?)",
            (rec.site_id, rec.status, rec.latency_ms, rec.reason, rec.checked_at),
        )
        self._con.commit()

    def health_latest(self) -> dict[str, HealthRecord]:
        # ORDER BY checked_at DESC + rowid DESC 兜住同一时间戳：后插入者胜，
        # 再用 dict 覆盖保证每站只留一条（自连接 MAX 遇并列会出重复行）。
        rows = self._con.execute(
            """SELECT site_id, status, latency_ms, reason, checked_at
               FROM health_history
               ORDER BY checked_at DESC, rowid DESC"""
        ).fetchall()
        latest: dict[str, HealthRecord] = {}
        for site_id, status, latency_ms, reason, checked_at in rows:
            latest.setdefault(
                site_id,
                HealthRecord(site_id=site_id, status=status, latency_ms=latency_ms,
                             reason=reason, checked_at=checked_at),
            )
        return latest
