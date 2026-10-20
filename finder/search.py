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

from .lang import CJK_RE, KANA_RE
from .models import SearchHit, Site

NAV_RE = re.compile(
    r"/(login|register|signup|tag|tags|category|categor|page/\d+|about|contact|"
    r"privacy|terms|feed|rss|user|profile|search|wp-content|wp-admin|wp-json|"
    r"wp-includes|assets|static|list|lists|forums?|thread|donations?|"
    # `/archives/category/…`、`/archives/tag/…`、`/archives/2026`（年份归档）
    # 都是列表页；但 `/archives/67`、`/archives/6661` 是文章详情页（nekogal
    # 实测），不能一起剔。年份必须收紧成 19xx/20xx —— 原来写 `\d{4}` 会把
    # id=6661 这类四位数文章页当年份归档删掉，查「制服カノジョ」时该站明明
    # 有 3 篇结果却解析出 0 条。
    r"archives?/(?:category|tag|author|date|page|(?:19|20)\d{2}(?:/|$))|"
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
    # `/\d{2,}` 必须「整段就是数字」：否则 `/2257.so`（ggbases 页脚的法律声明页）
    # 会被当成详情页给 1.0，搜索 0 结果时 pick_best 只能选中它（真站实测）。
    r"(/\d{2,}(?:/|$|\?|#)|/game/|/detail|/post/|/topic/detail/|/subject/|/entry/"
    r"|\.html$|/item/"
    # `.so?id=N` / `.php?id=N` / `.aspx?id=N` 这类「脚本 + 数字 id」详情页
    # （ggbases 实测：view.so?id=131080 曾是 0.5 分，选不中）
    r"|\.(?:so|php|aspx?|cgi)\?[^#]*\bid=\d+"
    # 论坛帖 slug：数字埋在 slug 中间、无扩展名，上面 `/\d{2,}(?:/|$)` 匹配不到。
    # anime-sharing 实测 `/threads/new-release-260910-エンターグラム/` 曾被判 0.5，
    # 整站从 dl=10 退化成 pick_best=None。只认 `/threads/`（XenForo 形状），
    # 不放宽到 `/members/<name>.<id>/`（用户页不该当资源）。
    r"|/threads/[^/?#]+/?)",
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
# 只认 alt= / aria-label=（用于内层 <img alt=> 封面标题），不含 title=：
# 内层 title= 常是上传者名（ggbases 实测），抢走它会丢掉真正的游戏名。
ALT_ATTR_RE = re.compile(
    r'(?:^|\s)(?:alt|aria-label)=["\']([^"\']{2,400})["\']', re.I
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


def clamp_query_detail(site: Site, query: str) -> tuple[str, bool, bool]:
    """按站点词长上限截断，并额外判断「是否把拉丁词拦腰切断」。

    返回 `(实际查询词, 是否截断, 是否切在词中间)`。`clamp_query` 保持旧的两值
    契约不变（缓存键等旧调用方依赖它），本函数只给 `search_one` 用。

    为什么要判「切在词中间」（真站实测 2026-10-18，acggw `max_query_len: 10`）：
    用户查 `summer clover`（13 字）被截成 `summer clo`。acggw 的详情页命中
    `summer` 但不命中 `clo`；然而整句 `summer clo` 又是 `Summer Clover` 的
    **子串**，「整句匹配」这一层挡不住 → 用户看到的是**别的游戏**。
    所以这类截断必须在发请求之前就放弃该站（报 `QUERY_TOO_LONG`），
    不能拿半截词去搜。

    规则（由 tests/test_mid_word_cut.py 锁定）：
      - 拉丁词：截断点两侧都是字母/数字才算半词（`summer cl|over`）。
      - 切在空格上（`summer |clover`）或切在完整 token 之后（`summer clo| ver`）
        都算**干净**截断 —— 截下来的整词仍能代表查询意图，照旧去搜。
      - CJK / 假名没有词边界（而且 `'莉'.isalnum()` 为真），硬截断永远放行；
        混合查询只要含 CJK/假名就跟随 CJK 规则。
      - 没有站点上限 / 未发生截断时永远是 False。
    """
    q, truncated = clamp_query(site, query)
    if not truncated:
        return q, False, False
    raw = query or ""
    if CJK_RE.search(raw) or KANA_RE.search(raw):
        return q, True, False
    limit = len(q)
    if limit <= 0 or limit >= len(raw):
        return q, True, False
    if raw[limit - 1].isalnum() and raw[limit].isalnum():
        return q, True, True
    return q, True, False


def _same_origin(url: str, page_url: str) -> bool:
    try:
        return urlparse(url).netloc == urlparse(page_url).netloc
    except Exception:  # noqa: BLE001
        return False


def _strip_fragment(url: str) -> str:
    return url.split("#", 1)[0]


def _anchor_title(attrs: str, body_html: str) -> str:
    """取链接标题：锚点自身的 title= > 内层 img alt= > </a> 之前的可见文本。

    注意「锚点自身」这一点（2026-10-18 ggbases 实测）：结果行是嵌套锚点

        <a href="...view.so?id=131080">
          <a class="keya" title="2D.G.F.">2D.G.F.</a>   <- 上传者名
          <b>制服カノジョ3 めいか初恋BOX</b>              <- 真正的标题
        </a>

    旧实现在 `attrs + body[:400]` 上一起找 title=，于是命中的是**内层**的
    `title="2D.G.F."`，游戏名整个丢失 → pick_best 拿不到查询词命中，
    三语全部 WRONG_GAME。所以必须分段找：先只看锚点自身的 attrs。
    """
    own = TITLE_ATTR_RE.findall(attrs)
    if own:
        return re.sub(r"\s+", " ", own[0]).strip()[:300]
    alt = ALT_ATTR_RE.findall(attrs + " " + body_html[:400])
    if alt:
        return re.sub(r"\s+", " ", alt[0]).strip()[:300]
    inner = _outer_anchor_inner(body_html)
    text = re.sub(r"<[^>]+>", " ", inner)
    return re.sub(r"\s+", " ", text).strip()[:300]


_ANCHOR_TAG_RE = re.compile(r"<a\b|</a\s*>", re.I)

# 单个锚点内部 HTML 的扫描上限。kungal 的搜索结果卡片内层有 3931 字符
# （封面 + 统计 + 标题 + 社团 + 评分），旧的 4000 上限勉强够、700 窗口远不够：
# 窗口不够时 `_outer_anchor_inner` 找不到配对的 `</a>`，会退化成「截前 600
# 字符」，而那 600 字符全是封面 div，游戏名永远取不到。
_ANCHOR_INNER_LIMIT = 20000


def _outer_anchor_inner(body_html: str) -> str:
    """取「外层锚点」的内部 HTML，正确处理嵌套 `<a>`。

    不能简单截到第一个 `</a>`：ggbases 的结果行是
        <a href="view.so?id=131080"><a title="2D.G.F.">2D.G.F.</a><b>游戏名</b></a>
    截到第一个 `</a>` 只会拿到上传者名，游戏名在后面被切掉。
    这里按 `<a` / `</a>` 的嵌套深度找到与外层配对的那个结束标签。
    """
    depth = 1
    limit = min(len(body_html), _ANCHOR_INNER_LIMIT)
    for m in _ANCHOR_TAG_RE.finditer(body_html, 0, limit):
        if m.group(0).lower().startswith("</"):
            depth -= 1
            if depth == 0:
                return body_html[: m.start()]
        else:
            depth += 1
    return body_html[: min(len(body_html), _ANCHOR_INNER_LIMIT)]


_DATA_URI_RE = re.compile(r"data:[\w/+.\-]+;base64,[A-Za-z0-9+/=\s]{200,}", re.I)

# 「纯讨论串」形状：只有一串数字的帖子路径。压分（不排除），因为有些站的
# 游戏页本身也走 /topic/…，但一定带 detail 之类的段（jidiyouxi 的
# `/topic/detail/<id>`），所以这里要求数字紧跟在 topic/post/thread/forum 后。
THREAD_RE = re.compile(r"/(?:topic|post|thread|forum)/(\d+)/?$", re.I)

# 「求资源」帖：标题带 [Request] / [REQ] / 求档 之类前缀，正文是「谁有这个」，
# 不含下载链接。实测 2026-10-18（anime-sharing 查「制服カノジョ」）：求资源帖
# 标题以查询词开头拿满位置分，压过前面带日期/厂商前缀的真发布帖，
# 于是抽出 0 条下载、报 NO_DOWNLOADS。压分不排除（见 pick_best）。
REQUEST_RE = re.compile(
    r"^\s*[\[\(【]?\s*(?:request|req|wanted|looking\s+for|iso)\s*[\]\)】]?"
    r"|[\[\(【]\s*(?:request|req|求档|求資源|求资源|求物)\s*[\]\)】]",
    re.I,
)

_CJK_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")


def _strip_data_uris(html: str) -> str:
    """把内联 base64 data URI 的载荷压掉（保留前缀，不留正文）。

    kungal 实测（2026-10-18）：搜索结果卡片的封面是内联 base64 PNG，单张卡
    的 innerHTML 有 8201 字符、其中 8000+ 是图。`parse_result_links` 只把
    `html[m.end():m.end()+700]` 这段窗口交给 `_anchor_title`，于是窗口里
    全是 base64，游戏名（在窗口外）永远拿不到，标题退化成
    `'<div class="kun-image-blur '` 这种碎片。

    在扫描前整体压掉载荷，既保住 DOM 结构（偏移一致），又让 700 字符窗口
    装得下真正的文本。只压长于 200 字符的载荷，避免误伤小图标。
    """
    return _DATA_URI_RE.sub("data:image/x;base64,", html or "")


def parse_result_links(html: str, page_url: str, site: Site) -> list[SearchHit]:
    """从搜索结果页抽候选详情链接。同域 + 排除导航/静态资源 + 详情形状加分。

    - 相对路径先 urljoin 成绝对 URL（线上 jidiyouxi 就是相对路径）。
    - 同一 URL 出现多次（封面链接 + 标题链接）时保留信息量最大的标题。
    - 搜索页自身的排序/筛选变体（同 path、只差 query）不算结果。
    - 先剥掉导航/页头页脚/侧栏（见 strip_chrome），否则站点菜单里的详情页形状
      链接会冒充搜索结果（gamer520 实测就这么选错了游戏）。
    """
    html = strip_chrome(html)
    html = _strip_data_uris(html)
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
        title = _anchor_title(
            m.group(0), html[m.end(): m.end() + _ANCHOR_INNER_LIMIT]
        )
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
    """归一化：小写 + 去掉分隔符与装饰性符号。

    装饰符号这一项是 kungal 实测加的：站点官方名是「千恋＊万花」（全角星号
    U+FF0A 插在中间），用户输入「千恋万花」时子串匹配直接失败。这类星号/
    波浪号在标题里只是排版装饰，不该参与匹配。
    """
    return re.sub(
        r"[\s\-_·・:：,，.。()（）\[\]【】＊﹡∗★☆〜~～/／|｜]+", "", (s or "").lower()
    )


def _norm_spaced(s: str) -> str:
    """只去掉装饰性符号、**保留空白**的归一化。

    `_norm` 会连空格一起去掉，用于「逐字命中率」；但查询词的正则对拉丁词要求
    词边界（`(?<![a-z0-9])`），把空格也去掉后 `Ender Lilies` 会粘成
    `enderlilies`，边界断言就对不上了。这个版本只清装饰符号。
    """
    return re.sub(r"[＊﹡∗★☆〜~～/／|｜·・]+", " ", (s or "").lower())


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
      -6   纯讨论串形状（THREAD_RE）—— 见下

    讨论串压分（2026-10-18 kungal 实测）：搜索结果是混合的，游戏条目
    `/galgame/15`（有「本体资源下载」标签页）与论坛帖 `/topic/3887`（纯讨论）
    同时命中。帖子标题以查询词开头，位置分拿满，条目页标题前面有统计数字
    （`266576 93 3 天前 千恋＊万花 …`）位置分略低 —— 于是选了**讨论帖**，
    用户拿不到下载链接。压分而不是排除：只有帖子命中时仍要能返回。
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
        score = 0.0
        pos = None
        if rx is not None:
            m = rx.search(raw_title)
            if m is not None:
                pos = m.start()
            else:
                # 站点官方名常带排版装饰（kungal 是「千恋＊万花」全角星号），
                # 原始标题上匹配不到。退到「只去装饰、保留空格」的形态再试一次，
                # 这样拉丁词边界 `(?<![a-z0-9])` 依然有效。
                m = rx.search(_norm_spaced(raw_title))
                if m is not None:
                    pos = m.start()
                elif _CJK_RE.search(query or ""):
                    # CJK 标题里装饰符可能插在词中间（千恋＊万花），去空格后
                    # 才能命中。只对 CJK 查询启用：拉丁短查询（"AI"）去空格
                    # 会命中 "Chained"，那正是 Task 7 修掉的缺陷。
                    i = _norm(raw_title).find(_norm(query))
                    if i >= 0:
                        pos = i
        if pos is not None:
            score += 12.0
            # 命中越靠前越好（标题开头就是游戏名）
            score += 1.0 * (1.0 - min(pos, 60) / 60.0)
        t = _norm(raw_title)
        if qn:
            score += sum(1 for ch in qn if ch in t) / len(qn)
        score += h.score * 0.1
        if THREAD_RE.search(urlparse(h.url).path or ""):
            score -= 6.0
        if REQUEST_RE.search(raw_title):
            # 求资源帖：标题里没有「有下载」的信号，压到发布帖之下。
            # 压分而非排除 —— 站上只有求资源帖时仍要如实返回。
            score -= 6.0
        if score > best_score:
            best_score = score
            best = h
    return best
