"""把 browser + search + detail 串成一条抓取管线。

一条链路：
  搜索页（url 模板 / form 输入）→ parse_result_links → pick_best
  → 详情页 → extract_card

硬约束（都是前几个任务实测出来的，别改）：
  - 绝不直接消费 hits[0]：parse_result_links 里分类页/导航页是 0.5 分，
    真文章才 1.0 分；gamer520 的 /pcplay 就在 hits 里。必须过 pick_best。
  - force_headful 只有在用 BrowserSession.for_site 时才生效，所以 run()
    按 force_headful 分组开会话，而不是全程一个会话。
  - 详情页可能被 Cloudflare 换成 "Access denied" 页（gamer520 实测），
    这必须当错误报，不能当「抽到了空下载」的成功。
  - 搜索页可能明确回「Nothing Found」（flysheep 实测），此时页面里仍有
    导航链接能凑出 hits，必须识别无结果文案，否则会把 dl=0 报成成功。
  - jidiyouxi 搜索页正文只有 ~160 字节，但链接不少；成败看链接数，不看正文长度。
  - pick_best 只能在搜索页链接里挑，看不到详情页正文；标题打分并列时它会按
    出现顺序选第一个（gamer520 实测：查 enderlilies 选中了固件整合包）。
    所以选完之后必须再做一次**内容证据闸门**：详情页标题/正文里连一个查询词
    都找不到，就是选错游戏，报 WRONG_GAME，绝不能挂上别的游戏的下载链接。
"""
from __future__ import annotations

import base64
import html as html_mod
import json
import queue
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from .detail import (
    build_magnet_from_torrent,
    build_magnet_url,
    extract_card,
    parse_magnet_ids,
)
from .lang import CJK_RE, KANA_RE
from .models import Download, GameDetail, SearchHit, Site
from .search import (
    _norm,
    build_search_url,
    clamp_query,
    parse_result_links,
    pick_best,
)

SEARCH_TIMEOUT = 45000
DETAIL_TIMEOUT = 45000
SETTLE_MS = 2500

# 排版空白（不间断空格 U+00A0 / 全角空格 U+3000 等）归一成普通空格。
# ggbases 空结果页输出 `0\xa0個資源`，不做归一化标记永远匹配不上。
_SPACEY_RE = re.compile(r"[\u00a0\u2000-\u200b\u202f\u205f\u3000\t\r\n]+")

# 被 Cloudflare / 防火墙挡下来的页面特征（小写匹配）
BLOCK_MARKERS = (
    "access denied",
    "just a moment",
    "attention required",
    "cf-error-details",
    "enable javascript and cookies to continue",
    "verify you are human",
    "checking your browser",
)

# 站点明确表达「没有结果」——此时页面里的导航链接不是搜索结果
NO_RESULTS_MARKERS = (
    "nothing found",
    "nothing matched your search",
    "no results",
    "抱歉，没有找到",
    "没有找到相关",
    "未找到相关",
    "找不到相关",
    "无搜索结果",
    "没有搜索到",
    # 实测各站自己的「真的没有」文案（2026-10-18，逐个在真站上抓到的）：
    #   acggw    → "搜索结果 没有内容"
    #   nekogal  → "共找到 0 个文章" + "暂无内容"
    #   galgamex → "暂无游戏收录"
    #   ggbases  → "0 個資源"（繁体；`enderlilies` / `千恋万花` 实测都是 0 条）
    # 少了这几条就会掉进 "NO_RESULTS: pick_best returned None" 这种含糊报错。
    "搜索结果 没有内容",
    "没有内容",
    "共找到 0 个",
    "暂无内容",
    "暂无游戏收录",
    "0 個資源",
    "0 个资源",
    #   gamebounty → "没有关于“千恋万花”的结果"（2026-10-18 实测；英文界面
    #   时是 "No results for ..."）。少了它，空结果会掉进
    #   "NO_RESULTS: pick_best returned None"，看不出是站点真的没有。
    #   jidiyouxi → "无相关搜索"（实测查不存在的游戏时，同时 游戏专区 (0)）
    "没有关于",
    "没有相關",
    "no results for",
    "无相关搜索",
    "無相關搜索",
)


def _settle(page, ms: int = SETTLE_MS) -> None:
    """尽量等页面安静下来；networkidle 超时不算错误（很多站有长连接）。"""
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:  # noqa: BLE001
        pass


class FormSearchError(RuntimeError):
    """form 模式找不到可用输入框 —— 与 Playwright 的超时区分开，便于报错归类。"""


@dataclass
class FormOutcome:
    """form 搜索的执行结果。effective=False 时页面上的链接不是搜索结果。"""

    navigated: bool = False
    anchors_before: int = 0
    anchors_after: int = 0

    def new_anchor_count(self) -> int:
        return max(0, self.anchors_after - self.anchors_before)

    @property
    def effective(self) -> bool:
        """页面跳转过，或者原地长出了新链接（实时下拉）——都算搜索生效。

        实测反例（2026-10-18）：
          gamebounty / sayafx 是 Ctrl+K 命令面板，填字+回车后 URL 不变、
          链接数不变（75→75、2420→2420），首页列表照旧在 → 不是结果。
          anime-sharing 原地不动，但输入后多出 5 条匹配链接 → 是结果。
        """
        return self.navigated or self.new_anchor_count() > 0


# 通用输入框候选，按「更像搜索框」排序
GENERIC_INPUT_SELECTORS = (
    "input[type=search]",
    "input[name*=search i]",
    "input[id*=search i]",
    "input[placeholder*=搜索]",
    "input[placeholder*=Search i]",
    "input[placeholder*=搜索 i]",
    "input[name*=keyword i]",
    "input[name=s]",
    "input[name*=s]",
    "input[type=text]",
)

# 点击后能展开折叠搜索框的元素候选
GENERIC_OPEN_SELECTORS = (
    "[class*=search]",
    "[id*=search i]",
    "[aria-label*=earch]",
    "button[title*=搜索]",
    ".search-icon",
)

# 数页面链接用：只要 href，不需要标题
_ANCHORS_JS = (
    "() => Array.from(document.querySelectorAll('a[href]'))"
    ".map(a => a.href)"
)


def _anchor_count(page) -> int:
    try:
        return len(page.evaluate(_ANCHORS_JS))
    except Exception:  # noqa: BLE001
        return 0


