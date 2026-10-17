"""Throwaway probe #39: close the two extraction gaps found by probe #38.

Gap A (gamer520): the valid 剑星 detail page 123857.html yielded pan_total=0, yet
the page clearly offers downloads. Find the real control (button? hidden div?
reply-gate? QR?).

Gap B (jidiyouxi): `og:image` is the string "[object Object]" (a React bug), so
the cover must come from elsewhere — the <link rel=preload as=image> or appState.

Also: gamer520's QR-code links carry the pan URL urlencoded inside `data=`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote

from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = Path(r"D:\K\deepseek\_gf_e2e_probe")
PROXY = "http://127.0.0.1:6234"
HERE = Path(__file__).parent


def main() -> None:
    out: dict = {}
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE), channel="chrome", executable_path=CHROME,
            headless=True, timeout=60_000, proxy={"server": PROXY},
        )
        page = ctx.new_page()

        # ---------- Gap A: gamer520 download control ----------
        page.goto("https://www.gamer520.com/123857.html", timeout=45000, wait_until="load")
        page.wait_for_timeout(8000)
        out["g520"] = page.evaluate(
            r"""() => {
                const html = document.documentElement.outerHTML;
                // elements whose text mentions download-ish words
                const hits = Array.from(document.querySelectorAll('a,button,div,span,p,li'))
                    .filter(e => e.children.length <= 2)
                    .map(e => ({tag: e.tagName, t: (e.innerText||'').trim().slice(0,60),
                                href: e.getAttribute('href') || null,
                                cls: (e.className||'').toString().slice(0,70)}))
                    .filter(o => o.t && /下载|网盘|提取码|回复|可见|登录|购买|立即/.test(o.t))
                    .slice(0, 40);
                // hidden pan links
                const pans = Array.from(new Set(html.match(/https?:[^\s"'<>]*(?:pan\.|quark|xunlei|123pan|lanzou|magnet:)[^\s"'<>]*/g) || []));
                // is there a reply/login gate?
                const gate = /回复可见|登录后可见|请先登录|评论后|购买后|VIP|积分/.test(document.body.innerText||'');
                // qr endpoints
                const qrs = Array.from(new Set(html.match(/https?:[^\s"'<>]*qrserver[^\s"'<>]*/g) || []));
                return {hits: hits, pans: pans.slice(0,10), pans_total: pans.length,
                        gate: gate, qrs: qrs.slice(0,6), qr_total: qrs.length,
                        title: document.title, body_len: (document.body.innerText||'').length};
            }"""
        )
        # decode the qr data params
        out["g520_qr_decoded"] = [unquote(u.split("data=")[-1])[:200]
                                  for u in out["g520"]["qrs"] if "data=" in u]

        # ---------- Gap B: jidiyouxi cover ----------
        page.goto("https://www.jidiyouxi.com/topic/detail/171085167", timeout=45000,
                  wait_until="load")
        page.wait_for_timeout(8000)
        out["jidi"] = page.evaluate(
            r"""() => {
                const html = document.documentElement.outerHTML;
                const preload = Array.from(document.querySelectorAll('link[rel=preload][as=image]')).map(l => l.getAttribute('href'));
                const imgs = Array.from(document.querySelectorAll('img')).map(i => i.src).filter(Boolean).slice(0, 12);
                const ogi = (document.querySelector('meta[property="og:image"]')||{}).content || null;
                const st = document.getElementById('appState');
                const t = st ? (st.textContent||'') : '';
                const cover = t.match(/"cover[^"]*":"([^"]{10,200})"/g) || [];
                return {preload: preload.slice(0,6), imgs: imgs, ogi: ogi,
                        cover_fields: cover.slice(0,6),
                        img2: Array.from(new Set(html.match(/https?:\/\/img\d*\.52jidi\.com[^\s"'<>\\]*/g) || [])).slice(0,8)};
            }"""
        )
        ctx.close()

    (HERE / "probe_gaps2.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = []
    lines.append("=== gamer520 123857 ===")
    lines.append(f"title={out['g520']['title']} body_len={out['g520']['body_len']} gate={out['g520']['gate']}")
    lines.append(f"pans_total={out['g520']['pans_total']} qr_total={out['g520']['qr_total']}")
    for h in out["g520"]["hits"]:
        lines.append(f"  {h['tag']} {h['t']!r} href={h['href']!r} cls={h['cls'][:50]!r}")
    lines.append("  qr decoded:")
    for q in out["g520_qr_decoded"]:
        lines.append(f"    {q}")
    lines.append("  pans:")
    for x in out["g520"]["pans"]:
        lines.append(f"    {x[:140]}")
    lines.append("\n=== jidiyouxi cover ===")
    lines.append("preload=" + json.dumps(out["jidi"]["preload"], ensure_ascii=False))
    lines.append("imgs=" + json.dumps(out["jidi"]["imgs"][:6], ensure_ascii=False))
    lines.append("ogi=" + repr(out["jidi"]["ogi"]))
    lines.append("img2=" + json.dumps(out["jidi"]["img2"][:5], ensure_ascii=False))
    (HERE / "_gaps2.txt").write_text("\n".join(lines), encoding="utf-8")
    print("ok -> _gaps2.txt")


if __name__ == "__main__":
    main()
