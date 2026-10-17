"""启动本地服务并打开浏览器标签页。"""
from __future__ import annotations

import threading
import webbrowser
from pathlib import Path

import uvicorn
import yaml

ROOT = Path(__file__).resolve().parent


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    host = cfg["server"]["host"]
    port = cfg["server"]["port"]
    url = f"http://{host}:{port}/"
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"[game-finder] serving at {url}")
    uvicorn.run("finder.web.server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
