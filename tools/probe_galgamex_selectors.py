"""Score candidate `download_open_selector` values against the real page.

Requirement: match ONLY the resource-card download buttons (分卷 N / 网盘 provider),
not the tab bar, not 复制/反馈/收藏. Prints matched texts per candidate.
"""

from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = Path(r"D:\K\deepseek\_gf_galgamex_probe")
URL = "https://www.galgamex.net/game/cbe7d89e"
HERE = Path(__file__).parent
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36"
)
TAB = "\u8d44\u6e90\u4e0b\u8f7d"  # 资源下载

CANDIDATES = [
    "button[data-slot='button'][data-variant='default'][data-size='sm']",
    "button[data-slot='button'][data-size='sm']",
    "div:has(> h2:text-is('\u8d44\u6e90\u4e0b\u8f7d')) button[data-slot='button']",
    "button:has-text('\u5206\u5377'), button:has-text('\u7f51\u76d8')",
    "button[data-variant='default']",
]

TEXTS_JS = """
(sel) => Array.from(document.querySelectorAll(sel)).map(e => ({
  text: (e.innerText || '').trim().replace(/\\s+/g, ' '),
  variant: e.getAttribute('data-variant') || '',
  size: e.getAttribute('data-size') || '',
  visible: e.getBoundingClientRect().width > 0,
}))
"""


def main() -> None:
    out: dict = {"candidates": {}}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE),
            channel="chrome",
            executable_path=CHROME,
            headless=True,
            timeout=60_000,
            user_agent=UA,
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.new_page()

        def on_route(route) -> None:
            try:
                route.abort()
            except Exception:  # noqa: BLE001
                pass

        ctx.route("**/redirect*", on_route)
        page.goto(URL, timeout=45000, wait_until="load")
        page.wait_for_timeout(4500)
        page.get_by_text(TAB, exact=False).first.click(timeout=8000)
        page.wait_for_timeout(2500)

        for sel in CANDIDATES:
            try:
                matched = page.evaluate(TEXTS_JS, sel)
            except Exception as exc:  # noqa: BLE001
                matched = [{"error": f"{type(exc).__name__}: {exc}"[:120]}]
            vis = [m for m in matched if m.get("visible")]
            out["candidates"][sel] = {"total": len(matched), "visible": len(vis), "items": matched}
            print(f"--- {sel}\n    total={len(matched)} visible={len(vis)}")
            for m in vis:
                print("     ", repr(m.get("text")), m.get("variant"), m.get("size"))
        ctx.close()

    (HERE / "probe_galgamex_selectors.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    lines = []
    for sel, info in out["candidates"].items():
        lines.append(f"=== {sel}  total={info['total']} visible={info['visible']}")
        for m in info["items"]:
            lines.append(f"    vis={m.get('visible')} variant={m.get('variant')} size={m.get('size')} text={m.get('text')!r}")
    (HERE / "probe_galgamex_selectors.txt").write_text("\n".join(lines), encoding="utf-8")
    print("wrote probe_galgamex_selectors.{json,txt}")


if __name__ == "__main__":
    main()
