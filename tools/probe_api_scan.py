"""Throwaway probe #31 (OFFLINE): jidiyouxi API endpoints + folder tab mechanism.

probe #29/#30 proved: the 修改器 folder renders, 游戏本体 never does, and no
download control exists in the DOM. Need the API that serves a folder's posts,
so the extractor can ask for folder 10 directly.
"""

from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).parent
html = (HERE / "_topic_full.html").read_text(encoding="utf-8")
lines: list[str] = []

apis = sorted(set(re.findall(r"""["'](/api/[A-Za-z0-9_/\-]+)["']""", html)))
lines.append(f"=== API endpoints: {len(apis)} ===")
for a in apis[:60]:
    lines.append("  " + a)

lines.append("\n=== folder_list occurrences ===")
for m in re.finditer("folder_list", html):
    lines.append(html[max(0, m.start() - 80): m.start() + 300].replace("\n", " "))
    lines.append("")

lines.append("\n=== selectedNav occurrences ===")
for m in re.finditer("selectedNav", html):
    lines.append(html[max(0, m.start() - 120): m.start() + 160].replace("\n", " "))

lines.append("\n=== api/fs or posts endpoint guesses ===")
for m in re.finditer(r"""["']([^"']*topic[^"']*post[^"']*)["']""", html):
    lines.append("  " + m.group(1)[:120])

out = HERE / "_api_scan.txt"
out.write_text("\n".join(lines), encoding="utf-8")
print(f"[wrote {out}] apis={len(apis)}")
for a in apis[:30]:
    print("  ", a)
