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

# 登录页判据只看**路径**：页面导航里到处都有「登录」二字，扫正文必然误判。
# （真正的登录成功判据在 looks_logged_in：路径 + 正文双条件。）
LOGIN_PATH_RE = re.compile(
    r"/(?:login|log-in|signin|sign-in|sign_in|auth|account/login)(?:[/?#]|$)",
    re.I,
)

# 轮询间隔与上限：用户点完登录到 Cookie 生效通常 < 2s，
# 但有人会先注册再登录，给足 10 分钟。
# 可在 config.yaml 的 login.timeout_s / login.poll_ms 覆盖（打包验收要用短超时）。
POLL_MS = 1000
TIMEOUT_S = 600

# 登录后才出现的文案（galgame.dev 实测页脚是「退出」，英文站多为 Sign out）。
# 顺序无关，任一命中即算已登录。
LOGGED_IN_MARKERS = (
    "退出", "登出", "我的帐号", "我的账号", "个人中心",
    "Sign out", "Log out", "My account",
)

# 本地凭据文件（**永不进仓库**，见 .gitignore 与 build_portable.py 的排除表）。
CREDENTIALS_FILE = "credentials.yaml"

# 自动登录的缺省超时：程序自己填表比人快，20 秒足够；卡住就放弃、退回人工。
AUTO_TIMEOUT_S = 20

# 表单选择器：先试站点配置，再按常见形状兜底。
USERNAME_SELECTORS = (
    "#username", "input[name=username]", "input[name=email]",
    "input[type=email]", "input[autocomplete=nickname]",
    "input[autocomplete=username]",
)
PASSWORD_SELECTORS = ("input[type=password]",)
SUBMIT_TEXTS = ("登录", "登入", "登陆", "login", "log in", "sign in", "signin")

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


def _snapshot(page) -> tuple[str, str, str]:
    """(url, title, blob)。blob = 标题 + 正文 + body 的 class。

    为什么要带上 class：NodeBB（galgame.dev）登录后页面上**没有**「退出」这类
    正文文案（它们藏在折叠的账号菜单里，`innerText` 取不到），但它会给 body
    加 `user-loggedin` 类。只扫正文会把「已经登录成功」判成没登进去 ——
    v0.1.1 的人工登录窗口就是这么一直等到超时的。
    """
    url = page.url
    title = page.title() or ""
    text = page.evaluate(
        "() => document.body ? document.body.innerText : ''"
    ) or ""
    try:
        cls = page.evaluate(
            "() => document.body ? document.body.className : ''"
        ) or ""
    except Exception:  # noqa: BLE001 - 取不到 class 不影响主判据
        cls = ""
    return url, title, f"{title}\n{text}\n{cls}"


