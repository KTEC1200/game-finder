"""SQLite 搜索缓存。纯标准库，无 ORM。"""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Download, GameDetail

SCHEMA = """
CREATE TABLE IF NOT EXISTS search_cache (
    query_norm TEXT NOT NULL,
    site_id    TEXT NOT NULL,
    payload    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (query_norm, site_id)
);
"""

# dataclass 字段名集合：用于丢弃 payload 里未来版本才有的键，避免 GameDetail(**data) 炸掉
_DETAIL_KEYS = {f.name for f in fields(GameDetail)}
_DOWNLOAD_KEYS = {f.name for f in fields(Download)}


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Store:
    """search_cache（带 TTL）的薄封装，可作上下文管理器。

    线程安全：sqlite3 默认禁止跨线程使用连接（`check_same_thread=True`），
    而 pipeline 的并发路径会在 worker 线程里读写缓存 —— 实测直接抛
    `ProgrammingError: SQLite objects created in a thread can only be used in
    that same thread`，且该异常会被单站兜底逻辑吞成 error 字段，表现为
    「并发整批 0 成功、0.5s 就结束」，极难定位。

    所以这里 `check_same_thread=False` 并给每次操作加锁：本模块的访问模式是
    极短的 KV 读写，串行化开销可以忽略，换来跨线程可用。
    """

    def __init__(
        self,
        db_path: Path | str,
        ttl_hours: int = 12,
        fail_ttl_minutes: int = 30,
    ):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl = timedelta(hours=ttl_hours)
        # 失败结果用更短的 TTL：不缓存会让重复搜索几乎和首次一样慢（实测
        # 11 站里 6 个是失败站，占掉约 28s）；缓存 12h 又会让站点临时抽风时
        # 用户半天没法重试。30 分钟是折中，且前端可「强制刷新」绕开。
        self.fail_ttl = timedelta(minutes=fail_ttl_minutes)
        self._lock = threading.Lock()
        self._con = sqlite3.connect(str(self.path), check_same_thread=False)
        self._con.executescript(SCHEMA)
        self._con.commit()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self._con.close()

    def close(self) -> None:
        self._con.close()

    def put_cached(self, query_norm: str, detail: GameDetail) -> None:
        with self._lock:
            self._con.execute(
                "INSERT OR REPLACE INTO search_cache VALUES (?,?,?,?)",
                (query_norm, detail.site_id,
                 json.dumps(asdict(detail), ensure_ascii=False),
                 _now().isoformat()),
            )
            self._con.commit()

    def get_cached(self, query_norm: str, site_id: str) -> GameDetail | None:
        with self._lock:
            row = self._con.execute(
                "SELECT payload, created_at FROM search_cache "
                "WHERE query_norm=? AND site_id=?",
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
        # 失败结果按 fail_ttl 过期（更短），成功结果按 ttl。
        # 严格大于：ttl_hours=0 时任何正的时间流逝都算过期。
        ttl = self.fail_ttl if data.get("error") else self.ttl
        if _now() - created_dt > ttl:
            return None
        try:
            data["downloads"] = [
                Download(**{k: v for k, v in d.items() if k in _DOWNLOAD_KEYS})
                for d in data.get("downloads", [])
            ]
            return GameDetail(**{k: v for k, v in data.items() if k in _DETAIL_KEYS})
        except (TypeError, AttributeError):
            return None
