"""Chrome 生命周期。

三条实测硬约束（见 spec §2.1.1 / §2.1.2 / §2.1.4）：
  1. profile 必须是**非默认**路径，否则 Chrome 155 拒绝对默认 user-data-dir
     开放 DevTools（pipe 与 --remote-debugging-port 双双失效，表现为超时）
  2. 代理必须**显式**传 http://127.0.0.1:6234，不能依赖 Chrome 继承系统代理
     （跟随系统代理时 jidiyouxi 会挂）
  3. UA 必须**显式**设真实 Chrome UA，headless 默认 UA 会被 Cloudflare 403

本模块只在真正 `__enter__` 时才导入 playwright，纯函数（版本 / UA / profile）
可以脱离浏览器测试。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from .models import Site

DEFAULT_CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
ANTI_BOT_ARGS = ["--disable-blink-features=AutomationControlled"]
FALLBACK_CHROME_VERSION = "155.0.0.0"

_VERSION_RE = re.compile(r"\b(\d+\.\d+\.\d+(?:\.\d+)?)\b")


def sync_playwright():
    """延迟导入 playwright，让纯函数测试不依赖浏览器环境。"""
    from playwright.sync_api import sync_playwright as _sync_playwright

    return _sync_playwright()


def _read_version_win32(chrome_path: str) -> str | None:
    """用 Win32 版本资源读 chrome.exe 的真实版本。

    注意：Windows 上**不能**用 `chrome.exe --version` —— 它不会打印版本，
    而是在现有浏览器会话里打开一个窗口（实测输出「正在现有的浏览器会话中打开。」）。
    """
    import ctypes
    from ctypes import wintypes

    class _VS_FIXEDFILEINFO(ctypes.Structure):
        _fields_ = [
            ("dwSignature", wintypes.DWORD),
            ("dwStrucVersion", wintypes.DWORD),
            ("dwFileVersionMS", wintypes.DWORD),
            ("dwFileVersionLS", wintypes.DWORD),
            ("dwProductVersionMS", wintypes.DWORD),
            ("dwProductVersionLS", wintypes.DWORD),
            ("dwFileFlagsMask", wintypes.DWORD),
            ("dwFileFlags", wintypes.DWORD),
            ("dwFileOS", wintypes.DWORD),
            ("dwFileType", wintypes.DWORD),
            ("dwFileSubtype", wintypes.DWORD),
            ("dwFileDateMS", wintypes.DWORD),
            ("dwFileDateLS", wintypes.DWORD),
        ]

    try:
        version_dll = ctypes.WinDLL("version")
        size = version_dll.GetFileVersionInfoSizeW(str(chrome_path), None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not version_dll.GetFileVersionInfoW(str(chrome_path), 0, size, buf):
            return None
        ptr = ctypes.c_void_p()
        length = wintypes.UINT()
        if not version_dll.VerQueryValueW(
            buf, "\\", ctypes.byref(ptr), ctypes.byref(length)
        ):
            return None
        info = ctypes.cast(ptr, ctypes.POINTER(_VS_FIXEDFILEINFO)).contents
        if info.dwSignature != 0xFEEF04BD:
            return None
        ms, ls = info.dwFileVersionMS, info.dwFileVersionLS
        return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"
    except Exception:  # noqa: BLE001
        return None


def _read_version_registry() -> str | None:
    """HKCU\\Software\\Google\\Chrome\\BLBeacon 的 version（Windows 专用）。"""
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\BLBeacon"
        ) as key:
            value, _ = winreg.QueryValueEx(key, "version")
        return str(value)
    except Exception:  # noqa: BLE001
        return None


def _read_version_subprocess(chrome_path: str) -> str | None:
    """非 Windows：`chrome --version` 能正常打印。"""
    if sys.platform == "win32":
        # Windows 上执行会开窗口，绝不走这条路。
        return None
    try:
        out = subprocess.run(
            [str(chrome_path), "--version"],
            capture_output=True,
            timeout=10,
        )
        text = out.stdout.decode("utf-8", "replace")
        match = _VERSION_RE.search(text)
        return match.group(1) if match else None
    except Exception:  # noqa: BLE001
        return None


def read_chrome_version(chrome_path: str) -> str:
    """从 chrome.exe 读真实版本号，如 "155.0.8059.80"。

    顺序：文件版本资源 → 注册表 BLBeacon → 常量兜底。
    """
    for reader in (_read_version_win32,):
        version = reader(str(chrome_path))
        if version:
            return version
    version = _read_version_registry()
    if version:
        return version
    version = _read_version_subprocess(str(chrome_path))
    if version:
        return version
    return FALLBACK_CHROME_VERSION


def build_user_agent(chrome_version: str) -> str:
    """拼真实 Chrome UA。major 版本 + .0.0.0 是 Chrome 的惯例写法。"""
    major = str(chrome_version).strip().split(".")[0] or "155"
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{major}.0.0.0 Safari/537.36"
    )


def chrome_default_profile_dir() -> Path:
    """Chrome 的默认 user-data-dir（三条约束里唯一绝不能用的路径）。"""
    home = Path.home()
    if sys.platform == "win32":
        return home / "AppData" / "Local" / "Google" / "Chrome" / "User Data"
    if sys.platform == "darwin":
        return home / "Library" / "Application Support" / "Google" / "Chrome"
    return home / ".config" / "google-chrome"


def _normalized(path: Path | str) -> str:
    """比较用：绝对化 + Windows 大小写/分隔符归一。"""
    return os.path.normcase(os.path.abspath(str(path)))


def is_chrome_default_profile(path: Path | str) -> bool:
    """path 是否等于 Chrome 默认 user-data-dir 或落在它里面。"""
    target = _normalized(path)
    default = _normalized(chrome_default_profile_dir())
    return target == default or target.startswith(default + os.sep)


def resolve_profile_dir(project_root: Path, configured: str) -> Path:
    """专用 profile 目录。绝不允许落到 Chrome 默认 user-data-dir。

    相对路径（config.yaml 的 "chrome-profile"）按 project_root 解析，
    解析结果是 <project_root>/chrome-profile，而非 cwd 或 Chrome 默认目录。
    """
    if not configured:
        raise ValueError("browser.profile_dir is empty; a dedicated profile is required")
    p = Path(configured)
    if not p.is_absolute():
        p = Path(project_root) / p
    if is_chrome_default_profile(p):
        raise ValueError(
            f"browser.profile_dir must not be Chrome's default user-data-dir: {p}"
        )
    return p


class BrowserSession:
    """包装 launch_persistent_context，统一注入 UA / 代理 / 反检测参数。"""

    def __init__(
        self,
        config: dict[str, Any],
        project_root: Path,
        headful_override: bool = False,
    ):
        self._cfg = config
        self._root = Path(project_root)
        self._headful_override = headful_override
        self._pw = None
        self._ctx = None
        self._closed = False
        # 启动后可供诊断/健康检查读取
        self.profile_dir: Path | None = None
        self.user_agent: str | None = None
        self.headless: bool | None = None

    @classmethod
    def for_site(
        cls, config: dict[str, Any], project_root: Path, site: Site
    ) -> "BrowserSession":
        """按站点降级：site.force_headful 为 True 时用 headful。"""
        return cls(config, project_root, headful_override=bool(site.force_headful))

    def __enter__(self) -> "BrowserSession":
        b = self._cfg.get("browser") or {}
        chrome_path = str(b.get("chrome_path") or DEFAULT_CHROME)
        if not Path(chrome_path).exists():
            raise FileNotFoundError(f"chrome not found: {chrome_path}")

        profile = resolve_profile_dir(self._root, b.get("profile_dir", "chrome-profile"))
        profile.mkdir(parents=True, exist_ok=True)

        ua = b.get("user_agent") or build_user_agent(read_chrome_version(chrome_path))
        headless = bool(b.get("headless", True)) and not self._headful_override

        kwargs: dict[str, Any] = {
            "user_data_dir": str(profile),
            "channel": "chrome",
            "executable_path": chrome_path,
            "headless": headless,
            "user_agent": ua,
            "args": list(ANTI_BOT_ARGS),
        }
        px = self._cfg.get("proxy") or {}
        if px.get("enabled") and px.get("server"):
            # 约束 2：显式传，不依赖 Chrome 继承系统代理
            kwargs["proxy"] = {"server": str(px["server"])}

        self.profile_dir = profile
        self.user_agent = ua
        self.headless = headless

        self._pw = sync_playwright().start()
        try:
            self._ctx = self._pw.chromium.launch_persistent_context(**kwargs)
        except BaseException:
            # 启动失败也要收掉 playwright，否则 node driver 会残留
            try:
                self._pw.stop()
            finally:
                self._pw = None
            raise
        return self

    @property
    def context(self):
        return self._ctx

    def new_page(self):
        if self._ctx is None:
            raise RuntimeError("BrowserSession is not started; use it as a context manager")
        return self._ctx.new_page()

    def close(self) -> None:
        """关闭 context 并停止 playwright。close 抛异常时仍会 stop playwright。"""
        if self._closed:
            return
        self._closed = True
        try:
            ctx = self._ctx
            self._ctx = None
            if ctx is not None:
                ctx.close()
        finally:
            pw = self._pw
            self._pw = None
            if pw is not None:
                pw.stop()

    def __exit__(self, *exc) -> None:
        self.close()

    def __repr__(self) -> str:  # pragma: no cover - 诊断用
        return (
            f"<BrowserSession profile={self.profile_dir!r} "
            f"headless={self.headless!r} started={self._ctx is not None}>"
        )