def _first_visible(page, selector: str):
    """在 selector 命中的元素里取第一个**可见**的；全不可见则返回 None。

    这是本缺陷的要害：anime-sharing 首页 25 个 input、前 8 个都是 0x0 隐藏的
    name=keywords，`locator(sel).first` 直接 fill 会一直等到超时。
    """
    try:
        loc = page.locator(selector)
        n = loc.count()
    except Exception:  # noqa: BLE001
        return None
    for i in range(min(n, 20)):
        try:
            cand = loc.nth(i) if hasattr(loc, "nth") else loc.first
            if cand.is_visible(timeout=500):
                return cand
        except Exception:  # noqa: BLE001
            continue
        if not hasattr(loc, "nth"):
            break
    return None


def _open_collapsed_box(page, site: Site):
    """搜索框折叠时先点开它（gamebounty / touchgal / sayafx 实测都需要）。"""
    selectors = []
    if site.search.open_selector:
        selectors.append(site.search.open_selector)
    selectors.extend(GENERIC_OPEN_SELECTORS)
    for sel in selectors:
        try:
            el = _first_visible(page, sel)
            if el is None:
                continue
            el.click(timeout=3000)
            page.wait_for_timeout(900)
            return sel
        except Exception:  # noqa: BLE001
            continue
    return None


def _form_search(
    page, site: Site, query: str, timeout_ms: int = SEARCH_TIMEOUT
) -> FormOutcome:
    """在首页填搜索框并提交。找不到输入框抛 FormSearchError，否则返回 FormOutcome。"""
    input_selectors = (
        [site.search.input_selector] if site.search.input_selector else []
    ) + list(GENERIC_INPUT_SELECTORS)

    box = None
    for sel in input_selectors:
        box = _first_visible(page, sel)
        if box is not None:
            break

    if box is None:
        if _open_collapsed_box(page, site):
            for sel in input_selectors:
                box = _first_visible(page, sel)
                if box is not None:
                    break

    if box is None:
        raise FormSearchError(
            f"no visible input found on {site.homepage} "
            f"(tried {len(input_selectors)} selectors)"
        )

    url_before = getattr(page, "url", "")
    anchors_before = _anchor_count(page)

    box.fill(query, timeout=10000)

    # 实时下拉站（anime-sharing）在 fill 之后就已经出结果，再看一次
    try:
        page.wait_for_timeout(1200)
    except Exception:  # noqa: BLE001
        pass

    submitted = False
    if site.search.submit_selector:
        try:
            btn = _first_visible(page, site.search.submit_selector)
            if btn is not None:
                btn.click(timeout=5000)
                submitted = True
        except Exception:  # noqa: BLE001
            pass
    if not submitted:
        box.press("Enter")

    _settle(page, 3000)
    try:
        page.wait_for_timeout(1500)
    except Exception:  # noqa: BLE001
        pass

    return FormOutcome(
        navigated=getattr(page, "url", "") != url_before,
        anchors_before=anchors_before,
        anchors_after=_anchor_count(page),
    )
    try:
        page.wait_for_timeout(ms)
    except Exception:  # noqa: BLE001
        pass


def _visible_text(html: str) -> str:
    """粗抽可见文本（去 script/style/标签），用于「无结果」判定。

    必须先反转义 HTML 实体：真站空结果页输出的是 `0&nbsp;個資源`，
    不反转义的话拿到的是字面量 `&nbsp;`，后面的空白归一化永远对不上。
    """
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html or "", flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    return re.sub(r"\s+", " ", text)


# 站点自己的前端接口挂掉时的特征。这类页面长得像空结果，但其实是暂态：
# jidiyouxi 实测 `游戏专区 (0) … 无相关搜索 Network Error`，隔一会儿重开
# 同一个 URL 就正常出结果（40 条）。必须重试，不能记成 NO_RESULTS。
TRANSIENT_MARKERS = ("network error",)

# 暂态页的正文极短（jidiyouxi 实测 164～215 字符），真实结果页上千字符。
# 只用标记命中判断即可；这个阈值用于「标记没命中但正文短得可疑」时补一次重试。
_TRANSIENT_TEXT_MIN = 300


def _looks_transient(html: str) -> bool:
    text = _SPACEY_RE.sub(" ", _visible_text(html))
    low = text.lower()
    if any(m in low for m in TRANSIENT_MARKERS):
        return True
    return len(text) < _TRANSIENT_TEXT_MIN


def looks_blocked(title: str, html: str) -> str | None:
    """返回命中的拦截特征（原文小写），没命中返回 None。

    只看标题 + 正文前 4000 字符：整页 HTML 里常带 Cloudflare 的脚本，
    全页扫描会误报「所有页都被拦」。
    """
    blob = f"{title or ''}\n{(html or '')[:4000]}".lower()
    for marker in BLOCK_MARKERS:
        if marker in blob:
            return marker
    return None


def looks_no_results(title: str, html: str) -> str | None:
    """识别站点明确的无结果文案；返回命中的特征，没命中返回 None。

    必须先把各类「排版空白」归一成普通空格：ggbases 空结果页实测输出
    `0\xa0個資源`（不间断空格 U+00A0），标记表里写普通空格永远匹配不上，
    于是空结果掉进 `pick_best returned None` 的含糊报错。
    """
    blob = f"{title or ''} {_visible_text(html)}".lower()
    blob = _SPACEY_RE.sub(" ", blob)
    for marker in NO_RESULTS_MARKERS:
        if marker in blob:
            return marker
    return None


def match_strength(query: str, hit_title: str) -> tuple[float, str]:
    """查询词与结果标题的匹配强度：返回 (逐字命中率, strong|weak|none)。

    只作诊断用，**不作为硬门槛**：同一款游戏在不同站的中文译名常常不同
    （gamer520 上「终焉之莉莉」就是「终结的百合花：骑士们的救赎」），
    硬卡阈值会误杀真实结果。
    """
    q = _norm(query)
    t = _norm(hit_title)
    if not q:
        return 0.0, "none"
    if q in t:
        return 1.0, "strong"
    rate = sum(1 for ch in q if ch in t) / len(q)
    return rate, ("strong" if rate >= 0.8 else "weak" if rate > 0 else "none")


# 网络层可重试的失败（不是站点真的没有内容，而是连接抖了 / 被限流一瞬间）
RETRYABLE_NAV = (
    "ERR_CONNECTION_CLOSED",
    "ERR_CONNECTION_RESET",
    "ERR_CONNECTION_ABORTED",
    "ERR_EMPTY_RESPONSE",
    "ERR_NETWORK_CHANGED",
    "ERR_TIMED_OUT",
    "Timeout",
)


