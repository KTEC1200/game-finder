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
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from .detail import extract_card
from .models import GameDetail, Site
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
)


def _settle(page, ms: int = SETTLE_MS) -> None:
    """尽量等页面安静下来；networkidle 超时不算错误（很多站有长连接）。"""
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:  # noqa: BLE001
        pass
    try:
        page.wait_for_timeout(ms)
    except Exception:  # noqa: BLE001
        pass


def _visible_text(html: str) -> str:
    """粗抽可见文本（去 script/style/标签），用于「无结果」判定。"""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html or "", flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text)


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
    """识别站点明确的无结果文案；返回命中的特征，没命中返回 None。"""
    blob = f"{title or ''} {_visible_text(html)}".lower()
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


def _goto(page, url: str, timeout: int) -> tuple[int | None, str | None]:
    """导航到 url。返回 (http_status, nav_error)；nav_error 不为 None 时页面可能是残页。"""
    try:
        resp = page.goto(url, timeout=timeout, wait_until="load")
        status = getattr(resp, "status", None) if resp is not None else None
        return status, None
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {str(exc)[:200]}"


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

    if site.search.mode == "url":
        url = build_search_url(site, q)
        status, nav_error = _goto(page, url, timeout_ms)
        _settle(page)
    else:
        status, nav_error = _goto(page, site.homepage, timeout_ms)
        _settle(page)
        sel = (
            site.search.input_selector
            or "input[type=search], input[name*=s], input[type=text]"
        )
        try:
            box = page.locator(sel).first
            box.fill(q, timeout=10000)
            box.press("Enter")
            _settle(page, 3000)
        except Exception as exc:  # noqa: BLE001
            return GameDetail(
                site_id=site.id,
                url=getattr(page, "url", site.homepage),
                title="",
                error=f"FORM_FAILED: {type(exc).__name__}: {str(exc)[:150]}",
                extra=extra,
            )
        status = None

    search_url = page.url
    search_html = page.content()
    search_title = _page_title(page)
    search_block = looks_blocked(search_title, search_html)
    no_results = looks_no_results(search_title, search_html)
    hits = parse_result_links(search_html, search_url, site)
    best = pick_best(hits, q)

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
    if no_results:
        extra["no_results_marker"] = no_results
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

    d_status, d_nav_error = _goto(page, best.url, timeout_ms)
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
    if not card.downloads:
        # gamer520 实测：详情页本身不含网盘链接，只有一个 /go?post_id=<id> 跳板。
        # 不自动跟进：实测该跳板会把 post 带到 520.gamers520.com/<n>.html，
        # 而落地页标题与 post 对不上（可能按登录态/推荐位分流），
        # 自动跟进有把「别的游戏」的网盘链接挂到本结果上的风险。只记录证据。
        card.extra["gate_links"] = _find_gate_links(detail_html, detail_url)
        card.error = "NO_DOWNLOADS"
    return card


def run(
    config: dict,
    sites: list[Site],
    query: str,
    project_root: Path,
) -> list[GameDetail]:
    """对一组站点串行跑（同站串行、跨站并行留给 server 层做）。

    按 site.force_headful 分组：普通站共用一个 headless 会话，需要人工过盾的站
    共用一个 headful 会话。这样 force_headful 真正生效，又不用每站重启浏览器。
    返回顺序与传入 sites 一致。
    """
    from .browser import BrowserSession

    root = Path(project_root)
    timeout = int((config.get("search") or {}).get("timeout_ms") or SEARCH_TIMEOUT)
    results: dict[int, GameDetail] = {}

    groups: dict[bool, list[tuple[int, Site]]] = {}
    for idx, site in enumerate(sites):
        groups.setdefault(bool(site.force_headful), []).append((idx, site))

    for headful in (False, True):
        batch = groups.get(headful) or []
        if not batch:
            continue
        # for_site 只读 site.force_headful，用组里任意一站代表整组
        representative = batch[0][1]
        with BrowserSession.for_site(config, root, representative) as sess:
            for idx, site in batch:
                page = None
                try:
                    page = sess.new_page()
                    results[idx] = search_one(page, site, query, timeout_ms=timeout)
                except Exception as exc:  # noqa: BLE001
                    results[idx] = GameDetail(
                        site_id=site.id,
                        url=site.homepage,
                        title="",
                        error=f"{type(exc).__name__}: {str(exc)[:150]}",
                    )
                finally:
                    if page is not None:
                        try:
                            page.close()
                        except Exception:  # noqa: BLE001
                            pass

    return [results[i] for i in range(len(sites))]
