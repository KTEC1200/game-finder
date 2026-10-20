"""Inspect galgamex detail-page structure around the download tab.

Console is GBK: never print CJK here, emit JSON to a file and print only ASCII
keys/indices. Uses a plain urllib fetch (the local proxy at 127.0.0.1:6234 was
down at probe time; the site answers 200 with a real Chrome UA).
"""

from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
)
URL = "https://www.galgamex.net/game/cbe7d89e"
HERE = Path(__file__).parent
TAB = "\u8d44\u6e90\u4e0b\u8f7d"  # 资源下载


def main() -> None:
    req = urllib.request.Request(URL, headers={"User-Agent": UA})
    html = urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "replace")

    out: dict = {"len": len(html), "tab_occurrences": [], "class_hints": {}}

    for m in re.finditer(re.escape(TAB), html):
        s = max(0, m.start() - 400)
        e = min(len(html), m.end() + 400)
        out["tab_occurrences"].append(html[s:e])

    # What classes/attributes do download-ish controls carry?
    for pat in (
        r'class="[^"]*download[^"]*"',
        r'data-slot="[^"]*"',
        r'href="[^"]*redirect[^"]*"',
        r'href="[^"]*/api/[^"]*"',
        r'class="[^"]*provider[^"]*"',
    ):
        hits = sorted(set(re.findall(pat, html)))
        out["class_hints"][pat] = hits[:25]

    # Any pan/redirect URLs at all in the raw HTML?
    out["pan_urls"] = re.findall(r"https?://[^\"'\s<>]*(?:pan\.baidu|pan\.quark|aliyundrive|123pan)[^\"'\s<>]*", html)[:10]
    out["has_redirect"] = "redirect" in html.lower()

    # Buttons with their visible text (script bodies stripped first).
    stripped = re.sub(r"<script\b.*?</script>", "", html, flags=re.S | re.I)
    buttons = []
    for m in re.finditer(r"<button\b([^>]*)>(.*?)</button>", stripped, re.S | re.I):
        attrs, inner = m.group(1), m.group(2)
        text = re.sub(r"<[^>]+>", " ", inner)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            buttons.append({"text": text[:60], "attrs": attrs[:200]})
    out["buttons_with_text"] = buttons[:40]

    (HERE / "probe_galgamex_static.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("html_len:", len(html))
    print("tab_occurrences:", len(out["tab_occurrences"]))
    print("has_redirect:", out["has_redirect"])
    print("pan_urls:", len(out["pan_urls"]))
    print("buttons_with_text:", len(buttons))
    for i, b in enumerate(buttons[:25]):
        print(f"  [{i}] text={b['text']!r}")
    for pat, hits in out["class_hints"].items():
        print("PAT", pat, "->", len(hits))
        for h in hits[:8]:
            print("    ", h[:120])


if __name__ == "__main__":
    main()
