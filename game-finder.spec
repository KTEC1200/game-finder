# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包定义（onedir，便携版）。

为什么是 onedir 而不是 onefile：
  * onefile 每次启动都要把 ~110 MB 的 Playwright driver 解压到临时目录，
    冷启动 5–10 秒，且任务管理器里会出现一个解压后的子进程；
  * onedir 双击即启，`_internal/` 目录本身就是「便携」的边界——
    整个文件夹拷走就能用。

关键点：
  * `config.yaml` / `sites.yaml` 作为**模板**打进 `_internal/`；
    首次运行由 `finder/paths.py::ensure_runtime_files()` 复制到 exe 旁边，
    之后用户改的是 exe 旁边那份，升级不会覆盖。
  * Playwright 的 `driver/`（node.exe + package/）必须完整带上，
    否则 `sync_playwright().start()` 找不到 node 直接崩。
  * 前端 `finder/web/static/` 必须显式加 datas：它不是 .py，
    PyInstaller 的依赖分析看不见它。
"""
from PyInstaller.utils.hooks import collect_data_files

datas = [
    ("config.yaml", "."),
    ("sites.yaml", "."),
    ("finder/web/static/index.html", "finder/web/static"),
]
# playwright 的 driver 目录（node.exe 89 MB + package/）
datas += collect_data_files("playwright")

hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    "finder.web.server",
    "finder.pipeline",
    "finder.browser",
]

excludes = [
    "tkinter", "unittest", "pydoc_data", "pytest", "tests",
    "numpy", "pandas", "matplotlib", "PIL", "IPython",
]

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="game-finder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="game-finder",
)
