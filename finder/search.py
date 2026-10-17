"""站内搜索：url 模式（17 站）+ form 模式（5 站）。

关键实测（spec §2.1.4）：jidiyouxi 正文仅 160 字节但能出结果
→ 判成败必须数链接，不能看正文长度。

关键实测（Task 6 修正）：搜索结果页里混着大量导航/静态资源链接
（gamer520 的 search_ai.html 原始抽法出 39 条，其中 css/js/首页占大头，
而且会选中 /pcplay 这种分类页）。所以必须：
  1. NAV_RE 排除导航形状的路径；
  2. ASSET_RE 排除静态资源（扩展名维度）—— 比路径维度更可靠；
  3. pick_best 优先只在详情形状的链接里挑。

关键实测（Task 7 修正，真站冒烟发现）：
  4. **线上 jidiyouxi 的结果链接是相对路径**（`/topic/detail/959615543`），
     只收 `http` 开头的 href 会导致 hit=0。必须 urljoin 后再判同域。
  5. 客户端路由在数据没回来时会渲染 `/topic/detail/undefined` 占位链接，必须滤掉。
  6. 标题必须取 `<a title=…>` / `<a>` 内的文本；旧的「href 附近 300 字符窗口」
     在真实页面上取到的是导航菜单文本（gamer520 实测：把「金手指 3A巨作」
     当成了结果标题），导致 pick_best 选错文章。
"""
from __future__ import annotations

import re
from urllib.parse import quote, urljoin, urlparse

from .models import SearchHit, Site

