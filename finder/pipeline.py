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
import logging
import queue
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from .detail import (
    ASSET_URL_RE,
    _classify,
    build_magnet_from_torrent,
    build_magnet_url,
    extract_card,
    parse_magnet_ids,
)
from .lang import CJK_RE, KANA_RE
from .models import Download, GameDetail, SearchHit, Site
from .search import (
    DETAILISH_RE,
    SLUG_DETAIL_RE,
    _norm,
    build_search_url,
    clamp_query,
    clamp_query_detail,
    parse_result_links,
    pick_best,
)
from urllib.parse import urlparse

SEARCH_TIMEOUT = 45000
DETAIL_TIMEOUT = 45000
SETTLE_MS = 2500

# v0.1.1 -> v0.1.2 回归：pipeline.py 里 3 处 log.info/warning 没有 logger，
# ensure_logged_in 一旦真的登录成功就 NameError，整次搜索直接崩掉。
# 单测全程不触发登录路径，所以 578 个测试全绿也发现不了。
log = logging.getLogger("gamefinder.pipeline")

# 排版空白（不间断空格 U+00A0 / 全角空格 U+3000 等）归一成普通空格。
# ggbases 空结果页输出 `0\xa0個資源`，不做归一化标记永远匹配不上。
_SPACEY_RE = re.compile(r"[\u00a0\u2000-\u200b\u202f\u205f\u3000\t\r\n]+")
# 路径里的「搜索段」——用来把站内搜索 URL 从「详情页形状」里排掉。
# 刻意只收 search/find/query：`s`、`so` 这类太短的词会把正常路径误伤。
SEARCH_PATH_RE = re.compile(r"(?:^|/)(?:search|find|query)(?:/|$)", re.I)

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
    #   touchgal → "未找到相關內容"（2026-10-18 实测，form 模式查「夏色四叶草」）。
    #   该站的搜索**确实执行了**，但页面不跳转、也不新增锚点 —— 只有这句文案
    #   是站方给出的「没有」结论。少了它，`FormOutcome.effective` 会判成
    #   「表单没生效」，用户拿到误导性的 FORM_FAILED。
    #   **必须排在笼统的「未找到相关」之前**：标记表是按顺序取首个命中，
    #   先命中短标记的话，报错里就只剩「未找到相关」，丢掉站方原文。
    "未找到相關內容",
    "未找到相关内容",
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
    #   ankergames → "No games found / Try different filters or browse the full
    #   catalogue."（2026-10-18 实测：查日文游戏名时该站英文库确实 0 条）
    "no games found",
)


def _settle(page, ms: int = SETTLE_MS) -> None:
    """尽量等页面安静下来；networkidle 超时不算错误（很多站有长连接）。

    实测（2026-10-22）：真正的时间大头是这个函数。`ms` 以前**根本没被用**，
    上限写死 10s，于是每个「永远到不了 networkidle」的站（长连接/心跳/广告位）
    都要白等满 10 秒 —— 一轮 14 站里有两个站各吃掉 10.01s。
    现在按 `ms` 走，默认 2.5s：干净的站 0.5～1s 就 idle 返回，不干净的站
    最多等 ms 就往下走。慢渲染的站由 `_looks_transient` 的重试循环兜底
    （那里会传更大的 ms）。
    """
    cap = ms if isinstance(ms, int) and ms > 0 else SETTLE_MS
    try:
        page.wait_for_load_state("networkidle", timeout=cap)
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

# 搜索页被站点重定向到登录页。galgame.dev 实测：搜索 URL 直接 302 到 /login，
# 页面上只剩导航链接，被解析成 6 条 0.5 分候选 → pick_best 返回 None →
# 报成 NO_RESULTS，用户会以为站上没有这款游戏（sites.yaml 里它本来就标了
# needs_login: true）。
#
# 只认**落地 URL 的路径**，不扫正文：导航里到处都有「登录」「登录后可见」
# 这类词，扫 HTML 会把每个带登录入口的搜索页都误判成墙。
_LOGIN_PATH_RE = re.compile(
    r"/(?:login|log-in|signin|sign-in|sign_in|auth|account/login)(?:[/?#]|$)",
    re.I,
)


def looks_login_wall(url: str, html: str = "") -> str | None:
    """搜索落地在某站的登录页 → 报 NEEDS_LOGIN，而不是假装「没有结果」。"""
    path = urlparse(url or "").path or ""
    if _LOGIN_PATH_RE.search(path):
        return "NEEDS_LOGIN: 该站搜索需要先登录（搜索页被重定向到登录页）"
    return None


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


def _is_site_search_url(site: Site, url: str) -> bool:
    """url 是不是这个站的**站内搜索 URL 本身**。

    jidiyouxi 的搜索模板是 `https://www.jidiyouxi.com/search/detail/{q}` ——
    路径形状跟详情页一模一样，只看 `DETAILISH_RE` 会把它当成「搜索即跳详情」，
    于是搜索页渲染成空壳（站点抖动）时被当成详情页去抽卡，用户拿到的是
    误导性的 `WRONG_GAME`（2026-10-18 实测 3 次里出现 1 次）。

    先按**站点自己的模板前缀**认（精确），再退回通用的 `/search` 路径段。
    """
    if not url:
        return False
    tpl = getattr(site.search, "url_template", None) or ""
    if "{q}" in tpl:
        prefix = tpl.split("{q}", 1)[0]
        if prefix and url.startswith(prefix):
            return True
    try:
        path = urlparse(url).path or ""
    except Exception:  # noqa: BLE001
        return False
    return bool(SEARCH_PATH_RE.search(path))


def _looks_detail_page(site: Site, url: str) -> bool:
    """当前 URL 是不是「详情页形状」——用于识别「搜索即跳详情」的站点。

    只判路径形状，不看正文：正文判断在 _extract_detail 里已有内容证据闸门，
    这里的作用只是决定「不要因为没解析出列表就放弃」。
    """
    if _is_site_search_url(site, url):
        # 搜索页长得像详情页（jidiyouxi）时，宁可报「没有结果」也不要
        # 假装站在详情页上 —— 后者会把站点抖动说成「页面内容对不上查询」。
        return False
    try:
        parsed = urlparse(url or "")
    except Exception:  # noqa: BLE001
        return False
    if not parsed.path or parsed.path in ("", "/"):
        return False
    bare = parsed.path
    return bool(DETAILISH_RE.search(bare) or SLUG_DETAIL_RE.search(bare))


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


