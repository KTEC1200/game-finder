"""Throwaway probe #23: show the DOM context around jidiyouxi pan links.

probe #22 proved the pan links ARE in the rendered DOM (baidu x3 + xunlei x1)
but the earlier "external anchors" query missed them, so the container shape is
still unknown. Dump context to a file (avoids GBK console issues).
"""

from pathlib import Path

HERE = Path(__file__).parent
html = (HERE / "_topic_full.html").read_text(encoding="utf-8")

needles = [
    "pan.baidu.com/s/1WUQ3Mvd7ZlPJF47gbK5BVw",
    "pan.xunlei.com/s/VOZdAgB2jxTWS-ce21yI8KnKA1",
]
chunks = []
for n in needles:
    i = html.find(n)
    chunks.append(f"===== {n} @ {i} =====\n" + html[max(0, i - 1500): i + 500])

(HERE / "_pan_context.txt").write_text("\n\n".join(chunks), encoding="utf-8")
print("[wrote _pan_context.txt]", len("\n\n".join(chunks)))
