"""一次性探针：直连（不走代理）逐个访问 19 个站首页，看谁能通。

输出写 JSON 再读（GBK 控制台会把 CJK 打成乱码）。
"""
from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/155.0.0.0 Safari/537.36"
)
OUT = ROOT / "tools" / "probe_direct_reach.json"


def fetch(url: str, timeout: float = 20.0) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    )
    started = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(200_000)
            return {
                "status": resp.status,
                "bytes": len(body),
                "ms": int((time.time() - started) * 1000),
                "final_url": resp.geturl(),
                "title": _title(body),
            }
    except urllib.error.HTTPError as exc:
        body = b""
        try:
            body = exc.read(200_000)
        except Exception:  # noqa: BLE001
            pass
        return {
            "status": exc.code,
            "bytes": len(body),
            "ms": int((time.time() - started) * 1000),
            "final_url": url,
            "title": _title(body),
            "error": f"HTTPError {exc.code} {exc.reason}",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": None,
            "ms": int((time.time() - started) * 1000),
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
        }


def _title(body: bytes) -> str:
    try:
        text = body.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return ""
    low = text.lower()
    i = low.find("<title")
    if i < 0:
        return ""
    j = text.find(">", i)
    k = text.find("</title>", j)
    if j < 0 or k < 0:
        return ""
    return " ".join(text[j + 1 : k].split())[:120]


def main() -> None:
    ssl_ctx = ssl.create_default_context()
    ssl_ctx.check_hostname = False
    ssl_ctx.verify_mode = ssl.CERT_NONE
    urllib.request.install_opener(
        urllib.request.build_opener(urllib.request.HTTPSHandler(context=ssl_ctx))
    )
    raw = yaml.safe_load((ROOT / "sites.yaml").read_text(encoding="utf-8"))
    results = {}
    for item in raw["sites"]:
        sid = item["id"]
        home = item["homepage"]
        results[sid] = {"homepage": home, **fetch(home)}
        print(f"{sid:14s} {results[sid].get('status')} {results[sid].get('ms')}ms "
              f"{results[sid].get('error', '')}")
    OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"written {OUT}")


if __name__ == "__main__":
    main()