def _evidence_counts(query: str, title: str, body_text: str) -> tuple[int, int]:
    """返回 `(命中项数, 通过所需的命中项数)`。计法与 `_query_evidence` 完全一致。

    抽出来是为了让「命中多少」和「够不够」两个判断永远用同一套计法 ——
    旧代码只有命中数，闸门写成 `> 0`，于是 acggw 的 `summer clo`
    （summer 中、clo 不中）照样放行，用户看到别的游戏。
    """
    hay = f"{title or ''} {body_text or ''}".lower()
    if not hay.strip():
        return 0, 1
    q = (query or "").strip().lower()
    if not q:
        return 0, 1
    if CJK_RE.search(q) or KANA_RE.search(q):
        # CJK/假名没有词边界：required 恒为 1，跨译名（终焉之莉莉→终结的百合花）
        # 才能靠「命中一个字」通过。
        chars = {ch for ch in q if CJK_RE.match(ch) or KANA_RE.match(ch)}
        return sum(1 for ch in chars if ch in hay), 1
    parts = [t for t in re.split(r"[^a-z0-9]+", q) if t]
    long_toks = [t for t in parts if len(t) >= 3]
    # required：>=3 字的 token 全中才算数；全是短词（如 "AI"）时回落 1，
    # 否则短查询永远是 0。
    required = len(long_toks) or 1
    pool = long_toks or parts
    compact_hay = re.sub(r"[^a-z0-9]+", "", hay)
    found = 0
    for t in pool:
        if re.search(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", hay):
            found += 1
        elif len(t) >= 5 and t in compact_hay:
            found += 1
    return found, required


def _query_evidence_ok(
    query: str, title: str, body_text: str
) -> tuple[bool, int, int]:
    """内容证据闸门：`(是否通过, 命中数, 所需命中数)`。

    与 `_query_evidence` 的唯一区别是**门槛**：拉丁查询要求 >=3 字的 token
    **全部**命中，而不是命中任一。真站实测（2026-10-18）：

    | 站       | 查询            | token 命中             | `>0` 旧闸门 | 全中 |
    |----------|-----------------|------------------------|-------------|------|
    | acggw    | `summer clo`    | summer=YES, clo=NO     | 误放行 ❌   | 拦下 |
    | galgamex | `summer clover` | summer=YES, clover=YES | 放行        | 放行 |

    空 haystack / 空查询永远不通过（查询为空什么也证明不了）。
    """
    found, required = _evidence_counts(query, title, body_text)
    return found >= required, found, required


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

    回传语义保持旧版（命中数），仍被诊断与既有测试使用；**闸门判定**请用
    `_query_evidence_ok` —— 它才是「全 token 命中」的那道门。
    """
    found, _required = _evidence_counts(query, title, body_text)
    return found


def _page_content(page) -> str | None:
    """读当前页 HTML；读不出来返回 None（页面被站点关掉/导航中会抛）。

    调用方必须把 None 当**错误**处理，绝不能当「空结果页」—— 否则一次读失败
    会被下游的「暂态」判定接手，最后谎报成 `NO_RESULTS`。
    """
    try:
        html = page.content()
    except Exception:  # noqa: BLE001
        return None
    return html if isinstance(html, str) else None


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
    q, truncated, mid_word = clamp_query_detail(site, query)
    extra: dict[str, Any] = {"truncated": truncated, "query_used": q, "mode": site.search.mode}
    if mid_word:
        # 拉丁词被站点上限拦腰切断（acggw `max_query_len: 10` 查 `summer clover`
        # → `summer clo`）。半截词在页面上是别的游戏的子串，搜下去只会把
        # 不相干的游戏挂给用户 —— 发请求之前就放弃，别浪费一次导航。
        extra["query_truncation"] = "mid_word"
        return GameDetail(
            site_id=site.id,
            url=site.homepage,
            title="",
            error=(
                f"QUERY_TOO_LONG: {len(query)} > {site.max_query_len}, "
                f"truncated to {q!r} mid-word"
            ),
            extra=extra,
        )

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
        # v0.1.2：先解析、再决定要不要等。搜索结果是 SSR/半 SSR 的站（jidiyouxi、
        # galgame.dev、ggbases…）在 `load` 事件时链接就已经在 DOM 里了，再等
        # networkidle 纯属白等 0.5–2.5s。解析出候选就跳过 `_settle`；
        # 解析不到才落到下面的等待 + 原有暂态重试（那条路径一个字都没动）。
        early_html = _page_content(page)
        if not (early_html and parse_result_links(early_html, page.url, site)):
            _settle(page)
        # 站内搜索接口偶发失败会渲染成空列表 + 自己的错误提示，看起来跟
        # 「真的没有」一模一样。jidiyouxi 实测：同一个 URL 前一次正文只有
        # `游戏专区 (0) … 无相关搜索 Network Error`（HTML 54KB），隔几分钟
        # 再来同样的请求就正常渲染出结果。**这类暂态必须先重试**，否则会把
        # 「站点抖了一下」永久记成 NO_RESULTS（还会进失败缓存）。
        for _retry in range(2):
            html_now = _page_content(page)
            if html_now is None:
                # 读不出页面 = 无法判定「暂态」，绝不能当成空结果页。
                break
            # **已经有候选就不许重载**。`_TRANSIENT_TEXT_MIN` 是按「正文至少
            # 300 字」猜的，而 jidiyouxi 是 JS 渲染页：出结果时 `_visible_text`
            # 也只有 250 字 → 会被误判成暂态 → 重载把**已经拿到的结果冲掉**，
            # 还要重新碰站点的随机空响应（实测 3 次里只成功 1 次）。
            # 「解析出候选」是硬证据 —— 跟「候选覆盖无结果标记」同一条原则。
            if parse_result_links(html_now, page.url, site):
                break
            if not _looks_transient(html_now):
                break
            # 先给它时间自己渲染，再决定要不要重载：这一页永远「短」，
            # 光看 `_looks_transient` 会一直判暂态。等待后必须**重查候选**，
            # 否则等于每轮都无条件重载（这也是抖动的主要来源）。
            _settle(page, 4000)
            html_now = _page_content(page)
            if html_now is None:
                break
            if parse_result_links(html_now, page.url, site):
                break
            if not _looks_transient(html_now):
                break
            extra.setdefault("search_transient_retries", 0)
            extra["search_transient_retries"] += 1
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
            #
            # 但「没生效」有两种成因，必须分开报：
            #   (a) 表单真的没提交（选择器打偏、站点改版）→ FORM_FAILED，是缺陷。
            #   (b) 站点**确实执行了搜索、并且明确回了「没有」** → touchgal 实测
            #       查「夏色四叶草」逐字显示「未找到相關內容」，URL 不变、也不
            #       新增锚点。站方已经给出了结论，报 FORM_FAILED 会误导用户
            #       （看起来像工具坏了）。所以先复查站点自己的空结果文案。
            # 注意 (b) 只在**没有候选**时成立：文案命中时页面里残留的首页链接
            # 绝不是结果，仍然只能报 NO_RESULTS。
            empty_marker = looks_no_results(_page_title(page), _page_content(page) or "")
            if empty_marker:
                extra["no_results_marker"] = empty_marker
                return GameDetail(
                    site_id=site.id,
                    url=getattr(page, "url", site.homepage),
                    title="",
                    error=f"NO_RESULTS: {empty_marker}",
                    extra=extra,
                )
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
    search_html = _page_content(page)
    if search_html is None:
        # 页面读不出来 ≠ 没有结果。报错必须区分，否则一次读失败会被下游当成
        # 空结果缓存 30 分钟（见缓存键约定），用户重试也拿不到真结果。
        return GameDetail(
            site_id=site.id,
            url=search_url or site.homepage,
            title="",
            error="PAGE_READ_FAILED: could not read search page HTML",
            extra=extra,
        )
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

    # 搜索即跳详情页：部分站点在结果唯一时直接把 /search 302 到详情页
    # （inarigal 实测 `?search=千恋万花` → `/detail/64`）。此时页面上没有
    # 结果列表可解析，但**已经站在正确的详情页上** —— 把它当成「没有候选」
    # 会白白丢掉一个完全可用的结果。
    direct_detail = best is None and not no_results and not search_block and _looks_detail_page(
        site, search_url
    )
    if direct_detail:
        extra["search_redirected_to_detail"] = search_url

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

    # 搜索层失败：拦截 > 登录墙 > 明确无结果 > 导航失败 > HTTP 错 > 没有候选
    if search_block:
        return GameDetail(
            site_id=site.id,
            url=search_url,
            title="",
            error=f"BLOCKED_SEARCH: {search_block}",
            extra=extra,
        )
    # 登录墙优先于「没有结果」：重定向到 /login 的页面上必然解析不出候选，
    # 但原因不是「站上没有这款游戏」，而是「这个站不让未登录的人搜」。
    # 只有真解析不出候选时才算墙 —— 有候选就说明搜索确实执行了。
    if best is None and not direct_detail:
        login_wall = looks_login_wall(search_url, search_html)
        if login_wall:
            extra["search_login_wall"] = search_url
            return GameDetail(
                site_id=site.id,
                url=search_url,
                title="",
                error=login_wall,
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
        if direct_detail:
            # 已经站在详情页上，跳过再导航一次（避免无谓请求与限流）
            return _extract_detail(page, site, q, search_url, timeout_ms, extra, already_open=True)
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
    already_open: bool = False,
) -> GameDetail:
    """进详情页并抽卡 + 内容证据闸门。url/form/index 三种模式共用这一段。

    `already_open=True` 表示页面**已经停在** target_url 上（搜索被站点直接
    302 到详情页的情形），不需要再导航一次。
    """
    if already_open:
        d_status, d_nav_error = extra.get("search_status"), None
    else:
        d_status, d_nav_error = _goto(page, target_url, timeout_ms, retries=2)
        # v0.1.2：先抽卡再决定要不要等。详情页的标题/下载块通常已在首屏 HTML 里，
        # 但**只在「已抽到下载 + 内容证据已成立」时**才跳过 networkidle 等待 ——
        # 证据闸门依赖正文可见文本，正文晚渲染时跳过会误报 WRONG_GAME。
        early_html = _page_content(page)
        early_card = extract_card(early_html, page.url, site.id) if early_html else None
        skip_settle = False
        if early_card is not None and early_card.downloads:
            early_body = _detail_body_text(page, early_html or "")
            early_ok, _ef, _er = _query_evidence_ok(q, early_card.title, early_body)
            skip_settle = early_ok
        if not skip_settle:
            _settle(page)
    detail_url = page.url
    detail_html = _page_content(page)
    if detail_html is None:
        extra.update({"detail_url": detail_url, "detail_status": d_status,
                      "detail_nav_error": d_nav_error or "content unavailable"})
        return GameDetail(
            site_id=site.id,
            url=detail_url or target_url,
            title="",
            error="PAGE_READ_FAILED: could not read detail page HTML",
            extra=extra,
        )
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
    evidence_ok, evidence_found, evidence_required = _query_evidence_ok(
        q, card.title, body_text
    )
    evidence = evidence_found
    card.extra["evidence"] = evidence
    card.extra["evidence_found"] = evidence_found
    card.extra["evidence_required"] = evidence_required
    card.extra["detail_text_len"] = len(body_text or "")
    if not evidence_ok:
        card.extra["wrong_game"] = True
        card.downloads = []          # 关键：不挂任何下载链接
        card.error = "WRONG_GAME: no query evidence in page"
        # 选错游戏时**绝不能**把那个游戏的标题留在卡片上：卡片上挂着真网盘链
        # 加一个不相干的标题，用户看起来就是「找到了」。原值留进 extra 供诊断。
        # 注意取值口径是「原始 picked title」——即使它是空串也要留键，方便
        # 排查「抽不到标题」和「抽到别的标题」两种成因。
        card.extra["wrong_game_title"] = card.title
        card.extra["wrong_game_url"] = detail_url
        card.title = ""
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
        elif site.search.download_flow == "inarigal":
            card.downloads = _fetch_inarigal_links(
                page, site, timeout_ms, extra
            )
        elif site.search.download_flow == "popup_redirect":
            # galgamex 实测：详情页 HTML 里没有任何下载链，链接由 JS 现场生成，
            # 必须点「资源下载」标签页 + 供应商按钮，从 `/redirect?url=` 里解。
            card.downloads = _fetch_popup_redirect_links(
                page, site, timeout_ms, extra
            )
        if site.search.torrent_selector:
            card.downloads = card.downloads + _fetch_torrent_magnets(
                page, site, timeout_ms, extra
            )
        # `_follow_detail_gate` 只是「还没拿到链接」时的兜底（touchgal 的
        # resource 页、kungal 的就地展开）。**已经有链接就绝不能再调它**：
        # 它的 reveal_only 分支会从当前页重新抽卡并**整体替换**返回值，
        # 把 download_flow 刚辛苦点出来的链接全丢掉（galgamex 实测踩到）。
        # popup_redirect 流程自己就负责点开标签页，也不能再被兜底重复点一次。
        followed = (
            _follow_detail_gate(page, site, detail_url, timeout_ms, extra)
            if not card.downloads and site.search.download_flow != "popup_redirect"
            else None
        )
        if followed is not None:
            return followed
        card.extra.update(extra)
        if not card.downloads:
            # gamer520 实测（2026-10-18，两次跟随结果逐字节一致）：详情页本身不含
            # 网盘链接，只有一个 /go?post_id=<id> 跳板。**不自动跟进** ——
            # 落地页 `520.gamers520.com/8191.html` 是第三方聚合站的用户上传帖
            # （面包屑 `… > 322369521 > 5009 牛夫人`，2024-06-04），正文 716 字里
            # 游戏名出现 0 次、`_query_evidence`=0；其百度盘链接还出现在**另一个
            # 帖子**（123857）的落地页上 → 落地页与本游戏无归属关系。
            # 自动跟进会把无法归属的链接挂到用户查的游戏上，所以只记录证据，
            # 并把「有跳板但没直链」单独报出来，不让用户以为是站点没有资源。
            gates = _find_gate_links(detail_html, detail_url)
            card.extra["gate_links"] = gates
            card.error = _classify_empty_detail(detail_html, gates)
    return card


# 「没抽到下载链接」的四种真实原因，必须分开报 —— 都写 NO_DOWNLOADS 会让
# 「需要登录/需要评论」「只有无法归属的跳板」和「适配器坏了」混成一团。
#
# iacg 实测（2026-10-18，`https://iacg.love/56681.html`）：正文里有
#   「此处内容已隐藏，请评论后刷新页面查看.」
# 而页面另外写着「请登录后查看评论内容」——即必须先登录、再评论，才看得到隐藏
# 内容。这类站点报 NO_DOWNLOADS 是误导，用户会以为真的没资源。
GATED_LOGIN_MARKERS = (
    "请登录后查看",
    "请登录后发表评论",
    "登录后查看",
    "登录后可见",
    "login to view",
    "log in to view",
    "sign in to view",
    "you must be logged in",
)
GATED_COMMENT_MARKERS = (
    "评论后刷新页面查看",
    "回复后刷新页面查看",
    "评论后可见",
    "回复后可见",
    "此处内容已隐藏",
    "reply to see",
    "comment to view",
)
GATED_CLOSED_MARKERS = (
    "资源已失效",
    "资源已下架",
    "链接已失效",
    "内容已删除",
    "暫無",
    "暂无",
    "this file has been removed",
)


def _classify_empty_detail(html: str, gate_links=()) -> str:
    """详情页抽不到下载时，给出具体原因而不是一律 NO_DOWNLOADS。"""
    blob = _SPACEY_RE.sub(" ", _visible_text(html or "")).lower()
    if any(m in blob for m in GATED_COMMENT_MARKERS):
        if any(m in blob for m in GATED_LOGIN_MARKERS):
            return "NEEDS_LOGIN: 需登录并评论后才显示下载（该站隐藏内容门槛）"
        return "NEEDS_COMMENT: 需先评论后才显示下载（该站隐藏内容门槛）"
    if any(m in blob for m in GATED_LOGIN_MARKERS):
        return "NEEDS_LOGIN: 页面要求登录后才显示下载"
    if any(m in blob for m in GATED_CLOSED_MARKERS):
        return "NO_DOWNLOADS: 站点自己标注内容不可用"
    if gate_links:
        # 页面有站内跳板但没直链。跳板落地页可能是第三方聚合站的通用页，
        # 与本次查询的游戏无归属关系，所以不自动跟进（见 card.extra["gate_links"]）。
        return (f"NEEDS_GATE: 详情页只有 {len(gate_links)} 条站内跳板链接、没有直链；"
                "跳板落地页无法确认属于本游戏，未自动跟进")
    return "NO_DOWNLOADS"


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


def _fetch_inarigal_links(
    page, site: Site, timeout_ms: int, extra: dict[str, Any]
) -> list[Download]:
    """inarigal：资源条目默认折叠，点「下载资源」才向 API 要真实直链。

    实测流程 2026-10-18（`/detail/684` 制服女友）：
      1. 详情页每个资源是一个 `.resource-item[data-resource-id]`，正文
         `.resource-content` 是 `display:none`，要先点 `.resource-header` 展开；
      2. 展开后有 `button.download-btn`，点它触发
         `GET https://api.<cdn>/api/getdownload/<resource_id>?format=json`
         → `{"success":true,"url":"https://.../xxx.rar?Authorization=..."}`
      3. 那条 `url` 就是可下载的直链（带一次性 Authorization 参数）。

    必须**靠点击 + 监听 response**，不能自己拼 API 域名：API 是
    `api.gscsm.com.cname1541.yjs-cdn.com` 这种 CDN cname，会轮换；
    页面内 fetch 也试过，跨域被拒（`TypeError: Failed to fetch`）。
    取不到就写 extra 错误，绝不猜链接。
    """
    errs: list[str] = []
    captured: list[str] = []
    host_filter = "getdownload"

    def _on_response(resp) -> None:
        try:
            if host_filter not in resp.url:
                return
            body = resp.json()
        except Exception:  # noqa: BLE001
            return
        url = (body or {}).get("url") if isinstance(body, dict) else None
        if url:
            captured.append(url)

    page.on("response", _on_response)
    try:
        items = page.locator(".resource-item")
        try:
            n_items = items.count()
        except Exception as exc:  # noqa: BLE001
            errs.append(f"items: {type(exc).__name__}")
            n_items = 0
        extra["inarigal_resource_items"] = n_items
        for idx in range(min(n_items, 6)):   # 一个游戏通常 1–4 条资源
            item = items.nth(idx)
            try:
                header = item.locator(".resource-header").first
                if header.count():
                    header.click(timeout=8000)
                    page.wait_for_timeout(700)
                btn = item.locator("button.download-btn").first
                if not btn.count():
                    errs.append(f"item{idx}: no-button")
                    continue
                before = len(captured)
                btn.click(timeout=8000)
                for _ in range(20):           # 等接口回来，最多 ~4s
                    if len(captured) > before:
                        break
                    page.wait_for_timeout(200)
                if len(captured) == before:
                    errs.append(f"item{idx}: no-url")
            except Exception as exc:  # noqa: BLE001
                errs.append(f"item{idx}: {type(exc).__name__}")
                continue
    finally:
        try:
            page.remove_listener("response", _on_response)
        except Exception:  # noqa: BLE001
            pass

    if errs:
        extra["inarigal_errors"] = errs
    out: list[Download] = []
    seen: set[str] = set()
    for url in captured:
        if url in seen:
            continue
        seen.add(url)
        out.append(Download(kind=_classify(url), url=url, label="资源直链"))
    return out


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


# 供应商按钮最多点几个。galgamex 实测一页最多 10 个供应商（百度/夸克/阿里/迅雷/
# 天翼/移动/123/MEGA/GDrive/OneDrive），留一点余量；再多就是页面结构变了，
# 把按钮全点一遍只会拖慢并触发风控。
MAX_PROVIDER_CLICKS = 12

# 点完供应商按钮后等跳转的节奏。实测（2026-10-20，`/game/cbe7d89e`）：
# 「分卷」按钮是直接 `<a download>` 式跳转，几十毫秒内 route 就命中；
# 「百度网盘」要先开弹窗再跳，固定等 400ms 会**漏掉它**（真机复现过）。
_PROVIDER_WAIT_MS = 4000
_PROVIDER_POLL_MS = 200


def _decode_redirect_target(url: str) -> str:
    """从站内跳转链里解出真实目标；本来就不是跳转链就原样返回。

    galgamex 实测形状（2026-10-18，`https://www.galgamex.net/game/cbe7d89e`）：
        https://www.galgamex.net/redirect?url=https%3A%2F%2Fpan.baidu.com%2F...
        → unquote(url 参数) = https://pan.baidu.com/s/1aCmoplMimsXAb16i9tfP_A?pwd=us6i
    注意**不能**无条件再 unquote 一次：目标里自带 `%2F` 这类编码时会被解坏。
    只有当参数值看起来仍是整串百分号编码时才补一次。
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
    except Exception:  # noqa: BLE001
        return raw
    if not parsed.query:
        return raw
    try:
        qs = parse_qs(parsed.query)
    except Exception:  # noqa: BLE001
        return raw
    for key in ("url", "u", "target", "to", "link", "redirect", "goto"):
        vals = qs.get(key) or []
        if not vals:
            continue
        cand = (vals[0] or "").strip()
        if not cand:
            continue
        # parse_qs 已经解过一次；若结果仍是 `https%3A%2F%2F...` 这种整串编码，
        # 说明站点做了双重编码，再解一次。
        if cand.lower().startswith("http%3a") or cand.lower().startswith("https%3a"):
            cand = unquote(cand)
        # 参数存在就**以它为准**（哪怕是个 `javascript:void(0)` 之类的水货）：
        # 交给 `_is_real_download_url` 判真伪，绝不能退回去把跳转链本身当下载链。
        return cand
    return raw


def _is_real_download_url(url: str) -> bool:
    """跳转解析出来的目标是不是一条**真下载链**（不是图标、不是 javascript:）。"""
    if not url or not url.startswith(("http://", "https://")):
        return False
    if ASSET_URL_RE.search(url):
        return False
    return True


def _fetch_popup_redirect_links(
    page, site: Site, timeout_ms: int, extra: dict[str, Any]
) -> list[Download]:
    """galgamex：下载按钮点开是**弹窗 + 站内跳转**，链接由 JS 现场生成。

    真站实测（2026-10-18，`https://www.galgamex.net/game/cbe7d89e`）：
      - 详情页原始 HTML 里**搜不到任何** `/redirect?url=`（48 个锚点里没有一条
        是下载链）—— 抽 HTML 永远抽不到，必须真的点。
      - 点「资源下载」标签页后出现供应商按钮（百度网盘 / 夸克 / 阿里云盘 …）；
        点按钮开新窗口，URL 是 `https://www.galgamex.net/redirect?url=<真链>`，
        同时打 `POST /api/game/resource/<id>/download`。
      - 取链手段选**路由拦截**：`context.route("**/redirect*")` 读到 URL 后
        `route.abort()` —— 根本不加载网盘页（省流量、不触发网盘风控），
        比接 popup 更稳。路由偶尔没拦住（`window.open` 直接开新页）时用
        popup 兜底，并立刻 close。

    纪律：
      - 单个按钮坏了（不可点/超时）只记 `extra["galgamex_errors"]`，**不能**
        拖死其它按钮 —— 供应商按钮是彼此独立的。
      - 重复 provider 去重（同一 URL 只留一条）。
      - 没有 selector 时返回空且不抛（站点配置缺失是配置问题，不是崩溃）。
    """
    errs: list[str] = []
    selector = site.search.download_open_selector or ""
    if not selector:
        extra["galgamex_errors"] = errs + ["selector: empty"]
        return []

    context = getattr(page, "context", None)
    captured: list[str] = []
    popups: list[Any] = []

    def _on_route(route) -> None:
        try:
            url = getattr(getattr(route, "request", None), "url", "") or ""
        except Exception:  # noqa: BLE001
            url = ""
        target = _decode_redirect_target(url)
        if target:
            captured.append(target)
        try:
            route.abort()
        except Exception:  # noqa: BLE001
            pass

    def _on_page(popup) -> None:
        popups.append(popup)

    routed = False
    if context is not None:
        try:
            context.route("**/redirect*", _on_route)
            routed = True
        except Exception as exc:  # noqa: BLE001
            errs.append(f"route: {type(exc).__name__}")
        try:
            context.on("page", _on_page)
        except Exception as exc:  # noqa: BLE001
            errs.append(f"listen: {type(exc).__name__}")

    try:
        # 1. 先点开「资源下载」标签页：供应商按钮在这一步之后才渲染。
        open_sel = site.search.detail_open_selector
        if open_sel:
            try:
                opener = _first_visible(page, open_sel)
                if opener is not None:
                    opener.click(timeout=min(timeout_ms, 8000))
                    # v0.1.2：供应商按钮通常点完 0.2–1s 就渲染出来，改成轮询
                    # （每 250ms 查一次，上限仍是 2s），别再无脑等满。
                    waited = 0
                    while waited < 2000:
                        try:
                            if page.locator(selector).count() > 0:
                                break
                        except Exception:  # noqa: BLE001
                            break
                        page.wait_for_timeout(_PROVIDER_POLL_MS)
                        waited += _PROVIDER_POLL_MS
            except Exception as exc:  # noqa: BLE001
                errs.append(f"open: {type(exc).__name__}")

        # 2. 逐个点供应商按钮，从路由/popup 里收真实网盘 URL。
        out: list[Download] = []
        seen: set[str] = set()
        try:
            loc = page.locator(selector)
            total = loc.count()
        except Exception as exc:  # noqa: BLE001
            errs.append(f"locator: {type(exc).__name__}")
            loc, total = None, 0
        if loc is not None and total == 0:
            errs.append("buttons: none")

        clicks = 0
        for i in range(min(total, MAX_PROVIDER_CLICKS)):
            try:
                btn = loc.nth(i) if hasattr(loc, "nth") else loc.first
            except Exception as exc:  # noqa: BLE001
                errs.append(f"nth[{i}]: {type(exc).__name__}")
                continue
            try:
                if hasattr(btn, "is_visible") and not btn.is_visible(timeout=500):
                    continue
            except Exception:  # noqa: BLE001
                pass

            captured.clear()
            popups.clear()
            try:
                btn.click(timeout=min(timeout_ms, 8000))
                clicks += 1
            except Exception as exc:  # noqa: BLE001
                # 单个按钮坏掉不影响其它按钮（真站有供应商按钮不可点）
                errs.append(f"click[{i}]: {type(exc).__name__}")
                continue

            # 路由拦截是同步的，但 popup 往往要等几百毫秒才发起跳转。
            # 实测（2026-10-20）：固定等 400ms 会漏掉「百度网盘」这类最后一个
            # 供应商按钮 —— 它开了弹窗才跳转，400ms 内 route 还没被触发。
            # 所以改成**轮询**：拿到候选或弹窗就立刻收工，最多等 _PROVIDER_WAIT_MS。
            waited = 0
            while waited < _PROVIDER_WAIT_MS and not captured and not popups:
                try:
                    page.wait_for_timeout(_PROVIDER_POLL_MS)
                except Exception:  # noqa: BLE001
                    break
                waited += _PROVIDER_POLL_MS
            if captured or popups:
                # 命中后仍给一点余量，让同一按钮的重复跳转（真站会跳两次）落齐。
                try:
                    page.wait_for_timeout(_PROVIDER_POLL_MS)
                except Exception:  # noqa: BLE001
                    pass

            candidates = list(captured)
            for popup in popups:
                try:
                    purl = getattr(popup, "url", "") or ""
                except Exception:  # noqa: BLE001
                    purl = ""
                if purl:
                    candidates.append(_decode_redirect_target(purl))
                try:
                    popup.close()
                except Exception:  # noqa: BLE001
                    pass
            popups.clear()

            for cand in candidates:
                if not _is_real_download_url(cand):
                    continue
                if cand in seen:
                    continue
                seen.add(cand)
                out.append(Download(kind=_classify(cand), url=cand, label="网盘"))
    finally:
        if routed:
            try:
                context.unroute("**/redirect*")
            except Exception:  # noqa: BLE001
                pass

    extra["galgamex_clicks"] = clicks
    if errs:
        extra["galgamex_errors"] = errs
    if not out:
        extra.setdefault("galgamex_errors", errs + ["links: none"])
    return out


def _wait_reveal(
    page, site: Site, detail_url: str, timeout_ms: int = 3000, step_ms: int = 250
) -> bool:
    """点开「下载/资源」标签页后等目标出现，最多 `timeout_ms`。

    v0.1.2 性能改动（实测）：touchgal 的 resource 链接点了之后 0.2–1s 就渲染出来，
    旧代码固定 `wait_for_timeout(3000)` 白等两次（搜索页/详情页各一次）就能吃掉
    6s。改成「出现即走」：
      - 站里配了 `detail_follow_pattern`：等页面出现匹配的 href；
      - 只配 `detail_open_selector`（就地展开，kungal）：等真的抽到下载链接。
    等不到也不报错 —— 调用方继续按原逻辑处理空结果。
    """
    pattern = site.search.detail_follow_pattern
    rx = re.compile(pattern) if pattern else None
    deadline = time.monotonic() + max(0, timeout_ms) / 1000.0
    while True:
        try:
            html = page.content()
        except Exception:  # noqa: BLE001
            html = ""
        if html:
            if rx is not None:
                for m in re.finditer(r'href=["\']([^"\']+)["\']', html, re.I):
                    url = urljoin(detail_url, m.group(1))
                    if rx.search(urlparse(url).path or "") and url != detail_url:
                        return True
            elif extract_card(html, detail_url, site.id).downloads:
                return True
        if time.monotonic() >= deadline:
            return False
        try:
            page.wait_for_timeout(step_ms)
        except Exception:  # noqa: BLE001
            return False


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
                    # v0.1.2：不再无条件干等 3s —— 每 250ms 查一次目标是否出现，
                    # 出现立刻走；3s 只是上限（kungal 这种点完不跳转的站照旧吃满）。
                    _wait_reveal(page, site, detail_url, 3000)
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
            card.error = _classify_empty_detail(html_now)
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
        card.error = _classify_empty_detail(html2)
    return card


def normalize_query(query: str | None) -> str:
    """缓存键归一：去首尾空白 + 连续空白压成一个 + 转小写。

    不做去标点/全半角归一：那会让「终焉之莉莉」和「终焉之莉莉！」共用缓存，
    而站点对这两者的检索结果确实可能不同，属于过度合并。
    """
    text = (query or "").strip().lower()
    return re.sub(r"\s+", " ", text)


def _search_in_session(
    sess, site: Site, query: str, timeout: int
) -> GameDetail:
    """在一个已打开的浏览器会话里搜一个站（每站一个新 tab）。"""
    page = None
    try:
        page = sess.new_page()
        return search_one(page, site, query, timeout_ms=timeout)
    finally:
        if page is not None:
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass


def _run_one_site(
    config: dict,
    root: Path,
    site: Site,
    query: str,
    timeout: int,
    store,
    cache_on: bool,
    profile_override: Path | None,
    sess=None,
) -> GameDetail:
    """单站的完整流程（含缓存读写）。供串行与并发两条路径共用。

    profile_override 为 None 时用主 profile（串行路径）；并发时每个 worker
    传自己的目录 —— Chrome 会锁住 user-data-dir，共享目录会有一个失败。

    sess 非空时**复用**这个已打开的会话，不再自己起停浏览器：
    起停一次 Chrome 约 1.4s（实测），14 个站就白花 20 秒。
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

    if sess is not None:
        card = _search_in_session(sess, site, query, timeout)
    else:
        with BrowserSession.for_site(config, root, site,
                                     profile_override=profile_override) as own:
            card = _search_in_session(own, site, query, timeout)
    if cache_on:
        # 失败也写缓存，但 Store 对带 error 的条目用更短的 fail_ttl 过期
        # （默认 30 分钟）——否则重复搜索会被失败站拖慢到和首次一样。
        store.put_cached(key, card)
    return card


def ensure_logged_in(
    config: dict, sites: list[Site], project_root: Path, *, force: bool = False
) -> dict[str, str]:
    """有凭据的站，在**搜索开始之前**先自动登录一次。

    为什么必须在播种 worker profile 之前：并发搜索用的 `chrome-profile-w<N>`
    是从主 profile 复制出来的（`seed_worker_profile`）。如果登录发生在播种
    之后，worker 手里还是旧 Cookie，症状是「登录明明成功了，搜索仍然撞登录墙」
    —— 而且**没有任何报错**，只能靠猜。所以登录放在这里。

    返回 {site_id: 结果说明}，只用于日志与 UI 展示；任何失败都不抛异常，
    失败后该站照常跑搜索，最终报 NEEDS_LOGIN，UI 会退回「手动登录」按钮。
    """
    from . import login as login_mod

    root = Path(project_root)
    creds = login_mod.load_credentials(root)
    if not creds:
        return {}
    out: dict[str, str] = {}
    cfg_login = (config or {}).get("login") or {}
    if cfg_login.get("auto") is False:
        return {}
    for site in sites:
        if not site.needs_login:
            continue
        cred = creds.get(site.id)
        if not cred:
            continue
        if not force and not login_mod.should_refresh(config, root, site):
            out[site.id] = "仍在上次登录的有效期内，跳过"
            continue
        result = login_mod.auto_login(config, root, site, cred)
        out[site.id] = result.message or ("登录成功" if result.ok else "登录失败")
        if result.ok:
            log.info("自动登录成功：%s（%.1fs）", site.id, result.elapsed_s)
        else:
            log.warning("自动登录失败：%s — %s", site.id, result.message)
    return out


def _site_cost_hint(site: Site) -> int:
    """并发派发用的**粗排**：只决定谁先上，不参与任何正确性判断。

    依据 2026-10-23 实测（tools/probe_speed_proxy.json）：form 模式
    （touchgal/anime-sharing/nekogal/sayafx 11–16s）、弹窗收链（galgamex 15s）、
    二次跳转（touchgal）最慢；index / 直链站 3–8s。分数只是序，不是耗时预测。
    """
    s = site.search
    score = 0
    if s.mode == "form":
        score += 10
    if s.download_flow == "popup_redirect":
        score += 8
    elif s.download_flow in ("ggbases", "ankergames", "inarigal"):
        score += 4
    if s.detail_follow_pattern:
        score += 6
    elif s.detail_open_selector:
        score += 3
    if s.mode == "index":
        score -= 2
    return score


def run(
    config: dict,
    sites: list[Site],
    query: str,
    project_root: Path,
    store=None,
    use_cache: bool = True,
    workers: int | None = None,
    profile: Path | str | None = None,
    on_result=None,
) -> list[GameDetail]:
    """对一组站点跑搜索。返回顺序**始终**与传入 sites 一致。

    `on_result(detail)`：每站一有结果就回调（在 worker 线程里），用于 SSE 增量
    推送 —— 用户不用等最慢的站。回调异常一律吞掉，绝不影响搜索本身。

    workers（并发度）：
      - None / 1 → 串行，用主 profile（chrome-profile），行为与旧版一致
      - >1     → 线程池并发，每个 worker 一份独立 profile（chrome-profile-w<N>），
                 启动前从主 profile 播种登录态（实测 0.02s）

    为什么并发必须换 profile：Chrome 会锁住 user-data-dir，实测同一目录并发
    2 个 persistent context 只有 1 个能起来（另一个 TargetClosedError）；
    独立目录 3 个并发全部成功、总耗时 5.3s。

    force_headful 的站永远走串行 headful 会话：它们的用途是让人工过盾，
    并发起来反而互相抢窗口。

    缓存：键是 (归一后的**实际查询词**, site_id)，实际词 = clamp_query 之后的值。
    成功结果缓存 12h；**失败结果缓存 30 分钟**（Store 的 fail_ttl）——
    完全不复用失败会让 6 个坏站每次都把整批拖慢一倍（实测 cold 53.9s→warm 0.5s），
    缓存太久又剥夺用户重试机会。用户可用 UI 的「强制刷新」绕过。

    profile：显式指定用哪个 Chrome profile 目录，并因此**强制串行**。
    用途是让同一台机器上多个 run() 进程互不抢同一个 user-data-dir
    （Chrome 会锁目录，抢到的那个会 TargetClosedError）。清扫脚本靠它并行。
    """
    from .browser import BrowserSession, seed_worker_profile, worker_profile_dir

    root = Path(project_root)
    search_cfg = config.get("search") or {}
    timeout = int(search_cfg.get("timeout_ms") or SEARCH_TIMEOUT)
    cache_on = store is not None and use_cache

    n_workers = int(workers if workers is not None
                    else (search_cfg.get("workers") or 1))
    if profile is not None:
        # 显式 profile 时不能并发：那个目录只允许一个 Chrome 进程。
        n_workers = 1
    n_workers = max(1, min(n_workers, max(1, len(sites))))

    # 自动登录必须在**播种 worker profile 之前**（见 ensure_logged_in 的注释）。
    try:
        ensure_logged_in(config, sites, root)
    except Exception as exc:  # noqa: BLE001 - 登录挂了不能带崩整次搜索
        log.warning("自动登录流程异常：%s: %s", type(exc).__name__, exc)

    headless_idx = [i for i, s in enumerate(sites) if not s.force_headful]
    headful_idx = [i for i, s in enumerate(sites) if s.force_headful]
    results: dict[int, GameDetail] = {}

    def _emit(detail: GameDetail | None) -> None:
        """一有结果就推给调用方（SSE 真流式的关键）。回调炸了不能带崩搜索。"""
        if detail is None or on_result is None:
            return
        try:
            on_result(detail)
        except Exception:  # noqa: BLE001
            pass

    def _safe(idx: int, profile: Path | None, sess=None) -> None:
        site = sites[idx]
        try:
            results[idx] = _run_one_site(
                config, root, site, query, timeout, store, cache_on, profile,
                sess=sess,
            )
        except Exception as exc:  # noqa: BLE001
            results[idx] = GameDetail(
                site_id=site.id, url=site.homepage, title="",
                error=f"{type(exc).__name__}: {str(exc)[:150]}",
            )
        _emit(results[idx])

    # ---- 串行路径（workers=1，行为与旧版一致；显式 profile 也走这里）----
    if n_workers == 1:
        for idx in headless_idx:
            _safe(idx, profile)
        if headful_idx:
            with BrowserSession.for_site(
                config, root, sites[headful_idx[0]], profile_override=profile
            ) as sess:
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
                        _emit(results.get(idx))  # type: ignore[arg-type]
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
    # 每个 worker **独占一个 profile，并在这个线程里自己开、自己关**浏览器。
    #
    # 为什么不能像以前那样「主线程统一关闭」：Playwright 的 sync API 绑定在
    # 创建它的线程上，跨线程 close 会抛 `error cannot switch to a different
    # thread`。异常被吞掉后 Chrome 进程留在原地、profile 目录被锁住，下一次
    # 搜索所有站都 TargetClosedError —— 实测就是这个现象（连做两次搜索，
    # 第二次 16 个站全在 2 秒内失败）。
    #
    # 站点**动态派发**（work-stealing）：以前按 `i % n_workers` 静态分块，
    # 14 站 5 槽时最慢的槽要独自背 3 个慢站，别的槽早空了也帮不上 —— 实测
    # 墙钟被最长槽拖死。改成共享队列后，谁先跑完谁拿下一站。
    # 队列顺序按「预估耗时从高到低」排（`_site_cost_hint`），慢站先派出去，
    # 避免它们最后一刻才开始。这个顺序只影响调度，不参与任何正确性判断。
    work: queue.Queue[int] = queue.Queue()
    for idx in sorted(headless_idx, key=lambda i: _site_cost_hint(sites[i]), reverse=True):
        work.put(idx)

    def _worker(w: int) -> None:
        profile = profiles[w]
        sess = None
        try:
            while True:
                try:
                    idx = work.get_nowait()
                except queue.Empty:
                    return
                try:
                    if sess is None:
                        sess = BrowserSession.for_site(
                            config, root, sites[idx], profile_override=profile
                        ).__enter__()
                    _safe(idx, profile, sess)
                except Exception:  # noqa: BLE001
                    # 浏览器自己挂了（TargetClosedError 之类）：在本线程关掉、
                    # 重开一次重试这个站，否则本线程后面每个站都会连着失败。
                    if sess is not None:
                        try:
                            sess.close()
                        except Exception:  # noqa: BLE001
                            pass
                        sess = None
                    _safe(idx, profile, None)
        finally:
            if sess is not None:
                try:
                    sess.close()
                except Exception:  # noqa: BLE001
                    pass

    threads = [
        threading.Thread(target=_worker, args=(w,), name=f"gf-worker-{w}", daemon=True)
        for w in range(n_workers)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 任何站没留下结果（worker 意外死掉）都要补一张卡，返回值长度永远等于站数。
    for i in range(len(sites)):
        if i not in results:
            results[i] = GameDetail(
                site_id=sites[i].id, url=sites[i].homepage, title="",
                error="WORKER_LOST: no result for this site",
            )
            _emit(results[i])

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
                    _emit(results.get(idx))  # type: ignore[arg-type]

    return [results[i] for i in range(len(sites))]


def resolve_worker_primary(config: dict, root: Path) -> Path:
    """并发 worker 播种的源目录 = 配置里的主 profile。"""
    from .browser import resolve_profile_dir

    b = config.get("browser") or {}
    return resolve_profile_dir(root, b.get("profile_dir", "chrome-profile"))
