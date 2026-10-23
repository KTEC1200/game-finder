"""真流式探针（HTTP 版）：连真实 uvicorn，逐帧记录到达时间。

TestClient 会把整个 SSE body 缓冲到结束（starlette 的测试 transport 行为），
所以「第一张卡几秒到」只能对着真服务量。用法：

  python app.py --no-browser --port 8799
  python tools/probe_stream_http.py --url http://127.0.0.1:8799 --query 千恋万花
"""
from __future__ import annotations

import argparse
import http.client
import json
import time
from pathlib import Path
from urllib.parse import urlparse


def probe(url: str, query: str, refresh: bool = True) -> dict:
    u = urlparse(url)
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=180)
    body = json.dumps({"query": query, "refresh": refresh}).encode()
    t0 = time.time()
    conn.request("POST", "/api/search", body=body,
                 headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    assert resp.status == 200, resp.status
    marks: dict[str, float] = {}
    frames: list[str] = []
    results: list[dict] = []
    order: list[str] = []
    done: dict = {}
    buf = b""
    while True:
        chunk = resp.read1(4096)
        if not chunk:
            break
        buf += chunk
        while b"\n\n" in buf:
            blk, buf = buf.split(b"\n\n", 1)
            ev = data = None
            for line in blk.decode("utf-8", "replace").splitlines():
                if line.startswith("event: "):
                    ev = line[7:].strip()
                elif line.startswith("data: "):
                    data = json.loads(line[6:])
            if not ev:
                continue
            frames.append(ev)
            marks.setdefault(ev, round(time.time() - t0, 2))
            if ev == "result":
                results.append(data)
            elif ev == "order":
                order = data.get("site_ids") or []
            elif ev == "done":
                done = data
    conn.close()
    return {
        "query": query, "total_s": round(time.time() - t0, 2),
        "first_result_s": marks.get("result"),
        "frame_marks": marks,
        "streamed_results": len(results),
        "order": order, "done": done,
        "results": [
            {"site_id": r["site_id"], "outcome": r.get("outcome"),
             "downloads": len(r.get("downloads") or []),
             "error": r.get("error"), "title": (r.get("title") or "")[:60]}
            for r in results
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8799")
    ap.add_argument("--query", action="append", default=[])
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    queries = args.query or ["千恋万花"]
    runs = []
    for q in queries:
        r = probe(args.url, q)
        runs.append(r)
        print(f"{q}: total={r['total_s']}s first_result={r['first_result_s']}s "
              f"results={r['streamed_results']} done={r['done']}", flush=True)
    if args.out:
        Path(args.out).write_text(json.dumps(runs, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
