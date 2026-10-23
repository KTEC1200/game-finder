"""真流式探针：直接调 FastAPI 应用，测「第一张卡」与各帧到达时间。

用法：
  python tools/probe_stream.py --lang zh --out tools/probe_stream_zh.json
  python tools/probe_stream.py --lang en --out tools/probe_stream_en.json

不启 uvicorn、不开浏览器窗口：TestClient 在进程内跑 SSE，只读真实站点，
用来验证 v0.1.2 的「边搜边推」与登录链路（galgame.dev 必须出卡片）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from finder.web.server import create_app  # noqa: E402

QUERIES = {"zh": "千恋万花", "en": "senren banka"}


def run_once(client: TestClient, query: str) -> dict:
    t0 = time.time()
    marks: dict[str, float] = {}
    frames: list[str] = []
    results: list[dict] = []
    order: list[str] = []
    done: dict = {}
    with client.stream("POST", "/api/search",
                       json={"query": query, "refresh": True}) as resp:
        assert resp.status_code == 200, resp.status_code
        for line in resp.iter_lines():
            if line.startswith("event: "):
                ev = line[7:].strip()
                frames.append(ev)
                marks.setdefault(ev, round(time.time() - t0, 2))
            elif line.startswith("data: "):
                data = json.loads(line[5:])
                if frames and frames[-1] == "result":
                    results.append(data)
                elif frames and frames[-1] == "order":
                    order = data.get("site_ids") or []
                elif frames and frames[-1] == "done":
                    done = data
    return {
        "query": query,
        "total_s": round(time.time() - t0, 2),
        "first_result_s": marks.get("result"),
        "first_frame_s": marks.get("start"),
        "frames": {k: v for k, v in marks.items()},
        "streamed_results": len(results),
        "order": order,
        "done": done,
        "results": [
            {
                "site_id": r["site_id"],
                "outcome": r.get("outcome"),
                "downloads": len(r.get("downloads") or []),
                "error": r.get("error"),
                "title": (r.get("title") or "")[:60],
            }
            for r in results
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=sorted(QUERIES), default="zh")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    client = TestClient(create_app())
    runs = []
    # 第一轮可能包含自动登录（galgame.dev 登录态过期时 ~8s），第二轮是稳态
    for i in (1, 2):
        r = run_once(client, QUERIES[args.lang])
        r["run"] = i
        runs.append(r)
        print(f"run{i}: total={r['total_s']}s first_result={r['first_result_s']}s "
              f"results={r['streamed_results']} done={r['done']}", flush=True)
    out = {"lang": args.lang, "runs": runs}
    if args.out:
        Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
