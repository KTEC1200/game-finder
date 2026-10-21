"""启动本地服务并打开浏览器标签页。

两种运行形态共用这一个入口：
  * 开发：`python app.py`
  * 打包：双击 `game-finder.exe`（PyInstaller onedir）

差异全部收敛在 `finder/paths.py`：打包后 config.yaml / sites.yaml / data/ /
chrome-profile/ 都在 **exe 旁边**（可写、可改），代码与前端资源在只读资源里。
"""
from __future__ import annotations

import argparse
import logging
import socket
import sys
import threading
import webbrowser

import uvicorn
import yaml

from finder import paths, proxy

log = logging.getLogger("gamefinder")


def _setup_logging(root) -> None:
    """控制台 + 文件双写。打包版的控制台可能被用户关掉，日志文件是唯一线索。"""
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    try:
        logs = root / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(logs / "game-finder.log", encoding="utf-8"))
    except OSError:
        pass  # 只读目录下就只写控制台，不能因为日志挂了起不来
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def _pick_port(host: str, preferred: int) -> int:
    """端口被占就往后找 10 个，别让「上次没退干净」变成「双击没反应」。"""
    for candidate in [preferred, *range(preferred + 1, preferred + 11)]:
        if _port_free(host, candidate):
            return candidate
    raise SystemExit(
        f"[game-finder] 端口 {preferred}–{preferred + 10} 全被占用，"
        "请关掉占用这些端口的程序后重试。"
    )


def _preflight(cfg: dict) -> None:
    """启动前把「必然失败」的环境问题一次性说清楚，而不是等用户搜完才报错。"""
    from finder.browser import CHROME_CANDIDATES, find_chrome

    chrome_cfg = str((cfg.get("browser") or {}).get("chrome_path") or "")
    chrome = find_chrome(chrome_cfg)
    if chrome is None:
        raise SystemExit(
            "[game-finder] 没找到 Google Chrome。\n"
            "本程序依赖系统安装的 Chrome（Playwright 自带浏览器过不了部分站点的\n"
            "Cloudflare 挑战，所以没有打包浏览器）。\n"
            "请先安装 Chrome：https://www.google.com/chrome/\n"
            "已尝试：\n  " + "\n  ".join(p for p in [chrome_cfg, *CHROME_CANDIDATES] if p)
        )
    if chrome_cfg and chrome != chrome_cfg:
        log.warning("config 里的 chrome_path 不存在，改用 %s", chrome)

    decision = proxy.resolve(cfg)
    if decision.server:
        log.info("代理：%s", decision.reason)
    else:
        log.warning("代理未启用（%s）—— 将直连。实测 19 站里 18 站直连可用，"
                    "只有 nyaa 可能超时。", decision.reason)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="game-finder", add_help=True)
    parser.add_argument("--check", action="store_true",
                        help="只打印环境诊断信息然后退出（不启动服务）")
    parser.add_argument("--no-browser", action="store_true",
                        help="不自动打开浏览器标签页")
    args = parser.parse_args(argv)

    root = paths.ensure_runtime_files()
    _setup_logging(root)

    if args.check:
        info = paths.describe()
        info["chrome"] = _chrome_report()
        for key, value in info.items():
            print(f"{key:12s} {value}")
        return

    cfg = yaml.safe_load(paths.config_path(root).read_text(encoding="utf-8"))
    _preflight(cfg)

    host = cfg["server"]["host"]
    port = _pick_port(host, int(cfg["server"]["port"]))
    url = f"http://{host}:{port}/"
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    log.info("serving at %s (root=%s)", url, root)

    from finder.web.server import app as fastapi_app

    uvicorn.run(fastapi_app, host=host, port=port, reload=False, log_level="info")


def _chrome_report() -> str:
    from finder.browser import find_chrome, read_chrome_version

    path = find_chrome()
    if path is None:
        return "NOT FOUND"
    try:
        return f"{path} ({read_chrome_version(path)})"
    except Exception:  # noqa: BLE001 - 诊断信息不该抛
        return path


if __name__ == "__main__":
    main()