def _poll_state(page):
    """读一次页面状态：(state, url, title, blob)，state ∈ {"ok","closed"}。

    **页面跳转的那一瞬间 `page.evaluate` 会抛 Error**（execution context was
    destroyed / navigation）。第一版把所有异常都当成「用户关了窗口」，
    于是登录刚提交、页面正在跳转时就报 `登录窗口已关闭（Error）` 直接放弃 ——
    实测踩过。真正的关窗判据只有 `page.is_closed()`。
    """
    for attempt in range(3):
        checker = getattr(page, "is_closed", None)
        if callable(checker):
            try:
                if checker():
                    return "closed", "", "", ""
            except Exception:  # noqa: BLE001
                return "closed", "", "", ""
        try:
            url, title, blob = _snapshot(page)
            return "ok", url, title, blob
        except Exception:  # noqa: BLE001 - 多半是正在跳转，稍等再读
            try:
                page.wait_for_timeout(250)
            except Exception:  # noqa: BLE001
                return "closed", "", "", ""
    return "closed", "", "", ""


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
    # None = 用 config.yaml 的 login.timeout_s / login.poll_ms，缺省 600s / 1000ms
    timeout_s: int | None = None
    poll_ms: int | None = None
    # 便于测试注入（默认用真实 BrowserSession）
    session_factory: Callable[..., Any] | None = None
    _sess: Any = field(default=None, init=False, repr=False)
    _page: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        cfg = (self.config or {}).get("login") or {}
        if self.timeout_s is None:
            try:
                self.timeout_s = int(cfg.get("timeout_s") or TIMEOUT_S)
            except (TypeError, ValueError):
                self.timeout_s = TIMEOUT_S
        if self.poll_ms is None:
            try:
                self.poll_ms = int(cfg.get("poll_ms") or POLL_MS)
            except (TypeError, ValueError):
                self.poll_ms = POLL_MS

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
            state, url, title, blob = _poll_state(page)
            if state == "closed":  # 用户关窗口是正常路径，不是错误
                return LoginResult(
                    ok=False, site_id=self.site.id, cancelled=True,
                    message="登录窗口已关闭",
                    elapsed_s=round(elapsed, 1),
                )
            if looks_logged_in(url, title, blob, self.site.login_success_pattern):
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

    def cookie_snapshot(self) -> dict:
        """关窗后确认登录态真的落盘了。

        为什么需要：`wait_for_login` 的判据是**页面**看起来已登录，
        而 Cookie 要等 Chrome 异步刷盘。用户登完立刻关窗口时，
        页面已经显示「退出」但磁盘上可能还没有 —— 这时重搜仍是登录墙，
        用户会以为功能坏了。这里主动问一次浏览器，并把 Cookie 写盘。
        """
        if self._sess is None:
            return {"ok": False, "reason": "窗口已关闭"}
        try:
            cookies = self._sess.context.cookies()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reason": f"{type(exc).__name__}: {str(exc)[:120]}"}
        host = ""
        from urllib.parse import urlparse

        try:
            host = (urlparse(self.site.homepage).hostname or "").lower()
        except ValueError:
            host = ""
        mine = [c for c in (cookies or []) if host and host in (c.get("domain") or "")]
        return {"ok": True, "count": len(mine),
                "names": sorted({c.get("name", "") for c in mine})[:8]}


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


# ---------------------------------------------------------------------------
# 自动登录（用本地凭据文件填表，不需要人操作）
#
# 凭据放在 exe / 项目根目录的 credentials.yaml，**永不进仓库、永不进发布包**：
#
#   sites:
#     galgame.dev:
#       username: "someone@example.com"
#       password: "..."
#
# 为什么单独一个文件、不写进 config.yaml：config.yaml 是**跟踪进 git** 的，
# 而且是发布包里给所有人看的模板。把它写成凭据就会跟着推上去。
# ---------------------------------------------------------------------------


def credentials_path(project_root: Path) -> Path:
    return Path(project_root) / CREDENTIALS_FILE


def load_credentials(project_root: Path) -> dict[str, dict]:
    """读 credentials.yaml。没有 / 读坏了都返回 {}（自动登录直接不可用）。"""
    path = credentials_path(project_root)
    if not path.exists():
        return {}
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001 - 配置写坏不能把搜索搞崩
        log.warning("credentials.yaml 读不出来，自动登录停用：%s", exc)
        return {}
    sites = data.get("sites") if isinstance(data, dict) else None
    if not isinstance(sites, dict):
        return {}
    out: dict[str, dict] = {}
    for site_id, entry in sites.items():
        if not isinstance(entry, dict):
            continue
        user = str(entry.get("username") or "").strip()
        pwd = str(entry.get("password") or "")
        if user and pwd:
            out[str(site_id)] = {"username": user, "password": pwd}
    return out


def credentials_for(project_root: Path, site: Site) -> dict | None:
    """该站的凭据；没有就 None。"""
    return load_credentials(project_root).get(site.id)


def _state_path(project_root: Path) -> Path:
    return Path(project_root) / "data" / "login-state.json"


