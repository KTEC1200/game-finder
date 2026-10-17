"""Throwaway probe #30 (OFFLINE): find jidiyouxi's 下载 affordance in saved HTML.

probe #29 showed only the 修改器 folder tab renders (post_tab=8); folder 10
(游戏本体) never appears, so the game-body link may not exist on this topic at
all. Before concluding, scan the saved full DOM for every 下载 occurrence and
its enclosing element to see if there is a real download control.
"""

from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).parent
html = (HERE / "_topic_full.html").read_text(encoding="utf-8")

lines: list[str] = []
lines.append(f"html len = {len(html)}")

# every 下载 occurrence with a wide window, tag-stripped
for i, m in enumerate(re.finditer("下载", html)):
    s = max(0, m.start() - 350)
    ctx = html[s: m.start() + 250]
    ctx = re.sub(r"\s+", " ", ctx)
    lines.append(f"\n--- #{i} @ {m.start()} ---")
    lines.append(ctx)

# is there an element whose own text is exactly 下载?
own = re.findall(r'>([^<>]{0,12}下载[^<>]{0,12})<', html)
lines.append("\n=== own-text matches ===")
for o in own:
    lines.append("  " + repr(o))

# any 'download' class/id
lines.append("\n=== download-ish attrs ===")
for m in re.finditer(r'(?:class|id)="([^"]*[Dd]ownload[^"]*)"', html):
    lines.append("  " + m.group(1)[:160])

out = HERE / "_download_scan.txt"
out.write_text("\n".join(lines), encoding="utf-8")
print(f"[wrote {out}] {len(lines)} lines, {len(own)} own-text matches")
