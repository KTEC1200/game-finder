"""数据模型。全部用 dataclass，无第三方依赖。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Lang = Literal["zh", "en", "ja"]
SearchMode = Literal["url", "form", "index"]
DownloadKind = Literal["direct", "pan", "magnet", "filehost", "unknown"]
AdapterStatus = Literal["verified", "untested", "broken"]


@dataclass
class SearchSpec:
    mode: SearchMode
    url_template: str | None = None          # mode="url" 时必需，含 {q}
    # mode="form" 时可选：搜索框不在首页，先打开这个页面（touchgal 实测）
    form_url: str | None = None
    input_selector: str | None = None        # mode="form"
    # 搜索框默认折叠、要先点这个元素才出现（gamebounty / touchgal 实测）
    open_selector: str | None = None
    submit_selector: str | None = None
    result_link_selector: str | None = None
    title_selector: str | None = None
    # mode="index"：站点的客户端搜索索引（sayafx 实测 /search.xml，760 条
    # <entry><title>/<url>）。本地匹配，不经过搜索页。
    index_url: str | None = None
    # 详情页里链接要二次跳转才出现时用（touchgal 实测）：
    # 先点 detail_open_selector 展开，再取匹配 detail_follow_pattern 的链接进去。
    detail_open_selector: str | None = None
    detail_follow_pattern: str | None = None
    # 详情页里指向 `.torrent` 种子的链接选择器（byrutgame 实测）：
    # 点它返回 application/x-bittorrent，磁力链由种子的 info hash 本地算出。
    torrent_selector: str | None = None


@dataclass
class Site:
    id: str
    name: str
    homepage: str
    kinds: list[str]
    langs: set[str]
    url_searchable: bool
    search: SearchSpec
    tags: set[str] = field(default_factory=set)
    needs_login: bool = False
    max_query_len: int | None = None
    adapter_status: AdapterStatus = "untested"
    # 仅当 headless+真实UA 仍被 Cloudflare 拦时置 True，该站改用 headful
    force_headful: bool = False


@dataclass
class SearchHit:
    site_id: str
    title: str
    url: str
    score: float = 0.0


@dataclass
class Download:
    kind: DownloadKind
    url: str
    label: str = ""
    code: str | None = None


@dataclass
class GameDetail:
    site_id: str
    url: str
    title: str
    cover_url: str | None = None
    intro: str | None = None
    version: str | None = None
    size: str | None = None
    updated_at: str | None = None
    downloads: list[Download] = field(default_factory=list)
    error: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class HealthRecord:
    site_id: str
    status: str                  # ok / degraded / unreachable / needs_proxy / ...
    latency_ms: int = 0
    reason: str = ""
    checked_at: str = ""         # ISO8601
