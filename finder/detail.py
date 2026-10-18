"""详情页抽取。

实测要点（spec §2.1.3）：
  - jidiyouxi 的网盘链接不在 <a> 标签，只在整页 HTML → 必须对 outerHTML 跑正则
  - jidiyouxi 的 og:image 是坏字符串 "[object Object]" → 回退 <link rel=preload as=image>
    （实测保存的 fixture 里连 preload 图也没有 → 再回退图片 CDN 的 id 规律）
  - gamer520 落地页用二维码藏链接 → 解 data= 参数（注意 HTML 里是 &amp;data=）
  - 二维码图片本身的 URL 不是下载链接 → 按 host 排除
"""
from __future__ import annotations

import base64
import html as html_mod
import re
from urllib.parse import unquote

from .models import Download, GameDetail

PAN_DOMAINS = (
    "pan.baidu.com", "pan.quark.cn", "pan.xunlei.com", "aliyundrive.com",
    "alipan.com", "123pan.com", "lanzou", "cowtransfer.com", "mega.nz",
    "1fichier.com", "mediafire.com", "drive.google.com", "mypikpak.com",
    "115.com", "pikpak",
)

# 文件寄存商（anime-sharing 的帖子只有这类直链，实测 2026-10-18）：
# rapidgator / katfile 各给一份，分卷用 PART1..PART6 的多个 URL 表示。
FILEHOST_DOMAINS = (
    "rapidgator.net", "katfile.com", "katfile.biz", "nitroflare.com",
    "tezfiles.com", "fikper.com", "ddownload.com", "alfafile.net",
    "fileditchfiles.me", "pixeldrain.com", "gofile.io", "buzzheavier.com",
    "send.now", "workupload.com", "mixdrop.co", "1cloudfile.com",
    "datanodes.to", "filemoon.sx", "krakenfiles.com", "uploadhaven.com",
)

# 页面装饰资源：图标、图片代理、追踪像素。它们会因为域名里带 filehost 关键字
# 或路径里带 /file 而被 _classify 判成下载（anime-sharing 实测：favicon.ico 与
# p.anime-sharing.com/proxy.php?image= 都被当成 filehost 混进结果）。
ASSET_URL_RE = re.compile(
    r"(?:favicon\.ico|/proxy\.php\?image=|/apple-touch-icon|/logo\.(?:png|svg|gif)"
    r"|\.(?:png|jpe?g|gif|webp|svg|ico|css|js|woff2?|ttf)(?:\?|#|$))",
    re.I,
)

# gamebounty 的下载按钮不指向文件主机本身，而是同源跳板：
#   /api/dl/{slug}/{base64url(真实URL)}
# 解码后才是 rapidgator/pixeldrain 之类的真链（实测 2026-10-18）。
GB_DL_RE = re.compile(r"https?://[^\s\"'<>\\]*/api/dl/([^/\s\"'<>\\]+)/([A-Za-z0-9_\-=]+)")

# 整页 HTML 里抓 pan/magnet 链接。排除紧跟的引号/反斜杠，避免把 JSON 转义带进来。
URL_RE = re.compile(
    r"https?://[^\s\"'<>\\]+",
)
MAGNET_RE = re.compile(r"magnet:\?xt=urn:btih:[a-zA-Z0-9]+")
# ggbases 的磁力页链接：magnet.so?id=N（相对 / 绝对 / 裸形式都见过）
MAGNET_ID_RE = re.compile(r"magnet\.so\?id=(\d+)", re.I)
# BTIH hash：40 位十六进制（v1）或 32 位 base32
MAGNET_HASH_RE = re.compile(r"[a-fA-F0-9]{40}|[A-Za-z2-7]{32}")
CODE_RE = re.compile(r"(?:提取码|密码|访问码|pwd)\s*[:：=]?\s*([a-zA-Z0-9]{4,8})")
QR_RE = re.compile(
    r"https?://[^\s\"'<>\\]*qrserver[^\s\"'<>\\]*[?&]data=([^&\"'<>\\]+)"
)
# 二维码图片本身（api.qrserver.com/...）不是下载链接；其载荷由 decode_qr_pan_links 解出。
QR_IMAGE_HOST_RE = re.compile(r"qrserver\.com", re.I)
PRELOAD_IMG_RE = re.compile(
    r'<link[^>]+rel=["\']preload["\'][^>]+as=["\']image["\'][^>]+href=["\']([^"\']+)',
    re.I,
)
# jidiyouxi 的图片 CDN 规律：img2.52jidi.com/topic/cover/id/<id>/sz/420
# 页面里既可能是真斜杠，也可能是 JSON 转义的 \u002F，两种都认。
COVER_ID_RE = re.compile(
    r"img\d*\.52jidi\.com(?:\\u002F|/)(?:topic(?:\\u002F|/)cover|img(?:\\u002F|/)view)"
    r"(?:\\u002F|/)id(?:\\u002F|/)(\d+)"
)
OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']*)', re.I
)
OG_TITLE_RE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']*)', re.I
)
OG_DESC_RE = re.compile(
    r'<meta[^>]+(?:property=["\']og:description["\']|name=["\']description["\'])'
    r'[^>]+content=["\']([^"\']*)', re.I
)
TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
SIZE_RE = re.compile(r"\b\d+(?:\.\d+)?\s?(?:GB|MB|TB)\b")
VERSION_RE = re.compile(r"\bV?\d+\.\d+(?:\.\d+)*(?:\.[A-Za-z]+\d+)?\b")
DATE_RE = re.compile(r"20\d{2}[-/年.]\d{1,2}[-/月.]\d{1,2}")


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html_mod.unescape(s or "")).strip()