def _goto(page, url: str, timeout: int, retries: int = 0) -> tuple[int | None, str | None]:
    """导航到 url。返回 (http_status, nav_error)；nav_error 不为 None 时页面可能是残页。

    `retries>0` 时对**网络层**失败退避重试：jidiyouxi 在短时间连续搜索后会
    直接 `ERR_CONNECTION_CLOSED`（实测同 URL 隔一会儿再来就 200），
    ggbases 偶发 `Page.goto: Timeout 45000ms exceeded`。这类不是站点的
    内容结论，不该被记成「搜索失败」。HTTP 4xx/5xx **不重试** —— 那是
    站点的明确回答。
    """
    attempt = 0
    while True:
        try:
            resp = page.goto(url, timeout=timeout, wait_until="load")
            status = getattr(resp, "status", None) if resp is not None else None
            return status, None
        except Exception as exc:  # noqa: BLE001
            msg = f"{type(exc).__name__}: {str(exc)[:200]}"
            if attempt >= retries or not any(m in msg for m in RETRYABLE_NAV):
                return None, msg
            attempt += 1
            try:
                _settle(page, 1500 * attempt)
            except Exception:  # noqa: BLE001
                pass


# 「下载跳板」链接形状：本站中转到网盘落地页的中间层
GATE_RE = re.compile(r"/go\b|/down(load)?\b|/dl\b|/getfile|/outlink|/jump", re.I)


def _find_gate_links(html: str, page_url: str) -> list[str]:
    """找出详情页里通往网盘落地页的跳板链接（不抓取，只记录）。"""
    out: list[str] = []
    for m in re.finditer(r'href=["\']([^"\']+)["\']', html or "", re.I):
        url = urljoin(page_url, m.group(1))
        if not GATE_RE.search(urlparse(url).path or ""):
            continue
        if url not in out:
            out.append(url)
    return out[:5]


def _page_title(page) -> str:
    try:
        return page.title() or ""
    except Exception:  # noqa: BLE001
        return ""


# 客户端搜索索引（sayafx 实测：/search.xml 760 条 <entry><title>/<url>）。
# 这种站没有可用的搜索页/搜索框，站点把索引整份发下来在浏览器里本地过滤。
INDEX_ENTRY_RE = re.compile(
    r"<entry>\s*<title>(.*?)</title>\s*<url>(.*?)</url>", re.I | re.S
)


def parse_search_index(xml: str) -> list[tuple[str, str]]:
    """把站点的搜索索引 XML 解析成 [(标题, 相对URL)]。解不出就返回空表。"""
    out: list[tuple[str, str]] = []
    for m in INDEX_ENTRY_RE.finditer(xml or ""):
        title = re.sub(r"<[^>]+>", "", m.group(1) or "")
        title = re.sub(r"\s+", " ", title).strip()
        url = (m.group(2) or "").strip()
        if title and url:
            out.append((title, url))
    return out


def hits_from_index(
    entries: list[tuple[str, str]], site: Site, query: str, base_url: str,
    limit: int = 20,
) -> list[SearchHit]:
    """在本地索引里按查询词过滤，产出与 parse_result_links 同形的 SearchHit。

    匹配规则刻意保守（索引条目少、标题是人工写的）：
      1. 整个查询词出现（忽略大小写/空白/标点）→ 命中
      2. 否则查询词的每个「词」（空白切分）都出现 → 命中
    不做逐字模糊匹配：sayafx 上用「终焉之莉莉」做逐字匹配会命中 118 条
    毫不相干的条目（实测），那等于没有搜索。
    """
    q = _norm(query)
    if not q:
        return []
    words = [_norm(w) for w in re.split(r"\s+", (query or "").strip()) if w.strip()]
    words = [w for w in words if w]

    out: list[SearchHit] = []
    for title, rel in entries:
        t = _norm(title)
        if q in t or (words and all(w in t for w in words)):
            out.append(
                SearchHit(
                    site_id=site.id,
                    title=title,
                    url=urljoin(base_url, rel),
                    score=1.0,
                )
            )
        if len(out) >= limit:
            break
    return out


def _index_search(
    page, site: Site, query: str, timeout_ms: int = SEARCH_TIMEOUT
) -> tuple[list[SearchHit], dict[str, Any]]:
    """index 模式：直接取站点的搜索索引，在本地过滤。返回值与诊断信息。"""
    info: dict[str, Any] = {"mode": "index"}
    if not site.search.index_url:
        raise FormSearchError(f"site {site.id} has no index_url configured")

    resp = page.request.get(site.search.index_url, timeout=timeout_ms)
    xml = resp.text()
    entries = parse_search_index(xml)
    info.update(
        {
            "index_url": site.search.index_url,
            "index_status": getattr(resp, "status", None),
            "index_bytes": len(xml),
            "index_entries": len(entries),
        }
    )
    hits = hits_from_index(entries, site, query, site.homepage)
    info["index_hits"] = len(hits)
    return hits, info


def _detail_body_text(page, html: str) -> str:
    """详情页可见文本：优先 innerText（浏览器渲染后的正文），拿不到再退回 HTML 去标签。

    innerText 只在页面里取一次，不重新导航（详情页已经加载好了）。
    取失败时用 HTML 兜底，绝不能因为拿不到正文就把它当成「选错游戏」。
    """
    try:
        text = page.evaluate("() => document.body.innerText || ''")
        if isinstance(text, str) and text.strip():
            return text
    except Exception:  # noqa: BLE001
        pass
    return _visible_text(html)


