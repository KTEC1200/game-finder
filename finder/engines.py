"""搜索引擎兜底链接：资源站结果不够时，给用户一个「去引擎自己搜」的出口。

用户要求（原文，m01166）：
  「如果出来的结果少于三个，在必应、百度、谷歌、Yandex也进行搜索和整合，
    不过不用给出结果，给跳转链接就行」

设计取舍（**只拼 URL**）：
  - 不发任何网络请求，因此零延迟、零反爬风险，也不会把引擎页当「结果」混进卡片；
  - 不解析引擎结果 —— 用户明确说「不用给出结果，给跳转链接就行」；
  - 查询词**原样**传给引擎（不追加 galgame / 下载），用户可以在引擎页面上自己改词。

计数口径：**有下载链接的站点数**。「站点找到了游戏但抽不到链接」（NO_DOWNLOADS /
NEEDS_LOGIN / NEEDS_GATE …）与「未找到」都不算 —— 对用户来说那都是拿不到资源。
计数单位是站点：同一站给 3 条网盘也只算 1 个。
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from .models import GameDetail

# 用户原话「少于三个」→ 少于 3 个有链接的站点就补引擎链接。
MIN_LINKED_SITES = 3


@dataclass(frozen=True)
class Engine:
    id: str
    name: str
    url_template: str

    def url_for(self, query: str) -> str:
        # safe="" 让 & # ? = / % + 全部转义；空格编码成 %20（`+` 在部分引擎里
        # 是字面加号，会搜出别的东西）。
        return self.url_template.format(q=quote(query, safe=""))


# 顺序 == 用户点名的顺序。域名与参数名都是实测的搜索入口，别凭印象改：
# 百度用 wd=（q= 也能通，但 wd= 是它自己的规范参数）。
ENGINES: tuple[Engine, ...] = (
    Engine("bing", "必应", "https://www.bing.com/search?q={q}"),
    Engine("baidu", "百度", "https://www.baidu.com/s?wd={q}"),
    Engine("google", "谷歌", "https://www.google.com/search?q={q}"),
    Engine("yandex", "Yandex", "https://yandex.com/search/?text={q}"),
)


def engine_links(query: str | None) -> list[dict]:
    """四个引擎的跳转链接。任何输入都不抛异常（空/None 也会给出干净 URL）。"""
    q = (query or "").strip()
    return [{"id": e.id, "name": e.name, "url": e.url_for(q)} for e in ENGINES]


def linked_site_count(results: list[GameDetail]) -> int:
    """有多少个**站点**给出了至少一条可用链接。

    只要求 downloads 非空且 URL 非空：`kind` 判不准（unknown）但 URL 有了，
    对用户仍然是能点的链接，不能漏。NO_RESULTS 的实测形状是 downloads=None，
    这里也要能吃下去。
    """
    n = 0
    for d in results or []:
        downloads = getattr(d, "downloads", None) or []
        if any((getattr(x, "url", None) or "").strip() for x in downloads):
            n += 1
    return n


def needs_fallback(results: list[GameDetail]) -> tuple[bool, int]:
    """(是否要补引擎链接, 有链接的站点数)。"""
    n = linked_site_count(results)
    return (n < MIN_LINKED_SITES, n)