def _trim_url(url: str) -> str:
    """截掉 URL 后面粘连的非 URL 尾巴。

    实测（touchgal，2026-10-18）：页面正文里存在 Markdown 文本
    `[工具](https://pan.quark.cn/s/xxx)`，直接跑 URL_RE 会得到
    `https://pan.quark.cn/s/xxx](https://pan.quark.cn/s/xxx` 这种畸形串，
    既污染结果又会让去重失效。→ 在 `](` / `[` / 空白前截断，再去尾部标点。
    """
    for stop in ("](", "\\u002F]"):
        idx = url.find(stop)
        if idx > 0:
            url = url[:idx]
    return url.rstrip(".,);]}")


def _classify(url: str) -> str:
    low = url.lower()
    if low.startswith("magnet:"):
        return "magnet"
    if any(d in low for d in PAN_DOMAINS):
        return "pan"
    if any(d in low for d in FILEHOST_DOMAINS):
        return "filehost"
    if re.search(r"/(download|dl|down|file)", low):
        return "direct"
    return "unknown"


def decode_gb_dl_links(html: str) -> list[str]:
    """解 gamebounty 的 /api/dl/{slug}/{base64url} 跳板，拿到真实文件主机 URL。

    页面上点「下载完整游戏」链接到的是这种同源包装链接，真链被 base64url
    编码在末段。解不出来就跳过（不猜）。
    """
    out: list[str] = []
    for m in GB_DL_RE.finditer(html_mod.unescape(html)):
        raw = m.group(2)
        raw += "=" * (-len(raw) % 4)
        try:
            real = base64.urlsafe_b64decode(raw).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            continue
        if real.startswith("http") and real not in out:
            out.append(real)
    return out


def parse_magnet_ids(html: str, detail_url: str = "") -> list[str]:
    """抽 ggbases 的磁力页数字 id（按出现顺序去重）。

    优先取**详情页 URL 自身的 `?id=N`**：真站实测详情页里没有
    `magnet.so?id=N` 这种 href —— 磁力是 JS 按钮 `.dbutton[bt=3]`，
    点击时才拼 `magnet.so?downid=<uuid>&id=N`。所以 N 只能从详情页
    URL 拿（`view.so?id=131080` → `131080`）。页面里若真有
    `magnet.so?id=` 链接也一并收进来（兼容别的形状）。
    """
    out: list[str] = []
    if detail_url:
        m = re.search(r"[?&]id=(\d+)", detail_url)
        if m:
            out.append(m.group(1))
    for m in MAGNET_ID_RE.finditer(html or ""):
        mid = m.group(1)
        if mid not in out:
            out.append(mid)
    return out


def build_magnet_url(hash_: str) -> str | None:
    """把裸 hash 拼成磁力链；不是合法 hex hash 就返回 None（不猜）。"""
    h = (hash_ or "").strip()
    if not MAGNET_HASH_RE.fullmatch(h):
        return None
    return f"magnet:?xt=urn:btih:{h}"


def _extract_cover(html: str) -> str | None:
    """封面三级回退：og:image → preload image → 图片 CDN id 规律。"""
    # 1. og:image，除非是已知的 React 坏字符串
    m = OG_IMAGE_RE.search(html)
    if m:
        cand = _clean(m.group(1))
        if cand and "[object Object]" not in cand and cand.startswith("http"):
            return cand
    # 2. <link rel=preload as=image>（spec 里记录的线上页来源）
    m = PRELOAD_IMG_RE.search(html)
    if m:
        cand = _clean(m.group(1))
        if cand.startswith("http"):
            return cand
    # 3. jidiyouxi topic-cover id 规律（保存下来的 fixture 只有这个可用）
    m = COVER_ID_RE.search(html)
    if m:
        return f"https://img2.52jidi.com/topic/cover/id/{m.group(1)}/sz/420"
    return None