def _query_evidence(query: str, title: str, body_text: str) -> int:
    """查询词在详情页标题/正文里命中多少项（按语种给不同的计法）。

    这是 pick_best 之后的**内容证据闸门**：pick_best 只看搜索页的链接标题，
    看不到详情页正文；gamer520 实测查 `enderlilies` 时会选中一个「Switch 固件
    整合包」的页面（标题里没有任何查询词），却挂着 3 条真实网盘链接 ——
    用户会下到完全错误的游戏。所以选完之后必须验证页面上真提到了查询词。

    计数（0 = 判为选错游戏）：
      - CJK / 假名查询：按**不同汉字/假名字符**命中数计。单字命中很弱但非零，
        所以门槛只卡「一个都没有」；跨译名的结果（终焉之莉莉 → 终结的百合花）
        靠这一条兜住。标点不算证据，否则正文里的「：」就能把错页放行。
      - 拉丁查询：按长度 >= 3 的词计，避免 "ai" 命中 "chained" 这类噪声。
        命中判定：整词命中，或去掉分隔符后整串命中（"enderlilies" 要能对上
        页面里的 "Ender Lilies"）；后者只对长度 >= 5 的词生效，防短词噪声。
        若查询里所有词都短于 3（如 "AI"），仍按整词判，否则短查询永远是 0。
      - 空 haystack / 空查询一律 0（查询为空什么也证明不了）。
    """
    hay = f"{title or ''} {body_text or ''}".lower()
    if not hay.strip():
        return 0
    q = (query or "").strip().lower()
    if not q:
        return 0
    if CJK_RE.search(q) or KANA_RE.search(q):
        chars = {ch for ch in q if CJK_RE.match(ch) or KANA_RE.match(ch)}
        return sum(1 for ch in chars if ch in hay)
    parts = [t for t in re.split(r"[^a-z0-9]+", q) if t]
    toks = [t for t in parts if len(t) >= 3] or parts
    compact_hay = re.sub(r"[^a-z0-9]+", "", hay)
    found = 0
    for t in toks:
        if re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", hay):
            found += 1
        elif len(t) >= 5 and t in compact_hay:
            found += 1
    return found


def search_one(
    page,
    site: Site,
    query: str,
    timeout_ms: int = SEARCH_TIMEOUT,
) -> GameDetail:
    """单站：搜索 → 选最佳结果 → 进详情页 → 抽卡。失败返回带 error 的 GameDetail。

    extra 里带全链路诊断（命中数、各级 HTTP 状态、拦截/无结果特征、匹配强度），
    冒烟脚本与将来的 UI 都靠它判断失败在哪一层。
    """
    q, truncated = clamp_query(site, query)
    extra: dict[str, Any] = {"truncated": truncated, "query_used": q, "mode": site.search.mode}

    if site.search.mode == "index":
        # 索引站：没有可用搜索页，直接取整份索引在本地过滤。
        try:
            hits, idx_info = _index_search(page, site, q, timeout_ms)
        except Exception as exc:  # noqa: BLE001
            return GameDetail(
                site_id=site.id,
                url=site.homepage,
                title="",
                error=f"INDEX_FAILED: {type(exc).__name__}: {str(exc)[:150]}",
                extra=extra,
            )
        extra.update(idx_info)
        best = pick_best(hits, q)
        if best is None:
            return GameDetail(
                site_id=site.id,
                url=site.homepage,
                title="",
                error=f"NO_RESULTS: index has no entry matching {q!r}",
                extra=extra,
            )
        rate, strength = match_strength(q, best.title)
        extra.update(
            {
                "hits": len(hits),
                "best_url": best.url,
                "best_title": best.title[:200],
                "best_score": best.score,
                "match_rate": round(rate, 2),
                "match": strength,
            }
        )
        return _extract_detail(page, site, q, best.url, timeout_ms, extra)

    if site.search.mode == "url":
        url = build_search_url(site, q)
        status, nav_error = _goto(page, url, timeout_ms, retries=2)
        _settle(page)
        # 站内搜索接口偶发失败会渲染成空列表 + 自己的错误提示，看起来跟
        # 「真的没有」一模一样。jidiyouxi 实测：同一个 URL 前一次正文只有
        # `游戏专区 (0) … 无相关搜索 Network Error`（HTML 54KB），隔几分钟
        # 再来同样的请求就正常渲染出结果。**这类暂态必须先重试**，否则会把
        # 「站点抖了一下」永久记成 NO_RESULTS（还会进失败缓存）。
        for _retry in range(2):
            if not _looks_transient(page.content()):
                break
            extra.setdefault("search_transient_retries", 0)
            extra["search_transient_retries"] += 1
            _settle(page, 4000)
            if _looks_transient(page.content()):
                _goto(page, url, timeout_ms)
                _settle(page, 4000)
    else:
        start_url = site.search.form_url or site.homepage
        status, nav_error = _goto(page, start_url, timeout_ms)
        _settle(page)
        try:
            outcome = _form_search(page, site, q, timeout_ms)
        except Exception as exc:  # noqa: BLE001
            return GameDetail(
                site_id=site.id,
                url=getattr(page, "url", site.homepage),
                title="",
                error=f"FORM_FAILED: {type(exc).__name__}: {str(exc)[:150]}",
                extra=extra,
            )
        extra["form_navigated"] = outcome.navigated
        extra["form_new_anchors"] = outcome.new_anchor_count()
        if not outcome.effective:
            # 关键：搜索没生效时，页面上的链接是首页内容（导航/推荐列表），
            # 当成结果会把「India Cats」这种无关游戏报成命中。
            return GameDetail(
                site_id=site.id,
                url=getattr(page, "url", site.homepage),
                title="",
                error=(
                    "FORM_FAILED: search did not execute "
                    f"(url unchanged, no new links; {outcome.anchors_before} anchors)"
                ),
                extra=extra,
            )
        status = None

    search_url = page.url
    search_html = page.content()
    search_title = _page_title(page)
    search_block = looks_blocked(search_title, search_html)
    marker = looks_no_results(search_title, search_html)
    hits = parse_result_links(search_html, search_url, site)
    best = pick_best(hits, q)
    # 有候选时不能让「无结果」标记覆盖它：有些站的空结果文案是**常驻模板**，
    # 有结果时也照样留在 DOM 里。playzip 实测 `hollow knight` 2 条真结果、
    # `No results found,` 那个 div 仍然 display:block 可见 —— 纯文本无法区分，
    # 只有「解析出候选」才是硬证据。标记仍然写进 extra 供排查。
    no_results = marker if best is None else None

    extra.update(
        {
            "hits": len(hits),
            "search_url": search_url,
            "search_status": status,
            "search_body_len": len(search_html),
            "search_title": search_title[:200],
        }
    )
    if nav_error:
        extra["search_nav_error"] = nav_error
    if search_block:
        extra["search_block_marker"] = search_block
    if marker:
        extra["no_results_marker"] = marker
        if no_results is None:
            extra["no_results_overridden_by_hits"] = len(hits)
    if best is not None:
        rate, strength = match_strength(q, best.title)
        extra.update(
            {
                "best_url": best.url,
                "best_title": best.title[:200],
                "best_score": best.score,
                "match_rate": round(rate, 2),
                "match": strength,
            }
        )

    # 搜索层失败：拦截 > 明确无结果 > 导航失败 > HTTP 错 > 没有候选
    if search_block:
        return GameDetail(
            site_id=site.id,
            url=search_url,
            title="",
            error=f"BLOCKED_SEARCH: {search_block}",
            extra=extra,
        )
    if no_results:
        return GameDetail(
            site_id=site.id,
            url=search_url,
            title="",
            error=f"NO_RESULTS: {no_results}",
            extra=extra,
        )
    if best is None:
        if nav_error:
            error = f"SEARCH_NAV_FAILED: {nav_error}"
        elif status is not None and status >= 400:
            error = f"HTTP_{status}"
        else:
            error = "NO_RESULTS: pick_best returned None"
        return GameDetail(site_id=site.id, url=search_url, title="", error=error, extra=extra)

    return _extract_detail(page, site, q, best.url, timeout_ms, extra)


