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
from html.parser import HTMLParser
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
TERMINAL_NAV_RE = re.compile(r"/(game|games|list|index\.php)/?($|\?)", re.I)
ASSET_RE = re.compile(
    r"\.(css|js|png|jpe?g|gif|svg|webp|ico|woff2?|ttf|eot|map|json|xml|txt|pdf)"
    r"($|\?)", re.I
)
DETAILISH_RE = re.compile(
    r"(/\d{2,}|/game/|/detail|/post/|/topic/detail/|/subject/|/entry/|\.html$|/item/)",
    re.I,
)
# 纯 slug 型详情页（实测 2026-10-18，两条都曾被判成 0.5 分而选不中）：
#   gamebounty  /ender-lilies-quietus-of-the-knights-free-pc-download
#   touchgal    /6a4e9cad   （8 位十六进制 id，无任何「详情」词）
# 判据刻意收窄，避免把导航页也算进来：
#   - 路径以 -download / -free-download 结尾（gamebounty 全站文章形状）
#   - 或**整条路径**就是一个 8-40 位十六进制/字母数字 id（touchgal 形状）
SLUG_DETAIL_RE = re.compile(
    r"(?:-download|/download(?:/|$))$"
    r"|^/[0-9a-f]{8}(?:[0-9a-f]{0,32})/?$",
    re.I,
)
# 客户端路由未拿到数据时的占位链接
JUNK_PATH_RE = re.compile(r"/(undefined|null|nan|NaN)(/|$|\?)")
# ---- 站点外壳剥离 ----------------------------------------------------------
# 实测 gamer520 搜索页 12 个候选里 10 个来自站点菜单：
# 其中 `/122908.html`（Switch 固件整合包）与 `/61541.html` 还是详情页形状，
# shape 会给 1.0，把真结果 `/18974.html`（终结的百合花）挤下去 →
# 整站返回错游戏的网盘链接。剥掉外壳后正确页成为唯一 1.0。
#
# 必须是「平衡扫描」而不是正则：`<div[^>]*menu.*?</div>` 这种写法会在
# 第一个 </div> 就截断（嵌套错的），而子串匹配 `header` 会把 acggw 的
# `.container-header` 整页吞掉（实测 17 条结果 → 0 条）。
# 所以：维护标签栈、按空白分隔的 class token 精确匹配、且绝不删结构容器。
CHROME_TAGS = {"nav", "header", "footer", "aside"}
# WordPress 把文章标题放在 <header class="entry-header"> 里 ——
# 在文章/正文容器内部的 header/footer/aside 不是站点外壳，不能删。
NESTED_OK_TAGS = {"article", "main", "section"}
CHROME_EXACT = {
    "menu", "navbar", "sidebar", "breadcrumb", "widget", "nav",
    "site-header", "site-footer", "site-nav", "main-nav", "top-nav",
    "mainmenu", "main-menu", "sub-menu", "submenu", "mobile-nav",
    "header-nav", "footer-nav", "menu-nav", "menu-item", "menu-user-box",
}
# 前缀必须窄：`nav-` 会命中 `<body class="...navbar-system">`，整页被删。
CHROME_PREFIX = (
    "menu-item", "menu-nav", "navbar-", "breadcrumb-",
    "sidebar-", "widget-", "site-header", "site-footer",
    "main-nav", "top-nav", "mobile-nav", "header-nav", "footer-nav",
)
_VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}
# 删掉任何一个都会毁掉页面或其正文，永远保留。
_NEVER_STRIP = {"html", "body", "main", "article", "section"}


def _chrome_class(value: str) -> bool:
    for tok in re.split(r"\s+", (value or "").strip()):
        if not tok:
            continue
        low = tok.lower()
        if low in CHROME_EXACT or any(low.startswith(p) for p in CHROME_PREFIX):
            return True
    return False


class _ChromeScanner(HTMLParser):
    """扫一遍标签栈，记录所有外壳区域的字符区间。"""

    def __init__(self, html: str):
        super().__init__(convert_charrefs=False)
        self.html = html
        self._line_starts = [0]
        for m in re.finditer(r"\n", html):
            self._line_starts.append(m.end())
        self._stack: list[tuple[str, bool, int]] = []
        self.spans: list[tuple[int, int]] = []

    def _offset(self) -> int:
        line, col = self.getpos()
        return self._line_starts[line - 1] + col

    def _inside_content(self) -> bool:
        return any(t in NESTED_OK_TAGS for t, _, _ in self._stack)

    def handle_starttag(self, tag, attrs):
        if tag in _VOID_TAGS:
            return
        chrome = False
        if tag in CHROME_TAGS:
            chrome = tag == "nav" or not self._inside_content()
        if not chrome:
            ad = dict(attrs)
            chrome = _chrome_class(ad.get("class", "")) or _chrome_class(ad.get("id", ""))
        if tag in _NEVER_STRIP:
            chrome = False
        self._stack.append((tag, chrome, self._offset()))

    def handle_endtag(self, tag):
        if tag in _VOID_TAGS:
            return
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] != tag:
                continue
            end = self._offset()
            close = self.html.find(">", end)
            stop = close + 1 if close != -1 else end
            for _, chrome, start in self._stack[i:]:
                if chrome:
                    self.spans.append((start, stop))
            del self._stack[i:]
            return

    def flush(self):
        for _, chrome, start in self._stack:
            if chrome:
                self.spans.append((start, len(self.html)))


def strip_chrome(html: str) -> str:
    """剥掉导航/页头页脚/侧栏这些绝不可能是搜索结果的区域。

    只做结构裁剪，链接判定仍走同一套 NAV_RE / 形状打分。
    任何异常都退回原文：宁可留着壳，也不能把结果页切没了。
    """
    try:
        sc = _ChromeScanner(html)
        sc.feed(html)
        sc.close()
        sc.flush()
        if not sc.spans:
            return html
        merged: list[list[int]] = []
        for start, end in sorted(sc.spans):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        out, prev = [], 0
        for start, end in merged:
            if start > prev:
                out.append(html[prev:start])
            out.append(" ")
            prev = max(prev, end)
        out.append(html[prev:])
        return "".join(out)
    except Exception:  # noqa: BLE001 — 裁剪失败不该让整次搜索失败
        return html


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
    - 先剥掉导航/页头页脚/侧栏（见 strip_chrome），否则站点菜单里的详情页形状
      链接会冒充搜索结果（gamer520 实测就这么选错了游戏）。
    """
    html = strip_chrome(html)
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
            scores[bare] = (
                1.0
                if DETAILISH_RE.search(bare) or SLUG_DETAIL_RE.search(path)
                else 0.5
            )
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