def decode_qr_pan_links(html: str) -> list[str]:
    """从二维码图片 URL 的 data= 参数里解出被编码的网盘链接。

    注意：真实 HTML 里是 `&amp;data=`，所以必须先 unescape 再跑正则。
    """
    out: list[str] = []
    for m in QR_RE.finditer(html_mod.unescape(html)):
        raw = unquote(m.group(1))
        if any(d in raw for d in PAN_DOMAINS) or raw.startswith("magnet:"):
            out.append(raw)
    return out


_JSON_SLASH_RE = re.compile(r"\\u002[fF]")


def _decode_embedded_json(html: str) -> str:
    """还原内嵌 JSON 里的 `\\u002F` 转义斜杠。

    kungal 实测（2026-10-18）：资源页正文存在 Nuxt payload（一个巨大内联
    JSON 数组）里，链接写作

        "https:\\u002F\\u002Fpan.baidu.com\\u002Fs\\u002F1Dau8...?pwd=t7cp"

    `URL_RE = r"https?://[^\\s\\"'<>\\\\]+"` 排除反斜杠，于是整页 685 处
    `\\u002F` 一条都抽不出来。`html_mod.unescape` 只处理 `&amp;` 这类 HTML
    实体，不动 JSON 转义，所以必须单独还原。

    只替换这两个斜杠形态，不做整体 json.loads —— payload 里混着非 JSON 片段
    （函数调用、裸变量名），整体解析会失败。其他 `\\uXXXX`（如中文）保持原样：
    它们不影响 URL 识别，替换成真字符反而可能让正则窗口变复杂。
    """
    return _JSON_SLASH_RE.sub("/", html or "")


def extract_downloads(html: str, page_url: str) -> list[Download]:
    """从整页 HTML 抽下载链接。不依赖 <a> 标签 —— 这是 jidiyouxi 的关键。"""
    seen: dict[str, Download] = {}
    decoded = _decode_embedded_json(html_mod.unescape(html))

    for m in URL_RE.finditer(decoded):
        url = _trim_url(m.group(0))
        if not url or len(url) < 12:
            continue
        if QR_IMAGE_HOST_RE.search(url):
            continue  # 二维码图片；其载荷由 decode_qr_pan_links 提供
        if "/api/dl/" in url:
            continue  # gamebounty 跳板；真链由 decode_gb_dl_links 提供
        if ASSET_URL_RE.search(url):
            continue  # 图标/图片/样式等页面装饰，不是可下载的资源
        kind = _classify(url)
        if kind == "unknown":
            continue
        if url not in seen:
            seen[url] = Download(kind=kind, url=url, label=kind)

    for m in MAGNET_RE.finditer(decoded):
        url = m.group(0)
        if url not in seen:
            seen[url] = Download(kind="magnet", url=url, label="磁力")

    for url in decode_qr_pan_links(html):
        if url not in seen:
            seen[url] = Download(kind=_classify(url), url=url, label="二维码")

    for url in decode_gb_dl_links(html):
        if url not in seen:
            seen[url] = Download(kind=_classify(url), url=url, label="跳板解码")

    # 提取码：全局扫一遍，挂到没有 ?pwd= 的 pan 链接上
    codes = [c for c in CODE_RE.findall(decoded) if c]
    pan_no_pwd = [d for d in seen.values() if d.kind == "pan" and "pwd=" not in d.url]
    if codes and pan_no_pwd:
        pan_no_pwd[0].code = codes[0]

    return list(seen.values())


def extract_card(html: str, page_url: str, site_id: str) -> GameDetail:
    """抽一张结果卡：标题/封面/简介/版本/大小/日期/下载链。缺就留空，不猜。"""
    title = ""
    m = OG_TITLE_RE.search(html)
    if m:
        title = _clean(m.group(1))
    if not title:
        m = TITLE_TAG_RE.search(html)
        if m:
            title = _clean(m.group(1))

    cover = _extract_cover(html)

    intro = None
    m = OG_DESC_RE.search(html)
    if m:
        intro = _clean(m.group(1))[:1500] or None

    text = re.sub(r"<[^>]+>", " ", html)
    text = _clean(text)
    size = (SIZE_RE.search(text).group(0) if SIZE_RE.search(text) else None)
    version = (VERSION_RE.search(text).group(0) if VERSION_RE.search(text) else None)
    date = (DATE_RE.search(text).group(0) if DATE_RE.search(text) else None)

    return GameDetail(
        site_id=site_id,
        url=page_url,
        title=title,
        cover_url=cover,
        intro=intro,
        version=version,
        size=size,
        updated_at=date,
        downloads=extract_downloads(html, page_url),
    )