def _extract_detail(
    page,
    site: Site,
    q: str,
    target_url: str,
    timeout_ms: int,
    extra: dict[str, Any],
) -> GameDetail:
    """进详情页并抽卡 + 内容证据闸门。url/form/index 三种模式共用这一段。"""
    d_status, d_nav_error = _goto(page, target_url, timeout_ms, retries=2)
    _settle(page)
    detail_url = page.url
    detail_html = page.content()
    detail_block = looks_blocked(_page_title(page), detail_html)
    extra.update({"detail_url": detail_url, "detail_status": d_status,
                  "detail_body_len": len(detail_html)})
    if d_nav_error:
        extra["detail_nav_error"] = d_nav_error
    if detail_block:
        extra["detail_block_marker"] = detail_block

    if detail_block:
        return GameDetail(
            site_id=site.id,
            url=detail_url,
            title="",
            error=f"BLOCKED_DETAIL: {detail_block}",
            extra=extra,
        )
    if d_nav_error:
        return GameDetail(
            site_id=site.id,
            url=detail_url,
            title="",
            error=f"DETAIL_NAV_FAILED: {d_nav_error}",
            extra=extra,
        )
    if d_status is not None and d_status >= 400:
        return GameDetail(
            site_id=site.id,
            url=detail_url,
            title="",
            error=f"DETAIL_HTTP_{d_status}",
            extra=extra,
        )

    card = extract_card(detail_html, detail_url, site.id)
    card.extra.update(extra)

    # 内容证据闸门（本文件头注释 / _query_evidence 详述）：
    # pick_best 只看搜索页链接标题，看不见详情页正文。gamer520 实测查 enderlilies
    # 会选中「Switch 固件整合包」——标题里 0 个查询词，却挂着 3 条真实网盘链接。
    # 这种卡片对用户是「下载错游戏」，必须报错，绝不能当成功返回。
    body_text = _detail_body_text(page, detail_html)
    evidence = _query_evidence(q, card.title, body_text)
    card.extra["evidence"] = evidence
    card.extra["detail_text_len"] = len(body_text or "")
    if evidence == 0:
        card.extra["wrong_game"] = True
        card.downloads = []          # 关键：不挂任何下载链接
        card.error = "WRONG_GAME: no query evidence in page"
        return card

    if not card.downloads:
        # 有些站详情页本身不含网盘链，要先点一个按钮才渲染出资源页链接
        # （touchgal 实测：「下载」按钮点完才出现 /{game}/resource/{id}）。
        # ggbases 实测：`kinds: [磁力]`，但详情页没有任何 `magnet:` 文本。
        # 磁力在独立的 magnet.so?id=N 页，hash 由页面 JS POST 拿。
        # 必须在**页面内 fetch**（复用浏览器网络栈与 cookie）：page.request
        # 走独立 TLS 连接，实测 ECONNRESET / 30s 超时。
        if site.search.download_flow == "ggbases":
            card.downloads = _fetch_ggbases_magnets(
                page, detail_html, detail_url, timeout_ms, extra
            )
        elif site.search.download_flow == "ankergames":
            card.downloads = _fetch_ankergames_link(
                page, site, timeout_ms, extra
            )
        if site.search.torrent_selector:
            card.downloads = card.downloads + _fetch_torrent_magnets(
                page, site, timeout_ms, extra
            )
        followed = _follow_detail_gate(page, site, detail_url, timeout_ms, extra)
        if followed is not None:
            return followed
        card.extra.update(extra)
        if not card.downloads:
            # gamer520 实测：详情页本身不含网盘链接，只有一个 /go?post_id=<id> 跳板。
            # 不自动跟进：实测该跳板会把 post 带到 520.gamers520.com/<n>.html，
            # 而落地页标题与 post 对不上（可能按登录态/推荐位分流），
            # 自动跟进有把「别的游戏」的网盘链接挂到本结果上的风险。只记录证据。
            card.extra["gate_links"] = _find_gate_links(detail_html, detail_url)
            card.error = "NO_DOWNLOADS"
    return card


