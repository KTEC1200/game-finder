"""Throwaway probe #28: where is the MAIN game download link on jidiyouxi?

probe #27 saved appState. `topic.ssrData.topicDetail.list` holds 3 POST items
(trainers) with a `content` field carrying pan links. But those are 修改器
posts by 修改器大王, not the game body itself. Need: is the game body's own
download link anywhere in appState, or only reachable via the 下载 button UI?
"""

from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).parent
d = json.loads((HERE / "_appstate.json").read_text(encoding="utf-8"))

lines: list[str] = []


def w(s: str = "") -> None:
    lines.append(s)


# 1. any pan/magnet URL anywhere in the whole appState
whole = json.dumps(d, ensure_ascii=False)
pans = sorted(set(re.findall(
    r"https?://[^\"\\\s]*(?:pan\.|quark|123pan|lanzou|aliyundrive|alipan|xunlei|"
    r"pikpak|baidu|115\.com|mega\.nz|mediafire|cowtransfer)[^\"\\\s]*", whole)))
w(f"=== pan/magnet URLs anywhere in appState: {len(pans)} ===")
for p in pans:
    w("  " + p)

# 2. topicInfo
ti = d["topic"]["ssrData"].get("topicInfo")
w("\n=== topicInfo ===")
w(json.dumps(ti, ensure_ascii=False, indent=2)[:4000] if ti else "  None")

# 3. the post items' content (the pan links live here)
lst = d["topic"]["ssrData"]["topicDetail"]["list"]
w(f"\n=== topicDetail.list: {len(lst)} items ===")
for i, item in enumerate(lst):
    w(f"\n--- post {i} id={item.get('id')} title={item.get('title')!r}")
    w(f"    cloud_resource={item.get('cloud_resource')} resource_type={item.get('resource_type')} "
      f"c_type={item.get('c_type')}")
    c = item.get("content") or ""
    w(f"    content len={len(c)}")
    for m in re.findall(r"https?://[^\s\"\\]+", c):
        w("      URL: " + m)
    w("    content head: " + c[:300].replace("\n", " | "))

# 4. game_info - does it hold download urls?
gi = d["topic"]["currentTopic"].get("game_info") or {}
w("\n=== currentTopic.game_info keys ===")
for k, v in gi.items():
    s = json.dumps(v, ensure_ascii=False)
    w(f"  {k}: {type(v).__name__} len={len(s)} :: {s[:200]}")

# 5. any key named like download/url anywhere, with its path
w("\n=== key paths matching down|url|link|share ===")
found: list[str] = []


def walk(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{path}.{k}"
            if re.search(r"down|url|link|share|pan|netdisk|resource", k, re.I):
                s = json.dumps(v, ensure_ascii=False)
                found.append(f"{p} [{type(v).__name__}] len={len(s)} :: {s[:160]}")
            walk(v, p)
    elif isinstance(node, list):
        for i, v in enumerate(node[:3]):
            walk(v, f"{path}[{i}]")


walk(d)
for f in found[:60]:
    w("  " + f)

out = HERE / "_appstate_analysis.txt"
out.write_text("\n".join(lines), encoding="utf-8")
print(f"[wrote {out}] {len(lines)} lines")