def mark_logged_in(project_root: Path, site_id: str) -> None:
    """记下「这个站刚刚登录成功」，用于避免每次搜索都重新登录。"""
    import json
    import time

    path = _state_path(project_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8")) or {}
        data[str(site_id)] = {"at": time.time()}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - 记不下来只影响节流，不影响登录
        log.debug("写 login-state.json 失败：%s", exc)


def last_login_at(project_root: Path, site_id: str) -> float | None:
    import json

    path = _state_path(project_root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8")) or {}
        at = (data.get(str(site_id)) or {}).get("at")
        return float(at) if at else None
    except Exception:  # noqa: BLE001
        return None


def should_refresh(
    config: dict[str, Any], project_root: Path, site: Site, *, force: bool = False
) -> bool:
    """是否值得再跑一次自动登录。

    Cookie 里有条目 ≠ 还有效（实测：galgame.dev 的 express.sid 早就过期了，
    但 `login_state` 只看「有没有条目」→ 报已登录 → 搜索仍然撞墙）。
    所以不能只看 Cookie，还要看**上次成功登录是什么时候**。
    """
    if force:
        return True
    cfg = (config or {}).get("login") or {}
    try:
        hours = float(cfg.get("refresh_hours") or 12)
    except (TypeError, ValueError):
        hours = 12.0
    at = last_login_at(project_root, site.id)
    if at is None:
        return True
    import time

    return (time.time() - at) > hours * 3600


def _visible(page, selector: str):
    """选择器下第一个可见元素；没有就 None。"""
    try:
        loc = page.locator(selector).first
        if loc.count() == 0:
            return None
        if not loc.is_visible(timeout=1000):
            return None
        return loc
    except Exception:  # noqa: BLE001 - 选择器打空是正常情况
        return None


def _first_fillable(page, selectors: tuple[str, ...]):
    for sel in selectors:
        loc = _visible(page, sel)
        if loc is not None:
            return loc
    return None


def _click_submit(page) -> bool:
    """点「登录」按钮。返回是否点到。

    先按文案找（多语言），再退回第一个可见的 submit —— 有些主题按钮里
    只有图标没有文字。最后退回在密码框上按回车。
    """
    script = """(texts) => {
      const cands = Array.from(document.querySelectorAll(
        'button[type=submit], input[type=submit], button'));
      const norm = s => (s || '').trim().toLowerCase();
      let hit = cands.find(b => texts.includes(norm(b.innerText || b.value)));
      if (!hit) hit = cands.find(b => b.type === 'submit' &&
                                 !!(b.offsetWidth || b.offsetHeight));
      if (!hit) return false;
      hit.click();
      return true;
    }"""
    try:
        if page.evaluate(script, list(SUBMIT_TEXTS)):
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        loc = _visible(page, "input[type=password]")
        if loc is not None:
            loc.press("Enter")
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def auto_login(
    config: dict[str, Any],
    project_root: Path,
    site: Site,
    credentials: dict,
    *,
    timeout_s: int | None = None,
    session_factory: Callable[..., Any] | None = None,
) -> LoginResult:
    """用账号密码自动登录一次（无头，不开窗口）。登录态落在主 profile 里。

    失败不会抛异常，返回 ok=False 的 LoginResult —— 调用方据此退回
    「打开浏览器手动登录」那条路，绝不能因为自动登录挂了就让整站失败。
    """
    started = time.monotonic()
    page_obj = Path(project_root)
    cfg = (config or {}).get("login") or {}
    if timeout_s is None:
        try:
            timeout_s = int(cfg.get("auto_timeout_s") or AUTO_TIMEOUT_S)
        except (TypeError, ValueError):
            timeout_s = AUTO_TIMEOUT_S
    deadline = time.monotonic() + timeout_s

    from .browser import BrowserSession

    factory = session_factory or BrowserSession
    try:
        sess = factory(config, page_obj).__enter__()
    except Exception as exc:  # noqa: BLE001
        return LoginResult(ok=False, site_id=site.id,
                           message=f"打不开浏览器：{type(exc).__name__}: {str(exc)[:120]}",
                           elapsed_s=round(time.monotonic() - started, 1))
    try:
        page = sess.new_page()
        url = login_url_for(site) or site.homepage
        page.goto(url, timeout=45000, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)

        # 已经是登录态就别再提交表单（重复登录会踢掉会话，也可能触发风控）
        cur_url, cur_title, cur_blob = _snapshot(page)
        if looks_logged_in(cur_url, cur_title, cur_blob, site.login_success_pattern):
            mark_logged_in(page_obj, site.id)
            return LoginResult(ok=True, site_id=site.id, url=cur_url,
                               message="本来就是登录状态",
                               elapsed_s=round(time.monotonic() - started, 1))

        pwd = _first_fillable(page, PASSWORD_SELECTORS)
        user = _first_fillable(page, USERNAME_SELECTORS)
        if pwd is None or user is None:
            return LoginResult(ok=False, site_id=site.id, url=cur_url,
                               message="登录页上找不到账号/密码输入框",
                               elapsed_s=round(time.monotonic() - started, 1))
        user.fill(credentials["username"])
        pwd.fill(credentials["password"])
        if not _click_submit(page):
            return LoginResult(ok=False, site_id=site.id, url=cur_url,
                               message="登录页上找不到提交按钮",
                               elapsed_s=round(time.monotonic() - started, 1))

        prev_err = ""
        while time.monotonic() < deadline:
            page.wait_for_timeout(700)
            state2, url2, title2, blob2 = _poll_state(page)
            if state2 == "closed":
                return LoginResult(ok=False, site_id=site.id, cancelled=True,
                                   message="登录窗口已关闭",
                                   elapsed_s=round(time.monotonic() - started, 1))
            if looks_logged_in(url2, title2, blob2, site.login_success_pattern):
                mark_logged_in(page_obj, site.id)
                return LoginResult(ok=True, site_id=site.id, url=url2,
                                   message="登录成功",
                                   elapsed_s=round(time.monotonic() - started, 1))
            # 登录失败时站点会在表单里回显原因（密码错、需要验证码…），
            # 把它带出去比等满超时有用得多。但要**连续两次读到同一条**才算数：
            # 提交瞬间页面上常有转瞬即逝的提示，读一次就下结论会误判（实测踩过）。
            err = _login_error(page)
            if err and "csrf" not in err.lower():
                if err == prev_err:
                    return LoginResult(ok=False, site_id=site.id, url=url2,
                                       message=f"登录被拒绝：{err}",
                                       elapsed_s=round(time.monotonic() - started, 1))
                prev_err = err
        url3 = ""
        try:
            url3 = page.url
        except Exception:  # noqa: BLE001
            pass
        return LoginResult(ok=False, site_id=site.id, url=url3,
                           message=f"自动登录 {timeout_s} 秒内没成功",
                           elapsed_s=round(time.monotonic() - started, 1))
    finally:
        try:
            sess.close()
        except Exception:  # noqa: BLE001
            pass


# 这些是提示不是错误：Playwright 用 fill() 填表会触发 NodeBB 的
# 「大写锁定已启用」提示，第一版把它当登录失败直接放弃了 —— 实测误报。
_BENIGN_ERROR_MARKERS = ("大写锁定", "caps lock", "capslock")


def _login_error(page) -> str:
    """登录页回显的错误文案（没有就空串）。"""
    try:
        text = page.evaluate("""() => {
          const nodes = document.querySelectorAll(
            '.alert-danger, .alert-error, [role=alert], .form-error');
          return Array.from(nodes).map(n => (n.innerText || '').trim())
                      .filter(Boolean).join(' | ').slice(0, 160);
        }""") or ""
    except Exception:  # noqa: BLE001
        return ""
    low = text.lower()
    if any(mark in low for mark in _BENIGN_ERROR_MARKERS):
        return ""
    return text
