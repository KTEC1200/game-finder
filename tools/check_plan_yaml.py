"""Verify the sites.yaml embedded in the plan matches the spec's assertions."""
import re
from pathlib import Path

txt = Path(r"C:\Users\27025\Desktop\game-finder\docs\superpowers\plans"
           r"\2026-10-17-game-finder-implementation.md").read_text(encoding="utf-8")

start = txt.index("# 站点注册表")
end = txt.index("```", start)
y = txt[start:end]

blocks = re.split(r"\n  - id: ", y)[1:]
sites = {}
for b in blocks:
    sid = b.split("\n")[0].strip()
    m = re.search(r"langs: \[([^\]]*)\]", b)
    langs = [x.strip() for x in m.group(1).split(",")] if m else []
    sites[sid] = {"langs": langs, "form": "mode: form" in b}

print("sites:", len(sites))
for lang in ("zh", "en", "ja"):
    print(lang, sum(1 for v in sites.values() if lang in v["langs"]))
print("form:", sorted(k for k, v in sites.items() if v["form"]))
