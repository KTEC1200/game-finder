"""构建 Windows 便携版（PyInstaller onedir + zip）。

用法：
    python tools/build_portable.py            # 构建并打包 zip
    python tools/build_portable.py --no-zip   # 只构建

产物：
    dist/game-finder/            可直接双击 game-finder.exe 的文件夹
    dist/game-finder-<ver>-win64.zip   整个文件夹的压缩包（便携版发布物）

为什么不用 onefile：onefile 每次启动都要把 ~90 MB 的 Playwright node.exe
解压到临时目录，冷启动慢且会多一个子进程。onedir 双击即启，
「整个文件夹拷走就能用」本身已经满足便携诉求。
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
APP_DIR = DIST / "game-finder"

# 首次运行会生成、不该进发布包的东西
RUNTIME_ARTIFACTS = (
    "data", "logs", "run.log", "run2.log",
    "chrome-profile", "chrome-profile-w0", "chrome-profile-w1",
    "chrome-profile-w2", "chrome-profile-sweep0",
)


def version() -> str:
    """从 PROGRESS.md 找不到版本号就退到日期，保证 zip 名可辨识。"""
    try:
        text = (ROOT / "finder" / "__init__.py").read_text(encoding="utf-8")
    except OSError:
        return "dev"
    for line in text.splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip("\"'")
    return "dev"


def build() -> None:
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
           "game-finder.spec"]
    print("[build]", " ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def clean_runtime_artifacts() -> None:
    """把构建过程/本地试跑留下的运行态文件剔掉，否则 zip 里带着别人的缓存。"""
    for name in RUNTIME_ARTIFACTS:
        target = APP_DIR / name
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        elif target.exists():
            target.unlink()


def make_zip() -> Path:
    out = DIST / f"game-finder-{version()}-win64.zip"
    if out.exists():
        out.unlink()
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in sorted(APP_DIR.rglob("*")):
            if not path.is_file():
                continue
            # 压缩包内顶层目录就叫 game-finder/，解压即得一个自包含文件夹
            zf.write(path, Path("game-finder") / path.relative_to(APP_DIR))
            count += 1
    print(f"[zip] {out} ({count} files, {out.stat().st_size / 1048576:.1f} MB)")
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-zip", action="store_true", help="只构建，不打包 zip")
    args = parser.parse_args(argv)

    build()
    clean_runtime_artifacts()
    if not args.no_zip:
        make_zip()


if __name__ == "__main__":
    main()
