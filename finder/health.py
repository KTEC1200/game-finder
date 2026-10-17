"""可用性巡检状态机。

判定口径（用户 2026-10-17 基于 12 站真实冒烟数据确认）：
  巡检要回答的是「**这个站还活着吗**」，而不是「站里有没有这个游戏」。
  两者必须分开，否则会把「站活着、只是没收录探测词」误报成站点故障。

状态（classify 的全部返回值）：
  ok               HTTP 200 + 页面能开 + 抽到 >=1 条结果链接（站内搜索可用）
  ok_no_hits       HTTP 200 + 页面能开，但站内搜索对这个探测词没有结果：
                   页面上有明确的无结果文案（WordPress "Nothing Found"、
                   未找到相关…），且没有详情形状的链接。**站是活的**，只是没这个游戏。
                   实测样例：flysheep 对不存在的游戏返回这种页面。
  degraded         HTTP 200 + 页面能开 + 没有结果且**没有**任何无结果文案
                   → 搜索可能坏了（选择器失效 / 前端报错 / 结果区被改版）。
                   form 模式填不进搜索框（FORM_FAILED）也归这类：站活着但搜索不可用。
  cloudflare_block 命中 Cloudflare 拦截页特征（强文案 / cf-error / 无结果页的 CF 弱特征）
  needs_login      0 结果且页面要求登录（登录态失效，登录一次即可恢复）
  unreachable      导航失败（status_code is None）或 HTTP >= 400

判定优先级（顺序即语义，改动前先想清楚为什么）：
  1. Cloudflare **强**文案特征 —— 拦截页也可能回 200，其内容毫无意义，必须先判。
  2. 导航失败 / HTTP >= 400 —— 连页面都没拿到，其余信号不可信。
  3. 有链接：默认 ok。但若站点**明确**说「没有找到」且命中的全是噪声链接
     （没有一条详情形状），判 ok_no_hits —— 页脚/导航链接不是搜索结果。
  4. 0 链接：登录提示（更可操作的诊断）→ 无结果文案 → Cloudflare 错误页标记 /
     弱特征 → degraded。
     顺序关键：无结果文案必须**先于**裸 "cloudflare" 字样，否则 Cloudflare 托管
     的站点（如 flysheep）出 "Nothing Found" 页会被误报成被拦截。

标记扫描只在**可见文本**（去掉 script/style）里做：Cloudflare 的
`cloudflareinsights.com/beacon.js`、`/cdn-cgi/challenge-platform/...` 脚本会被
**正常**站点（含 gamer520，实测）引用，扫原始 HTML 会把健康站判成
cloudflare_block。仅 `cf-error*` 这类错误页标记额外扫原始 HTML。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from .models import HealthRecord, Site
from .search import build_search_url, clamp_query, parse_result_links

# Cloudflare 拦截页的**强**特征：出现即判拦截，与结果数无关
CLOUDFLARE_MARKERS = (
    "attention required",
    "just a moment",
    "checking your browser",
    "verify you are human",
    "enable javascript and cookies to continue",
)
# Cloudflare **错误页**专属的 HTML 结构标记。
# 实测反例（tests/fixtures/gamer520/search_ai.html，31 条结果）：gamer520 本身就是
# Cloudflare 托管站，**正常**页面也会注入 /cdn-cgi/challenge-platform/scripts/jsd/main.js。
# 所以 challenge-platform / cf-challenge / cf-browser-verification 一律不能当证据；
# 只认 cf-error 这类错误页标记，且必须结合「0 结果」来判断。
CLOUDFLARE_HTML_MARKERS = (
    "cf-error-details",
    "cf-error",
)
# **弱**特征：正常站点也可能在页脚写 "Performance & security by Cloudflare"，
# 所以只在 0 结果时才用作证据，不能覆盖「有结果」这一事实。
CLOUDFLARE_WEAK_MARKER = "cloudflare"

LOGIN_MARKERS = (
    "请先登录",
    "请登录",
    "需要登录",
    "登录后查看",
    "登录后可见",
    "sign in to continue",
    "log in to continue",
    "login required",
    "please sign in",
)

# 站点明确表达「没有结果」——站活着，只是没收录。与 pipeline.NO_RESULTS_MARKERS 同源。
NO_RESULTS_MARKERS = (
    "nothing found",
    "nothing matched your search",
    "no results",
    "no results found",
    "sorry, but nothing matched",
    "抱歉，没有找到",
    "没有找到相关",
    "没有搜索到",
    "未找到相关",
    "找不到相关",
    "无搜索结果",
    "検索結果がありません",
    "該当する結果がありません",
)

# form 模式在没配 input_selector 时的回退选择器（与 pipeline 一致）
FORM_FALLBACK_SELECTOR = "input[type=search], input[name*=s], input[type=text]"
# 搜索框交互的默认超时：比导航短，避免一个坏站拖住整轮巡检
FORM_TIMEOUT_MS = 10000


def _visible_text(html: str) -> str:
    """粗抽可见文本（去 script/style/标签）。标记判定都基于它，避免脚本误报。"""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html or "", flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).lower()


def _find_marker(text: str, markers: tuple[str, ...]) -> str | None:
    """返回第一个命中的标记（标记本身），未命中返回 None。"""
    for marker in markers:
        if marker in text:
            return marker
    return None


def probe_word_for(site: Site, probe_words: dict[str, str]) -> str:
    """按站点声明的语种，优先 zh → en → ja 取探测词。

    探测词必须在该站确实有结果（zh=终焉之莉莉 / en=enderlilies / ja=制服カノジョ），
    这样「0 结果」才有诊断意义，顺带也验证了语种路由。
    """
    for lang in ("zh", "en", "ja"):
        if lang in site.langs and probe_words.get(lang):
            return probe_words[lang]
    return next(iter(probe_words.values()), "game")


def classify(
    status_code: int | None,
    body: str,
    hits: int,
    detail_hits: int | None = None,
) -> str:
    """把一次探测归类为状态机的一个状态。纯函数，无副作用。

    detail_hits：形状像详情页的链接数（parse_result_links 里 score>=1.0），
    默认 None 表示「未知，按 hits 处理」。之所以需要它：实测 flysheep 的
    "Nothing Found" 页仍能抽出 2 条页脚/导航链接（score=0.5），只看 hits>0
    会把「站活着但没收录」误报成 ok。真实结果页（gamer520 / jidiyouxi
    fixture）里没有任何无结果文案，所以「有明确无结果文案 + 命中全是噪音」
    判 ok_no_hits 是安全的。
    """
    raw = (body or "").lower()
    visible = _visible_text(body)
    detail = hits if detail_hits is None else detail_hits

    # 1. 拦截页的强文案：拦截页也可能回 200 并带导航链接，必须先判
    if _find_marker(visible, CLOUDFLARE_MARKERS):
        return "cloudflare_block"
    # 2. 页面都没拿到 → 其余信号不可信
    if status_code is None:
        return "unreachable"
    # 3. HTTP 错误页
    if status_code >= 400:
        return "unreachable"

    no_results = _find_marker(visible, NO_RESULTS_MARKERS)
    login = _find_marker(visible, LOGIN_MARKERS)

    # 4. 有链接：真详情链接（或无法区分形状时）就是 ok；但若站点明确说「没有找到」
    #    且命中的全是噪声链接，则站活着但没这个游戏。
    if hits > 0:
        if no_results and detail == 0:
            return "ok_no_hits"
        return "ok"
    # 5. 0 结果：登录墙是更可操作的诊断，优先于「没找到」
    if login:
        return "needs_login"
    # 6. 站明确说「没有找到」→ 站活着，只是没这个游戏。
    #    这一条必须排在弱特征 "cloudflare" 之前：flysheep 这类站既是 Cloudflare
    #    托管（页脚带字样）又会出 "Nothing Found" 页，反序会把「没这个游戏」
    #    误报成「被 Cloudflare 拦」——正是本次要避免的误判。
    if no_results:
        return "ok_no_hits"
    # 7. 0 结果 + Cloudflare 错误页标记 / 只剩 "cloudflare" 字样 → 视作挑战页
    if _find_marker(raw, CLOUDFLARE_HTML_MARKERS) or CLOUDFLARE_WEAK_MARKER in visible:
        return "cloudflare_block"
    # 8. 0 链接且无任何解释 → 搜索可能坏了
    return "degraded"


def _now_ms(started: datetime) -> int:
    return int((datetime.now(timezone.utc) - started).total_seconds() * 1000)


def _settle(page, budget_ms: int = 8000) -> None:
    """尽量等页面安静下来；networkidle 超时不算失败（很多站有长连接）。"""
    try:
        page.wait_for_load_state("networkidle", timeout=budget_ms)
    except Exception:  # noqa: BLE001
        pass


def check_site(
    page,
    site: Site,
    probe_words: dict[str, str],
    timeout_ms: int = 45000,
) -> HealthRecord:
    """对单站跑一次真实搜索探测，返回 HealthRecord。**绝不抛异常。**

    page 由调用方提供（运行中的浏览器），本函数不负责启动/关闭浏览器。

    失败一律落成 HealthRecord：
      - 导航失败 → unreachable（reason 带原始异常）
      - form 模式填不进搜索框 → degraded（reason 前缀 FORM_FAILED，实测有站点
        的搜索框匹配不到 `input[type=search], input[type=text]`，fill 会超时）
    任何未预期的异常也只会变成 degraded，不会让整轮巡检中断。
    """
    word = probe_word_for(site, probe_words)
    started = datetime.now(timezone.utc)
    status_code: int | None = None
    body = ""
    hits = 0
    error = ""

    try:
        if site.search.mode == "url":
            q, _ = clamp_query(site, word)
            url = build_search_url(site, q)
            resp = page.goto(url, timeout=timeout_ms, wait_until="load")
            status_code = getattr(resp, "status", None) if resp is not None else None
        else:
            home_resp = page.goto(site.homepage, timeout=timeout_ms, wait_until="load")
            home_status = getattr(home_resp, "status", None) if home_resp is not None else None
            if home_status is not None and home_status >= 400:
                # 首页都打不开（404/503）→ 站点不可达，别再折腾搜索框
                return HealthRecord(
                    site_id=site.id, status="unreachable",
                    latency_ms=_now_ms(started),
                    reason=f"homepage_http_{home_status}",
                    checked_at=started.isoformat(),
                )
            page.wait_for_timeout(2000)
            selector = site.search.input_selector or FORM_FALLBACK_SELECTOR
            try:
                box = page.locator(selector).first
                box.fill(word, timeout=FORM_TIMEOUT_MS)
                box.press("Enter", timeout=FORM_TIMEOUT_MS)
            except Exception as exc:  # noqa: BLE001
                # 站活着，但搜索框用不了 → 搜索降级，不是站点不可达
                return HealthRecord(
                    site_id=site.id, status="degraded",
                    latency_ms=_now_ms(started),
                    reason=f"FORM_FAILED: {type(exc).__name__}: {str(exc)[:120]}",
                    checked_at=started.isoformat(),
                )
            page.wait_for_timeout(3000)
            # form 模式拿不到导航响应对象；没抛异常就按成功计
            status_code = 200

        _settle(page)
        body = page.content()
        parsed = parse_result_links(body, page.url, site)
        hits = len(parsed)
        # 详情形状（score>=1.0）的链接才算「真结果」：页脚/导航链接是 0.5 分，
        # flysheep 的 "Nothing Found" 页正是靠这 2 条 0.5 分链接伪装成「有结果」。
        detail_hits = sum(1 for h in parsed if h.score >= 1.0)
    except Exception as exc:  # noqa: BLE001
        # page.content() 也可能炸；此处只记录，不重抛
        error = f"{type(exc).__name__}: {str(exc)[:120]}"
        detail_hits = None

    status = classify(status_code, body, hits, detail_hits)
    if error and status == "ok":
        # 拿到了结果却又出错（例如 content 读取失败），不当成功
        status = "degraded"
    detail = error or f"hits={hits}"
    if status == "ok_no_hits":
        # 把命中的无结果标记写进 reason，健康面板上能直接看出「站活着但没收录」。
        # 同时记录真实链接数：噪声链接（页脚/导航）常常不为 0，写成 hits=0 会误导。
        marker = _find_marker(_visible_text(body), NO_RESULTS_MARKERS)
        if marker:
            detail = f"hits={hits} no_results={marker}"
    return HealthRecord(
        site_id=site.id,
        status=status,
        latency_ms=_now_ms(started),
        reason=detail,
        checked_at=started.isoformat(),
    )
