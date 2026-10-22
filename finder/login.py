"""「打开浏览器手动登录」——把登录态灌进程序自己的专用 profile。

## 为什么需要这个

程序用的是**专用** profile（`chrome-profile`），不是用户日常那个 Chrome 的
user-data-dir（Chrome 136+ 禁止对默认目录开放 DevTools，实测 Playwright 直接
报 `browser.profile_dir must not be Chrome's default user-data-dir`）。
所以用户在**自己 Chrome** 里登录过，程序一点也用不到。

唯一可靠的办法是：**用程序自己的 profile 开一个有头浏览器**，让用户在里面
登录一次。登录态（Cookie / Local Storage）就落在 profile 目录里，之后无头
搜索自然带着它。

## 实测约束（2026-10-22，galgame.dev）

* 该站 `/search?term=...` 未登录 → 302 到 `/login`；`/api/search` → 401
  `{"status":{"code":"not-authorised", ...}}`
* 登录成功后 `/login` 会跳回首页或来源页，页面出现「退出」/头像
* 用有头 + 真实 Chrome 可以正常登录；**不要**用 Playwright 自带 Chromium
  （过不了该站 Cloudflare 挑战，见 browser.py 的注释）

## 并发约束

profile 是独占资源：Chrome 会锁住 user-data-dir。所以登录窗口必须在**没有
搜索在跑**的时候开，且登录期间不能有任何搜索进程用同一个 profile。
`LoginSession` 因此只做「开窗口 → 等用户 → 关窗口」这一件事，不参与搜索。
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .models import Site

log = logging.getLogger("gamefinder.login")

# 登录成功判据：落地 URL 不再是登录页。只认路径，不扫正文 ——
# 页面导航里到处都有「登录」二字，扫 HTML 必然误判。
LOGIN_PATH_RE = re.compile(
    r"/(?:login|log-in|signin|sign-in|sign_in|auth|account/login)(?:[/?#]|$)",
    re.I,
)

# 轮询间隔与上限：用户点完登录到 Cookie 生效通常 < 2s，
# 但有人会先注册再登录，给足 10 分钟。
POLL_MS = 1000
TIMEOUT_S = 600

# 登录后才出现的文案（galgame.dev 实测页脚是「退出」，英文站多为 Sign out）。
# 顺序无关，任一命中即算已登录。
LOGGED_IN_MARKERS = (
    "退出", "登出", "我的帐号", "我的账号", "个人中心",
    "Sign out", "Log out", "My account",
)

# 同一时刻只允许一个登录窗口（profile 独占）。
_LOCK = threading.Lock()


def is_login_path(url: str) -> bool:
    """落地 URL 是不是登录页。"""
    from urllib.parse import urlparse

    return bool(LOGIN_PATH_RE.search(urlparse(url or "").path or ""))


def login_url_for(site: Site) -> str | None:
    """该站的登录页地址；不需要登录的站返回 None。"""
    if not site.needs_login:
        return None
    if site.login_url:
        return site.login_url
    return site.homepage.rstrip("/") + "/login"


def looks_logged_in(
    url: str, title: str = "", text: str = "", success_pattern: str | None = None,
) -> bool:
    """登录态判据：不在登录页 **且** 页面能看出已登录。

    两个条件都要满足：
      * 落地 URL 不是登录页（否则用户只是还没点登录）
      * 正文里出现「退出」/「登出」/ 用户名等登录后才有的东西

    只判 URL 不够：galgame.dev 的 `/` 未登录也能打开，只看 URL 会误报成功。

    `success_pattern` 给了就用它（站点自己的判据，正则），否则用通用文案表。
    """
    if is_login_path(url):
        return False
    blob = f"{title}\n{text}"
    if success_pattern:
        try:
            return bool(re.search(success_pattern, blob, re.I))
        except re.error:
            pass  # 配置写错就退回通用判据，不能让正则把功能卡死
    return any(m in blob for m in LOGGED_IN_MARKERS)


@dataclass
class LoginResult:
    """一次登录尝试的结果。`ok` 为 True 表示 profile 里已经有登录态。"""

    ok: bool
    site_id: str
    url: str = ""
    message: str = ""
    elapsed_s: float = 0.0
    # 用户中途关掉窗口（不是失败，只是没登完）
    cancelled: bool = False


@dataclass
class LoginSession:
    """开一个**有头**浏览器让用户登录，轮询到登录成功或超时。

    用法：
        with LoginSession(config, root, site) as s:
            result = s.wait_for_login()

    超时不会报错，返回 ok=False；UI 据此提示「可以再点一次」。
    """

    config: dict[str, Any]
    project_root: Path
    site: Site
    timeout_s: int = TIMEOUT_S
    poll_ms: int = POLL_MS
    # 便于测试注入（默认用真实 BrowserSession）
    session_factory: Callable[..., Any] | None = None
    _sess: Any = field(default=None, init=False, repr=False)
    _page: Any = field(default=None, init=False, repr=False)

    def __enter__(self) -> "LoginSession":
        if not _LOCK.acquire(blocking=False):
            raise RuntimeError(
                "已经有一个登录窗口开着。请先在那边登录完（或关掉它）再试。"
            )
        try:
            self._sess = self._open()
        except BaseException:
            _LOCK.release()
            raise
        return self

    def __exit__(self, *exc) -> None:
        try:
            if self._sess is not None:
                self._sess.close()
        finally:
            self._sess = None
            _LOCK.release()

    # -- 内部 ---------------------------------------------------------------

    @property
    def page(self):
        """当前登录窗口的页面（`__enter__` 之后才有；验收脚本用它看落地页）。"""
        return self._page

    def _open(self):
        """用主 profile 开有头浏览器，直接落到登录页。"""
        from .browser import BrowserSession

        factory = self.session_factory or BrowserSession
        # headful_override=True：登录必须看得见窗口，headless 下用户没法操作。
        sess = factory(
            self.config, Path(self.project_root), headful_override=True
        ).__enter__()
        try:
            page = sess.new_page()
            url = login_url_for(self.site) or self.site.homepage
            page.goto(url, timeout=45000, wait_until="domcontentloaded")
            self._page = page
        except BaseException:
            sess.close()
            raise
        return sess

    def wait_for_login(self) -> LoginResult:
        """阻塞直到登录成功 / 超时 / 用户关掉窗口。"""
        started = time.monotonic()
        page = self._page
        deadline = started + self.timeout_s
        while True:
            elapsed = time.monotonic() - started
            try:
                url = page.url
                title = page.title() or ""
                text = page.evaluate(
                    "() => document.body ? document.body.innerText : ''"
                ) or ""
            except Exception as exc:  # noqa: BLE001 - 用户关窗口是正常路径
                return LoginResult(
                    ok=False, site_id=self.site.id, cancelled=True,
                    message=f"登录窗口已关闭（{type(exc).__name__}）",
                    elapsed_s=round(elapsed, 1),
                )
            if looks_logged_in(url, title, text, self.site.login_success_pattern):
                return LoginResult(
                    ok=True, site_id=self.site.id, url=url,
                    message="登录成功，登录态已保存",
                    elapsed_s=round(elapsed, 1),
                )
            if time.monotonic() >= deadline:
                return LoginResult(
                    ok=False, site_id=self.site.id, url=url,
                    message=f"等了 {self.timeout_s} 秒仍未检测到登录，可以再点一次",
                    elapsed_s=round(elapsed, 1),
                )
            page.wait_for_timeout(self.poll_ms)


def login_state(config: dict[str, Any], project_root: Path, site: Site) -> dict:
    """只读检查：profile 里现在能不能用该站（不发搜索，只看 Cookie 目录）。

    返回值给 UI 用，`logged_in` 是**保守**判断：
      * profile 目录不存在 → False（还没跑过）
      * Cookie 文件里没有该站域名的条目 → False
      * 有条目 → True（但 Cookie 可能已过期，真正的判据是搜索能不能过登录墙）
    """
    from .browser import resolve_profile_dir

    b = config.get("browser") or {}
    try:
        profile = resolve_profile_dir(project_root, b.get("profile_dir", "chrome-profile"))
    except (ValueError, OSError):
        return {"site_id": site.id, "logged_in": False, "reason": "profile 不可用"}

    cookie_db = profile / "Default" / "Network" / "Cookies"
    if not cookie_db.exists():
        cookie_db = profile / "Default" / "Cookies"
    if not cookie_db.exists():
        return {"site_id": site.id, "logged_in": False, "reason": "profile 里还没有 Cookie"}

    from urllib.parse import urlparse

    host = (urlparse(site.homepage).hostname or "").lower()
    if not host:
        return {"site_id": site.id, "logged_in": False, "reason": "站点域名解析失败"}
    # 主域 + 各级父域（galgame.dev 也可能存在 .galgame.dev 的 cookie）
    hosts = [host] + ["." + host]
    parts = host.split(".")
    for i in range(1, len(parts) - 1):
        parent = ".".join(parts[i:])
        hosts.extend([parent, "." + parent])

    try:
        import sqlite3

        con = sqlite3.connect(f"file:{cookie_db}?mode=ro", uri=True, timeout=2)
        try:
            rows = con.execute(
                "SELECT DISTINCT host_key FROM cookies"
            ).fetchall()
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001 - 只读探测，失败就当没有
        return {"site_id": site.id, "logged_in": False,
                "reason": f"读不到 Cookie（{type(exc).__name__}）"}

    known = {str(r[0] or "").lower() for r in rows}
    matched = sorted(h for h in known if h in hosts)
    return {
        "site_id": site.id,
        "logged_in": bool(matched),
        "hosts": matched,
        "reason": "profile 里已有该站 Cookie" if matched else "profile 里没有该站 Cookie",
    }