NAV_RE = re.compile(
    r"/(login|register|signup|tag|tags|category|categor|page/\d+|about|contact|"
    r"privacy|terms|feed|rss|user|profile|search|wp-content|wp-admin|wp-json|"
    r"wp-includes|assets|static|list|lists|forums?|thread|donations?|archives?|"
    r"board|boards)(/|$|\?)", re.I
)
# 终端段导航（`/game`、`/games`、`/index.php` 这类列表入口）。
# 不能并进 NAV_RE：`game` 作为普通段会连 `/galgame/235041`、`/games/12345`
# 一起吞掉。这里只认「路径到此结束」的形状（详见 parse_result_links）。
TERMINAL_NAV_RE = re.compile(r"/(game|games|list|index\.php)\s*($|\?)", re.I)
ASSET_RE = re.compile(
    r"\.(css|js|png|jpe?g|gif|svg|webp|ico|woff2?|ttf|eot|map|json|xml|txt|pdf)"
    r"($|\?)", re.I
)
DETAILISH_RE = re.compile(
    r"(/\d{2,}|/game/|/detail|/post/|/topic/detail/|/subject/|/entry/|\.html$|/item/)",
    re.I,
)
# 客户端路由未拿到数据时的占位链接
JUNK_PATH_RE = re.compile(r"/(undefined|null|nan|NaN)(/|$|\?)")
ANCHOR_RE = re.compile(r'<a\b([^>]*?)\bhref=["\']([^"\']+)["\']([^>]*)>', re.I)
# <a title="..."> / <a><img alt="..."> 里的标题
TITLE_ATTR_RE = re.compile(
    r'(?:^|\s)(?:title|alt|aria-label)=["\']([^"\']{2,400})["\']', re.I
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


def _strip_fragment(url: str) -> str:
    return url.split("#", 1)[0]


def _anchor_title(attrs: str, body_html: str) -> str:
    """取链接标题：<a title=> / <a><img alt=> 优先，否则取 </a> 之前的可见文本。"""
    found = TITLE_ATTR_RE.findall(attrs + " " + body_html[:400])
    if found:
        return re.sub(r"\s+", " ", found[0]).strip()[:300]
    end = re.search(r"</a\s*>", body_html, re.I)
    inner = body_html[: end.end()] if end else body_html[:600]
    text = re.sub(r"<[^>]+>", " ", inner)
    return re.sub(r"\s+", " ", text).strip()[:300]


def parse_result_links(html: str, page_url: str, site: Site) -> list[SearchHit]:
    """从搜索结果页抽候选详情链接。同域 + 排除导航/静态资源 + 详情形状加分。

    - 相对路径先 urljoin 成绝对 URL（线上 jidiyouxi 就是相对路径）。
    - 同一 URL 出现多次（封面链接 + 标题链接）时保留信息量最大的标题。
    - 搜索页自身的排序/筛选变体（同 path、只差 query）不算结果。
    """
    titles: dict[str, str] = {}
    scores: dict[str, float] = {}
    order: list[str] = []
    page_bare = _strip_fragment(page_url)
    page_path = urlparse(page_url).path or "/"

    for m in ANCHOR_RE.finditer(html):
        raw = m.group(2).strip()
        if not raw or raw.startswith("#") or raw.startswith("?"):
            continue  # 纯锚点 / 站内排序参数，不是结果
        url = urljoin(page_url, raw)
        if not url.startswith("http"):
            continue
        if not _same_origin(url, page_url):
            continue
        path = urlparse(url).path or "/"
        if NAV_RE.search(path):
            continue
        # 终端列表面（`/game`、`/games`、`/list`、`/index.php`）——真实冒烟里
        # acggw 就落在 `/game` 上。只判「路径到此结束」，保住 `/games/12345`。
        if TERMINAL_NAV_RE.search(path):
            continue
        if ASSET_RE.search(url):
            continue
        if JUNK_PATH_RE.search(path):
            continue
        if path == "/" or path == page_path:
            continue  # 首页 / 搜索页自身的排序筛选变体，不是结果
        bare = _strip_fragment(url)
        if bare == page_bare:
            continue
        title = _anchor_title(m.group(0), html[m.end(): m.end() + 700])
        if bare not in titles:
            order.append(bare)
            titles[bare] = title
            scores[bare] = 1.0 if DETAILISH_RE.search(bare) else 0.5
        elif len(title) > len(titles[bare]):
            titles[bare] = title

    return [
        SearchHit(site_id=site.id, title=titles[u], url=u, score=scores[u])
        for u in order
    ]


def _norm(s: str) -> str:
    return re.sub(r"[\s\-_·・:：,，.。()（）\[\]【】]+", "", (s or "").lower())


def _query_pattern(q_raw: str) -> str | None:
    """查询词的正则：拉丁词按词边界匹配，CJK 按子串匹配。

    原因（Task 7 实测）：短查询 "AI" 用裸子串会命中 "Chained Beasts" 里的 "ai"，
    gamer520 用 "AI" 搜索时会选到完全不相关的文章。拉丁词必须按词边界。
    """
    q = (q_raw or "").strip()
    if not q:
        return None
    if re.search(r"[A-Za-z0-9]", q) and not re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", q):
        parts = [re.escape(p) for p in re.split(r"\s+", q) if p]
        if not parts:
            return None
        return r"(?<![a-z0-9])" + r"\s+".join(parts) + r"(?![a-z0-9])"
    return re.escape(q)


def pick_best(hits: list[SearchHit], query: str, min_score: float = 1.0) -> SearchHit | None:
    """标题与关键词匹配打分，取最高。

    只在详情形状的链接（score >= min_score）里挑；**没有详情候选就返回 None**。
    旧实现的 `or hits` 回退会在搜索页没有任何详情形状链接时，退到 0.5 分的
    导航链接里挑，于是把 `/game`、`/forums?index=3`、`/donations` 当成结果
    （2026-10-17 真站冒烟实测）。宁可报 NO_RESULTS，也不要给用户一个捐赠页卡片。

    打分（Task 7 修正后）：
      +12  查询词作为完整词/子串命中（拉丁词按词边界，CJK 按子串）
      +1   命中的位置越靠标题开头越好
      +命中率 逐字命中率，缓解标题里混了别的东西
      +0.1 详情形状链接（DETAILISH_RE）的小幅加权
    """
    if not hits:
        return None
    pool = [h for h in hits if h.score >= min_score]
    if not pool:
        return None          # 没有详情形状候选 -> 诚实地报「没找到」
    pattern = _query_pattern(query)
    rx = re.compile(pattern, re.I) if pattern else None
    qn = _norm(query)
    best = None
    best_score = -1.0
    for h in pool:
        raw_title = h.title or ""
        low = raw_title.lower()
        score = 0.0
        if rx is not None:
            m = rx.search(raw_title)
            if m:
                score += 12.0
                # 命中越靠前越好（标题开头就是游戏名）
                score += 1.0 * (1.0 - min(m.start(), 60) / 60.0)
        t = _norm(raw_title)
        if qn:
            score += sum(1 for ch in qn if ch in t) / len(qn)
        score += h.score * 0.1
        if score > best_score:
            best_score = score
            best = h
    return best
