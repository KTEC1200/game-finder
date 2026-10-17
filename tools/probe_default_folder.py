"""Throwaway probe #35 (OFFLINE): compare the two jidiyouxi topics' default folder.

probe #34: 剑星 topic 171085167 defaults to selectedNav=7 (本体) and its SSR
appState already holds 18 pan links incl. the game body. But the AI LIMIT topic
20093940 appeared to default to selectedNav=8 (修改器). Check the saved file.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).parent
html = (HERE / "_topic_full.html").read_text(encoding="utf-8")

lines: list[str] = []
m = re.search(r'"selectedNav":"?(\d+)"?', html)
lines.append(f"AI LIMIT (20093940) selectedNav = {m.group(1) if m else None}")
m = re.search(r'"post_tab":(\d+)', html)
lines.append(f"AI LIMIT post_tab = {m.group(1) if m else None}")
m = re.search(r'"folder_list":(\[.*?\])', html)
lines.append(f"AI LIMIT folder_list = {m.group(1) if m else None}")

# postList entries: their folder / type
for pm in re.finditer(r'\{"id":(\d+),"mid":\d+,"tid":(\d+).{0,400}?"content":"(.{0,120})', html):
    lines.append(f"  post id={pm.group(1)} tid={pm.group(2)} content={pm.group(3)[:100]!r}")

# game_info blocks
for gm in re.finditer(r'"game_info":(\{.{0,300}?\})', html):
    lines.append("  game_info: " + gm.group(1)[:280])

out = HERE / "_default_folder.txt"
out.write_text("\n".join(lines), encoding="utf-8")
print(f"[wrote {out}] {len(lines)} lines")
