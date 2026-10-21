"""运行形态相关的路径解析（开发 / PyInstaller 打包两种）。

为什么要单独一层：
  * 开发时（`python app.py`）项目根就是 `finder/` 的上一级，一切照旧。
  * 打包成 onedir 后，Python 代码与静态资源在 PyInstaller 的临时解包目录
    （`sys._MEIPASS`，**只读**），而 config.yaml / sites.yaml / data/ /
    chrome-profile/ 必须放在 **exe 旁边** 才能「拷走就能用」，也才能被用户改。

所以这里把两件事分开：
  bundle_root()  只读资源（config.yaml 模板、sites.yaml 模板、static）
  app_root()     可写数据（用户可改的 config.yaml、缓存库、Chrome profile）
开发形态下两者是同一个目录，行为与打包前完全一致。
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

CONFIG_NAME = "config.yaml"
SITES_NAME = "sites.yaml"


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打出来的 exe 里。"""
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    """只读资源的根目录。"""
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        # onedir 且未设 _MEIPASS 时退到 exe 所在目录
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def app_root() -> Path:
    """可写数据根目录：exe 旁边（开发形态下就是项目根）。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return bundle_root()


def ensure_runtime_files(root: Path | str | None = None) -> Path:
    """确保可写根目录里存在 config.yaml / sites.yaml，缺的从只读资源复制。

    幂等：已存在的文件绝不覆盖（用户的改动不能被升级吞掉）。
    开发形态下源与目标同一个文件，直接跳过。
    """
    target_root = Path(root) if root is not None else app_root()
    target_root.mkdir(parents=True, exist_ok=True)
    for name in (CONFIG_NAME, SITES_NAME):
        target = target_root / name
        if target.exists():
            continue
        src = bundle_root() / name
        if not src.exists():
            continue
        try:
            if src.resolve() == target.resolve():
                continue
        except OSError:  # pragma: no cover - 极端路径异常
            pass
        shutil.copyfile(src, target)
    return target_root


def config_path(root: Path | str | None = None) -> Path:
    return Path(root or app_root()) / CONFIG_NAME


def sites_path(root: Path | str | None = None) -> Path:
    return Path(root or app_root()) / SITES_NAME


def data_dir(root: Path | str | None = None) -> Path:
    d = Path(root or app_root()) / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def static_dir() -> Path:
    """前端静态文件；打包后位于只读资源里（不在 exe 旁边）。"""
    return Path(__file__).resolve().parent / "web" / "static"


def describe() -> dict[str, str]:
    """诊断用：`--check` 会把它打出来。"""
    return {
        "frozen": str(is_frozen()),
        "bundle_root": str(bundle_root()),
        "app_root": str(app_root()),
        "config": str(config_path()),
        "sites": str(sites_path()),
        "data": str(data_dir()),
        "static": str(static_dir()),
    }
