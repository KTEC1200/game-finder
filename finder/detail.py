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
import binascii
import hashlib
import html as html_mod
import re
from urllib.parse import unquote, urlparse

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

# 广告/客户端安装包：**不是游戏本体**，出现时绝不能算下载。
# jidiyouxi 实测：详情页 appState 里带迅雷游戏助手安装包
#   https://bj-file-xlas-down-al-game.xunlei.com/winapp/installer/Installer-1.13.0-release-100010.exe
# 它曾经被当成 direct 混进下载列表（测试 fixture 的 21 条里第 21 条）。
AD_URL_RE = re.compile(
    r"xunlei\.com/winapp/installer/|/installer/[^/]*installer[^/]*\.exe"
    r"|/winapp/[^?#]*\.exe",
    re.I,
)

# gamebounty 的下载按钮不指向文件主机本身，而是同源跳板：
#   /api/dl/{slug}/{base64url(真实URL)}
# 解码后才是 rapidgator/pixeldrain 之类的真链（实测 2026-10-18）。
GB_DL_RE = re.compile(r"https?://[^\s\"'<>\\]*/api/dl/([^/\s\"'<>\\]+)/([A-Za-z0-9_\-=]+)")

# Zibll 主题的网盘跳板（nekogal 实测）：`/?golink=<base64url>&nonce=...`，
# base64 解出来才是真网盘地址。跳板 URL 本身不能当下载链接（点它只是 302）。
GOLINK_RE = re.compile(r"[?&]golink=([A-Za-z0-9_\-=]+)")

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
    # 站方自建网盘：主机名以 `pan.` 开头（nekogal 的 pan.nekogal.top/s/xxx 实测）。
    # 通用规则，不必为每个站往 PAN_DOMAINS 里加一条。但**必须是分享路径**
    # `/s/<id>`：同一主机下的 `/f/<file>.webp` 是封面图，不是下载。
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host.startswith("pan.") and parsed.path.startswith("/s/"):
        return "pan"
    if any(d in low for d in FILEHOST_DOMAINS):
        return "filehost"
    if re.search(r"/(download|dl|down|file)", low):
        return "direct"
    # 路径本身就是个文件（带扩展名），例如 inarigal 的
    # `https://annnnnnn.soraflie.top/old/PC/%E5%88%B6%E6%9C%8D%E5%A5%B3%E5%8F%8B.rar?Authorization=...`
    # —— 站点把直链放在自家对象存储上，URL 里没有 download 之类的词。
    # 只认压缩包/镜像/可执行这三类「一定是下载物」的扩展名，
    # 避免把 .html/.php 详情页判成下载（`.webp` 封面同理已由 ASSET_URL_RE 挡掉）。
    if re.search(r"\.(?:rar|zip|7z|tar|gz|xz|iso|bin|img|apk|exe|msi|dmg)$", parsed.path, re.I):
        return "direct"
    return "unknown"


def _bencode_skip(data: bytes, i: int) -> int | None:
    """从 `i` 开始跳过一个 bencode 值，返回结束位置（不含）。

    只做「跳过」，不建对象 —— 我们唯一需要的是 info 字典的字节边界，
    然后对它整体算 SHA1。遇到不完整的数据返回 None。
    """
    if i >= len(data):
        return None
    c = data[i : i + 1]
    if c == b"i":
        j = data.find(b"e", i)
        return None if j < 0 else j + 1
    if c == b"l" or c == b"d":
        i += 1
        while True:
            if i >= len(data):
                return None
            if data[i : i + 1] == b"e":
                return i + 1
            nxt = _bencode_skip(data, i)
            if nxt is None:
                return None
            i = nxt
    if c.isdigit():
        j = data.find(b":", i)
        if j < 0:
            return None
        try:
            n = int(data[i:j])
        except ValueError:
            return None
        end = j + 1 + n
        return end if end <= len(data) else None
    return None


def torrent_info_hash(data: bytes) -> str | None:
    """算 torrent 的 info hash（info 字典的 SHA1，40 位小写十六进制）。

    byrutgame 实测（2026-10-18）：下载按钮返回 `application/x-bittorrent`，
    整页 HTML 里没有任何 `magnet:` 文本，磁力链只能由种子本地算出。
    数据不完整 / 不是 bencode 时返回 None（不猜）。
    """
    if not data or data[0:1] != b"d":
        return None
    i = 1
    while True:
        if i >= len(data):
            return None
        if data[i : i + 1] == b"e":
            return None  # 走到外层结尾也没见到 info
        # key 必须是字符串
        kend = _bencode_skip(data, i)
        if kend is None or not data[i : i + 1].isdigit():
            return None
        try:
            klen = int(data[i : data.find(b":", i)])
        except ValueError:
            return None
        key = data[data.find(b":", i) + 1 : data.find(b":", i) + 1 + klen]
        vstart = kend
        vend = _bencode_skip(data, vstart)
        if vend is None:
            return None
        if key == b"info":
            return hashlib.sha1(data[vstart:vend]).hexdigest()
        i = vend


def build_magnet_from_torrent(data: bytes) -> str | None:
    """`.torrent` 字节 → 磁力链。算不出 info hash 时返回 None。"""
    h = torrent_info_hash(data)
    return f"magnet:?xt=urn:btih:{h}" if h else None


def decode_golink(html: str) -> list[str]:
    """解 Zibll 主题的 `?golink=<base64url>` 跳板，拿到真网盘地址。

    nekogal 实测（2026-10-18）：「资源下载」区每个按钮都是
        /?golink=aHR0cHM6Ly9wYW4ubmVrb2dhbC50b3Avcy9rQVpIYQ==&nonce=...
    base64 里才是 `https://pan.nekogal.top/s/kAZHa`。整页锚点扫描拿不到真链，
    该站因此一直 NO_DOWNLOADS。解不出来就跳过（不猜）。
    """
    out: list[str] = []
    for m in GOLINK_RE.finditer(html_mod.unescape(html)):
        raw = m.group(1)
        raw += "=" * (-len(raw) % 4)
        try:
            dec = base64.urlsafe_b64decode(raw).decode("utf-8", "replace")
        except (ValueError, binascii.Error):
            continue
        dec = dec.strip()
        if not dec.startswith("http"):
            continue
        # 「游戏官网」也用 golink 包装，但它是介绍页不是下载。只留可分类的地址。
        if _classify(dec) == "unknown":
            continue
        if dec not in out:
            out.append(dec)
    return out


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
        if AD_URL_RE.search(url):
            continue  # 客户端安装包等广告，不是游戏本体
        if "golink=" in url:
            continue  # Zibll 跳板；真链由 decode_golink 提供
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

    for url in decode_golink(html):
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