def _fetch_ggbases_magnets(
    page, detail_html: str, detail_url: str, timeout_ms: int, extra: dict[str, Any]
) -> list[Download]:
    """ggbases：详情页没有 `magnet:` 文本，磁力在独立的 magnet.so?id=N 页。

    hash 由那页的 JS 点「復製磁鏈」后 POST 拿到：
        POST /magnet.so?downid=<uuid>&json=1&id=N  ->  {"hash":"e018ad..."}
    downid 每次访问都会变，所以必须先把 magnet 页取下来读它。

    必须用**页面内 fetch**：page.request 走独立 TLS 连接，真站实测
    ECONNRESET 或 30s 超时；页面内 fetch 复用浏览器网络栈与 cookie，稳定 200。
    取不到就返回空（诚实报 NO_DOWNLOADS，不猜 hash）。
    """
    ids = parse_magnet_ids(detail_html, detail_url)
    extra["gg_magnet_ids"] = ids
    if not ids:
        return []

    base = f"{urlparse(detail_url).scheme}://{urlparse(detail_url).netloc}"
    out: list[Download] = []
    for mid in ids[:3]:                      # 一页最多跟进 3 个，避免拖慢
        magnet_page = f"{base}/magnet.so?id={mid}"
        # 先真的打开磁力页：downid 是在**这一页**渲染时生成的，从详情页
        # 直接 fetch 拿不到（页面内 fetch 那一步实测抛 Error）。
        try:
            status, nav_err = _goto(page, magnet_page, timeout_ms)
            _settle(page, 1200)
        except Exception as exc:  # noqa: BLE001
            extra.setdefault("gg_magnet_errors", []).append(
                f"goto({mid}): {type(exc).__name__}"
            )
            continue
        if nav_err:
            extra.setdefault("gg_magnet_errors", []).append(f"goto({mid}): {nav_err}")
            continue
        try:
            html = page.content()
        except Exception as exc:  # noqa: BLE001
            extra.setdefault("gg_magnet_errors", []).append(
                f"content({mid}): {type(exc).__name__}"
            )
            continue
        downids = list(dict.fromkeys(re.findall(r"downid=([0-9a-fA-F\-]{36})", html or "")))
        if not downids:
            extra.setdefault("gg_magnet_errors", []).append(f"no-downid({mid})")
            continue
        try:
            body = page.evaluate(
                """async ([d, i]) => {
                    const r = await fetch(`/magnet.so?downid=${d}&json=1&id=${i}`, {
                        method:'POST',
                        headers:{'X-Requested-With':'XMLHttpRequest'},
                        credentials:'include'
                    });
                    return r.ok ? await r.text() : '';
                }""",
                [downids[0], mid],
            )
        except Exception as exc:  # noqa: BLE001
            extra.setdefault("gg_magnet_errors", []).append(
                f"post({mid}): {type(exc).__name__}"
            )
            continue
        try:
            h = (json.loads(body or "{}") or {}).get("hash") or ""
        except Exception:  # noqa: BLE001
            h = ""
        url = build_magnet_url(h)
        if url and all(d.url != url for d in out):
            out.append(Download(kind="magnet", url=url))
    return out


def _fetch_torrent_magnets(
    page, site: Site, timeout_ms: int, extra: dict[str, Any]
) -> list[Download]:
    """byrutgame：详情页的下载按钮直接返回 `.torrent` 种子。

    实测 2026-10-18：`https://byrutgame.org/index.php?do=download&id=<n>`
    回 `application/x-bittorrent`（55 KB 种子），整页 HTML 里**没有**任何
    `magnet:` 文本 —— 磁力链只能由种子的 info hash 本地算出。

    种子必须用**页面内 fetch** 取（数组 → base64 传回来）：
    `page.request` 走独立 TLS 连接，与 ggbases 那次一样会被拒。取不到就
    返回空，由上层如实报 NO_DOWNLOADS，不猜 hash。
    """
    sel = site.search.torrent_selector or ""
    if not sel:
        return []
    try:
        href = page.evaluate(
            """(sel) => {
                for (const a of document.querySelectorAll(sel)) {
                    const h = a.href || a.getAttribute('href') || '';
                    if (h) return h;
                }
                return '';
            }""",
            sel,
        )
    except Exception as exc:  # noqa: BLE001
        extra.setdefault("torrent_errors", []).append(f"locate: {type(exc).__name__}")
        return []
    if not href:
        extra.setdefault("torrent_errors", []).append("locate: no-match")
        return []
    extra["torrent_href"] = href
    try:
        b64 = page.evaluate(
            """async (url) => {
                const r = await fetch(url, {credentials:'include'});
                if (!r.ok) return '';
                const buf = await r.arrayBuffer();
                let s = '';
                const bytes = new Uint8Array(buf);
                for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
                return btoa(s);
            }""",
            href,
        )
    except Exception as exc:  # noqa: BLE001
        extra.setdefault("torrent_errors", []).append(f"fetch: {type(exc).__name__}")
        return []
    if not b64:
        extra.setdefault("torrent_errors", []).append("fetch: empty")
        return []
    try:
        data = base64.b64decode(b64)
    except Exception:  # noqa: BLE001
        extra.setdefault("torrent_errors", []).append("fetch: bad-base64")
        return []
    extra["torrent_bytes"] = len(data)
    magnet = build_magnet_from_torrent(data)
    if not magnet:
        extra.setdefault("torrent_errors", []).append("parse: no-info-hash")
        return []
    return [Download(kind="magnet", url=magnet, label="种子")]


