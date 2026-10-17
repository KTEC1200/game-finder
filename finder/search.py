"""站内搜索：url 模式（17 站）+ form 模式（5 站）。

关键实测（spec §2.1.4）：jidiyouxi 正文仅 160 字节但能出结果
→ 判成败必须数链接，不能看正文长度。

关键实测（Task 6 修正）：搜索结果页里混着大量导航/静态资源链接
（gamer520 的 search_ai.html 原始抽法出 39 条，其中 css/js/首页占大头，
而且会选中 /pcplay 这种分类页）。所以必须：
  1. NAV_RE 排除导航形状的路径；
  2. ASSET_RE 排除静态资源（扩展名维度）—— 比路径维度更可靠；
  3. pick_best 优先只在详情形状的链接里挑。
"""
from __future__ import annotations

import re
from urllib.parse import quote, urlparse

from .models import SearchHit, Site

NAV_RE = re.compile(
    r"/(login|register|signup|tag|tags|category|page/\d+|about|contact|"
    r"privacy|terms|feed|rss|user|profile|search|wp-content|wp-admin|wp-json|"
    r"wp-includes|assets|static)(/|$|\?)", re.I
)
ASSET_RE = re.compile(
    r"\.(css|js|png|jpe?g|gif|svg|webp|ico|woff2?|ttf|eot|map|json|xml|txt|pdf)"
    r"($|\?)", re.I
)
DETAILISH_RE = re.compile(
    r"(/\d{2,}|/game/|/detail|/post/|/topic/|/subject/|/entry/|\.html$|/item/)",
    re.I
)


def build_search_url(site: Site, query: str) -> str:
    """mode=url 时按模板构造搜索 URL。form 模式必须抛错，由调用方走浏览器表单流程。"""
    if site.search.mode != "url" or not site.search.url_template:
        raise ValueError(f"{site.id}: not url-mode or missing template")
    return site.search.url_template.format(q=quote(query, safe=""))


def clamp_query(site: Site, query: str) -> tuple[str, bool]:
    """按站点词长上限截断（ACG 港湾 max_query_len=10）。返回 (词, 是否截断)。"""
    limit = site.max_query_len
    if limit and len(query) > limit:
        return query[:limit], True
    return query, False


def _same_origin(url: str, page_url: str) -> bool:
    try:
        return urlparse(url).netloc == urlparse(page_url).netloc
    except Exception:  # noqa: BLE001
        return False


def parse_result_links(html: str, page_url: str, site: Site) -> list[SearchHit]:
    """从搜索结果页抽候选详情链接。同域 + 排除导航/静态资源 + 详情形状加分。"""
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', html, re.I)
    seen: set[str] = set()
    hits: list[SearchHit] = []

    for h in hrefs:
        if not h.startswith("http"):
            continue
        if not _same_origin(h, page_url):
            continue
        path = urlparse(h).path or ""
        if NAV_RE.search(path):
            continue
        if ASSET_RE.search(h):
            continue
        if h in seen:
            continue
        seen.add(h)
        # 标题：取 href 附近文本（粗粒度，够用于打分）
        idx = html.find(h)
        window = html[max(0, idx - 300): idx + 400] if idx >= 0 else ""
        text = re.sub(r"<[^>]+>", " ", window)
        text = re.sub(r"\s+", " ", text).strip()
        score = 1.0 if DETAILISH_RE.search(h) else 0.5
        hits.append(SearchHit(site_id=site.id, title=text[:200], url=h, score=score))

    return hits


def _norm(s: str) -> str:
    return re.sub(r"[\s\-_·・:：,，.。()（）\[\]【】]+", "", (s or "").lower())


def pick_best(hits: list[SearchHit], query: str, min_score: float = 1.0) -> SearchHit | None:
    """标题与关键词归一化匹配打分，取最高。

    只在详情形状的链接（score >= min_score）里挑；一条都没有时才退回全集，
    避免在只有分类页/首页可选时误选。
    """
    if not hits:
        return None
    pool = [h for h in hits if h.score >= min_score] or hits
    q = _norm(query)
    best = None
    best_score = -1.0
    for h in pool:
        t = _norm(h.title)
        score = 0.0
        if q and q in t:
            score += 10.0
        # 逐字命中率，缓解标题里混了别的东西
        if q:
            score += sum(1 for ch in q if ch in t) / len(q)
        score += h.score * 0.1
        if score > best_score:
            best_score = score
            best = h
    return best