def _fetch_ankergames_link(
    page, site: Site, timeout_ms: int, extra: dict[str, Any]
) -> list[Download]:
    """ankergames：下载要过「生成下载页 → Cloudflare Turnstile → /link」。

    实测流程 2026-10-18（无登录、无需人工过盾）：
      1. 详情页 HTML 里有 `generateDownloadUrl(<download_id>)`（实测 id=1524）。
         它只是 POST `/generate-download-url/<id>`（带 csrf-token），返回
         `{"success":true,"download_url":".../download/<payload>/<hash>"}`。
         **直接调这个接口比点按钮稳**：点按钮要靠 Alpine 模态 + 标签跳转，
         实测同一次会话里时成时不成（广告脚本/Turnstile 会抢时序）。
      2. 打开那个 `download_url`（中间页），页内 `window.agTurnstile.tokenAsync()`
         静默出 token。
      3. 页面内 fetch `<base>/link?cf-turnstile-response=<token>` 回
         `{"success":true,"link":"https://tunnel5.dlproxy.uk/download/...?sig=..."}`。

    全程在页面内（fetch 复用浏览器网络栈与 cookie）；`page.request` 走独立
    TLS 连接，与 ggbases 同因会被拒。取不到返回空并写 extra 错误，不猜链接。
    """
    errs: list[str] = []

    def _fail(msg: str) -> list[Download]:
        extra["ank_errors"] = errs + [msg]
        return []

    # 1. 取 download_id → 生成中间页 URL
    try:
        dl_id = page.evaluate(
            """() => {
                const html = document.documentElement.outerHTML;
                const m = html.match(/generateDownloadUrl\\((\\d+)\\)/);
                return m ? m[1] : '';
            }"""
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(f"id: {type(exc).__name__}")
    if not dl_id:
        return _fail("id: not-found")
    extra["ank_download_id"] = dl_id
    try:
        gen = page.evaluate(
            """async (id) => {
                const meta = document.querySelector('meta[name=csrf-token]');
                const r = await fetch('/generate-download-url/' + id, {
                    method: 'POST', credentials: 'include',
                    headers: {'X-CSRF-TOKEN': meta ? meta.content : '',
                              'X-Requested-With': 'XMLHttpRequest',
                              'Content-Type': 'application/json',
                              'Accept': 'application/json'},
                    body: '{}'
                });
                return await r.text();
            }""",
            dl_id,
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(f"generate: {type(exc).__name__}")
    try:
        mid_url = (json.loads(gen or "{}") or {}).get("download_url") or ""
    except Exception:  # noqa: BLE001
        return _fail("generate: bad-json")
    if not mid_url.startswith("http"):
        return _fail("generate: no-download-url")
    extra["ank_mid_url"] = mid_url[:120]

    # 2. 打开中间页（换到它自己的对象上取 token）
    try:
        status, nav_err = _goto(page, mid_url, timeout_ms)
    except Exception as exc:  # noqa: BLE001
        return _fail(f"mid: {type(exc).__name__}")
    if nav_err:
        return _fail(f"mid: {nav_err}")
    _settle(page, 3000)                        # 等 Turnstile 脚本就绪

    # 3. 页内取 token → /link
    try:
        body = page.evaluate(
            """async () => {
                const el = document.querySelector('[x-data*=downloadPage]');
                const raw = el ? (el.getAttribute('x-data') || '') : '';
                const m = raw.match(/downloadPage\\('([^']+)'/);
                if (!m) return JSON.stringify({error: 'no-base-url'});
                const base = m[1].replace(/\\\\/g, '');
                if (!window.agTurnstile || !window.agTurnstile.tokenAsync) {
                    return JSON.stringify({error: 'no-turnstile'});
                }
                let tok = '';
                // tokenAsync 在脚本还没就绪时会抛，轮询几次再放弃
                for (let i = 0; i < 20; i++) {
                    try { tok = await window.agTurnstile.tokenAsync(); }
                    catch (e) { tok = ''; }
                    if (tok) break;
                    await new Promise(r => setTimeout(r, 500));
                }
                if (!tok) return JSON.stringify({error: 'empty-token'});
                const r = await fetch(base + '/link?cf-turnstile-response=' +
                                      encodeURIComponent(tok), {credentials: 'include'});
                return await r.text();
            }"""
        )
    except Exception as exc:  # noqa: BLE001
        return _fail(f"link: {type(exc).__name__}")
    try:
        payload = json.loads(body or "{}")
    except Exception:  # noqa: BLE001
        return _fail("link: bad-json")
    if payload.get("error"):
        return _fail(f"link: {payload['error']}")
    link = (payload.get("link") or "").strip()
    if not link.startswith("http"):
        return _fail("link: missing")
    extra["ank_link_len"] = len(link)
    return [Download(kind="direct", url=link, label="直链")]


def _follow_detail_gate(
    page, site: Site, detail_url: str, timeout_ms: int, extra: dict[str, Any]
) -> GameDetail | None:
    """详情页下载链要二次跳转时跟进一层（只在站里配了 detail_follow_pattern 时做）。

    返回抽好的 GameDetail，或 None 表示该站不适用/没找到可跟进的链接。
    只跟进一层：touchgal 的 resource 页就是终点，正文里直接是网盘链。

    特例（kungal 实测）：有些站点了标签页**不跳转**，链接直接在同一页渲染。
    这种站只配 detail_open_selector、不配 detail_follow_pattern —— 点击后
    就地重新抽卡，不做导航。
    """
    pattern = site.search.detail_follow_pattern
    open_sel = site.search.detail_open_selector
    if not pattern and not open_sel:
        return None
    # 只有 open_selector 的站 = 「就地展开」，不需要跳转
    reveal_only = not pattern

    opened = None
    if open_sel:
        try:
            el = _first_visible(page, open_sel)
            if el is None and not reveal_only:
                el = page.get_by_role("button", name="下载").first
            if el is not None:
                try:
                    empty = el.count() == 0
                except Exception:  # noqa: BLE001
                    empty = False
                if not empty:
                    el.click(timeout=8000)
                    page.wait_for_timeout(3000)
                    opened = open_sel
        except Exception as exc:  # noqa: BLE001
            extra["detail_open_error"] = f"{type(exc).__name__}: {str(exc)[:100]}"

    if reveal_only:
        if opened is None:
            extra.setdefault("detail_reveal_missing", open_sel)
            return None
        # 就地重抽：点完标签页后同一页就有网盘链了
        try:
            html_now = page.content()
        except Exception as exc:  # noqa: BLE001
            extra["detail_reveal_error"] = f"{type(exc).__name__}: {str(exc)[:100]}"
            return None
        extra["detail_revealed"] = True
        extra["detail_reveal_selector"] = opened
        extra["detail_reveal_body_len"] = len(html_now)
        card = extract_card(html_now, detail_url, site.id)
        card.extra.update(extra)
        if not card.downloads:
            card.error = "NO_DOWNLOADS"
        return card

    rx = re.compile(pattern)
    target = None
    try:
        html = page.content()
        for m in re.finditer(r'href=["\']([^"\']+)["\']', html, re.I):
            url = urljoin(detail_url, m.group(1))
            if rx.search(urlparse(url).path or "") and url != detail_url:
                target = url
                break
    except Exception as exc:  # noqa: BLE001
        extra["detail_gate_scan_error"] = f"{type(exc).__name__}: {str(exc)[:100]}"

    extra["detail_opened"] = opened
    if target is None:
        extra["detail_follow_missing"] = pattern
        return None

    extra["detail_followed_url"] = target
    status, nav_error = _goto(page, target, timeout_ms)
    _settle(page)
    final_url = page.url
    html2 = page.content()
    extra.update(
        {
            "detail2_url": final_url,
            "detail2_status": status,
            "detail2_body_len": len(html2),
        }
    )
    if nav_error:
        extra["detail2_nav_error"] = nav_error
        return None
    if looks_blocked(_page_title(page), html2):
        extra["detail2_block_marker"] = looks_blocked(_page_title(page), html2)
        return None

    card = extract_card(html2, final_url, site.id)
    card.extra.update(extra)
    if not card.downloads:
        card.error = "NO_DOWNLOADS"
    return card


def normalize_query(query: str | None) -> str:
    """缓存键归一：去首尾空白 + 连续空白压成一个 + 转小写。

    不做去标点/全半角归一：那会让「终焉之莉莉」和「终焉之莉莉！」共用缓存，
    而站点对这两者的检索结果确实可能不同，属于过度合并。
    """
    text = (query or "").strip().lower()
    return re.sub(r"\s+", " ", text)


def _run_one_site(
    config: dict,
    root: Path,
    site: Site,
    query: str,
    timeout: int,
    store,
    cache_on: bool,
    profile_override: Path | None,
) -> GameDetail:
    """单站的完整流程（含缓存读写）。供串行与并发两条路径共用。

    profile_override 为 None 时用主 profile（串行路径）；并发时每个 worker
    传自己的目录 —— Chrome 会锁住 user-data-dir，共享目录会有一个失败。
    """
    from .browser import BrowserSession

    clamped, _ = clamp_query(site, query)
    key = normalize_query(clamped)
    if cache_on:
        hit = store.get_cached(key, site.id)
        if hit is not None:
            hit.extra = dict(hit.extra or {})
            hit.extra["cached"] = True
            return hit

    page = None
    with BrowserSession.for_site(config, root, site,
                                 profile_override=profile_override) as sess:
        try:
            page = sess.new_page()
            card = search_one(page, site, query, timeout_ms=timeout)
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:  # noqa: BLE001
                    pass
    if cache_on:
        # 失败也写缓存，但 Store 对带 error 的条目用更短的 fail_ttl 过期
        # （默认 30 分钟）——否则重复搜索会被失败站拖慢到和首次一样。
        store.put_cached(key, card)
    return card


def run(
    config: dict,
    sites: list[Site],
    query: str,
    project_root: Path,
    store=None,
    use_cache: bool = True,
    workers: int | None = None,
) -> list[GameDetail]:
    """对一组站点跑搜索。返回顺序**始终**与传入 sites 一致。

    workers（并发度）：
      - None / 1 → 串行，用主 profile（chrome-profile），行为与旧版一致
      - >1     → 线程池并发，每个 worker 一份独立 profile（chrome-profile-w<N>），
                 启动前从主 profile 播种登录态（实测 0.02s）

    为什么并发必须换 profile：Chrome 会锁住 user-data-dir，实测同一目录并发
    2 个 persistent context 只有 1 个能起来（另一个 TargetClosedError）；
    独立目录 3 个并发全部成功、总耗时 5.3s。

    force_headful 的站永远走串行 headful 会话：它们的用途是让人工过盾，
    并发起来反而互相抢窗口。

    缓存：键是 (归一后的**实际查询词**, site_id)，实际词 = clamp_query 之后的值；
    只缓存成功结果（error is None）——失败被缓存 12 小时等于剥夺用户重试机会。
    """
    from .browser import BrowserSession, seed_worker_profile, worker_profile_dir

    root = Path(project_root)
    search_cfg = config.get("search") or {}
    timeout = int(search_cfg.get("timeout_ms") or SEARCH_TIMEOUT)
    cache_on = store is not None and use_cache

    n_workers = int(workers if workers is not None
                    else (search_cfg.get("workers") or 1))
    n_workers = max(1, min(n_workers, max(1, len(sites))))

    headless_idx = [i for i, s in enumerate(sites) if not s.force_headful]
    headful_idx = [i for i, s in enumerate(sites) if s.force_headful]
    results: dict[int, GameDetail] = {}

    def _safe(idx: int, profile: Path | None) -> None:
        site = sites[idx]
        try:
            results[idx] = _run_one_site(
                config, root, site, query, timeout, store, cache_on, profile
            )
        except Exception as exc:  # noqa: BLE001
            results[idx] = GameDetail(
                site_id=site.id, url=site.homepage, title="",
                error=f"{type(exc).__name__}: {str(exc)[:150]}",
            )

    # ---- 串行路径（workers=1，行为与旧版一致）----
    if n_workers == 1:
        for idx in headless_idx:
            _safe(idx, None)
        if headful_idx:
            with BrowserSession.for_site(config, root, sites[headful_idx[0]]) as sess:
                for idx in headful_idx:
                    page = None
                    try:
                        page = sess.new_page()
                        results[idx] = search_one(
                            page, sites[idx], query, timeout_ms=timeout
                        )
                        if cache_on:
                            clamped, _ = clamp_query(sites[idx], query)
                            store.put_cached(normalize_query(clamped), results[idx])
                    except Exception as exc:  # noqa: BLE001
                        results[idx] = GameDetail(
                            site_id=sites[idx].id, url=sites[idx].homepage,
                            title="", error=f"{type(exc).__name__}: {str(exc)[:150]}",
                        )
                    finally:
                        if page is not None:
                            try:
                                page.close()
                            except Exception:  # noqa: BLE001
                                pass
        return [results[i] for i in range(len(sites))]

    # ---- 并发路径：每个 worker 一份独立 profile ----
    primary = resolve_worker_primary(config, root)
    profiles: list[Path] = []
    for w in range(n_workers):
        p = worker_profile_dir(root, w)
        seed_worker_profile(primary, p)
        profiles.append(p)

    # profile 是**独占资源**：Chrome 会锁住 user-data-dir，两个线程同时用一个
    # 目录必有一个 TargetClosedError（实测）。所以用队列发放，用完归还——
    # 而不是按下标取模（那样 11 站 3 槽会出现多线程共用同一目录）。
    available: queue.Queue[Path] = queue.Queue()
    for p in profiles:
        available.put(p)

    def _task(idx: int) -> None:
        profile = available.get()
        try:
            _safe(idx, profile)
        finally:
            available.put(profile)

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = [pool.submit(_task, idx) for idx in headless_idx]
        for fut in as_completed(futures):
            fut.result()  # _safe 已兜住异常；这里只等完成

    # headful 组始终串行（人工过盾场景，并发没意义还会抢窗口）
    if headful_idx:
        with BrowserSession.for_site(config, root, sites[headful_idx[0]]) as sess:
            for idx in headful_idx:
                page = None
                try:
                    page = sess.new_page()
                    results[idx] = search_one(
                        page, sites[idx], query, timeout_ms=timeout
                    )
                    if cache_on:
                        clamped, _ = clamp_query(sites[idx], query)
                        store.put_cached(normalize_query(clamped), results[idx])
                except Exception as exc:  # noqa: BLE001
                    results[idx] = GameDetail(
                        site_id=sites[idx].id, url=sites[idx].homepage,
                        title="", error=f"{type(exc).__name__}: {str(exc)[:150]}",
                    )
                finally:
                    if page is not None:
                        try:
                            page.close()
                        except Exception:  # noqa: BLE001
                            pass

    return [results[i] for i in range(len(sites))]


def resolve_worker_primary(config: dict, root: Path) -> Path:
    """并发 worker 播种的源目录 = 配置里的主 profile。"""
    from .browser import resolve_profile_dir

    b = config.get("browser") or {}
    return resolve_profile_dir(root, b.get("profile_dir", "chrome-profile"))
