# Game Finder 实现计划（P0–P2）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个本地 Web 应用：用户输入游戏名 → 自动识别语种 → 在 22 个资源站中按语种路由做搜索 → 自动进详情页抓简介与下载链接 → 流式返回结果卡片；并定期巡检站点可用性。

**Architecture:** Python + FastAPI 起本地服务，Playwright 驱动**专用 Chrome profile**（非默认路径）抓取。搜索分 `url`（17 站，模板已由用户实测给出）与 `form`（5 站，驱动搜索框）两种模式。语种路由是纯函数层，与网络完全解耦，可离线单测。

**Tech Stack:** Python 3.14.6、FastAPI、uvicorn、Playwright 1.64.0（`channel="chrome"`）、PyYAML、pytest、SQLite（stdlib `sqlite3`）

**Spec:** `C:\Users\27025\Desktop\game-finder\docs\superpowers\specs\2026-10-16-game-finder-design.md`

## Global Constraints

以下为 spec 中已实测确认的项目级约束，**每个任务都隐含适用**：

- **Python 3.14.6**（`C:\Python314\python.exe`）；`playwright==1.64.0`、`fastapi`、`uvicorn`、`pyyaml`、`pytest` 均已装可用。**不要**创建 3.12 venv。
- **Chrome**：`C:\Program Files\Google\Chrome\Application\chrome.exe`，版本 155.0.8059.80。
- **浏览器 profile 必须是专用非默认路径**：`<project>/chrome-profile/`。用 Chrome 默认 user-data-dir 会被拒绝开启 DevTools（Chrome ≥136 限制）。
- **代理必须显式传**：`proxy={"server": "http://127.0.0.1:6234"}`。不要依赖 Chrome 继承系统代理（会挂 jidiyouxi）。
- **UA 必须显式设置**为真实 Chrome UA。headless 默认 UA 会被 Cloudflare 拦（ankergames / iacg 实测 403）。
- **站点总数 22**：`url` 模式 17 站 + `form` 模式 5 站。语种覆盖 zh=17 / en=18 / ja=12。
- **Windows 控制台是 GBK**：任何脚本**禁止** `print()` 页面标题/正文（含 emoji 会 `UnicodeEncodeError` 崩溃）。结果一律写 UTF-8 文件，stdout 只打 ASCII。
- **不要在 pwsh 命令里写 CJK 字面量**（GBK 控制台乱码），让 Python 从常量/文件读取。
- **不要传 `sandbox_permissions`**（本机审批已禁用，带该参数会被自动拒绝）。
- **验收看产物，不看退出码**：数产物文件/断言内容，`exit code 0` 不作成功判据。

---

## File Structure

```
game-finder/
  app.py                      # 入口：起 uvicorn + 打开浏览器标签页
  config.yaml                 # 代理/超时/并发/端口/缓存TTL/巡检间隔/探测词
  sites.yaml                  # 22 站注册表（含 langs / mode / url_template）
  finder/
    __init__.py
    models.py                 # Site / SearchSpec / SearchHit / GameDetail / Download / HealthRecord
    lang.py                   # detect_lang() / filter_sites_by_lang()  ← 纯函数
    sites.py                  # load_sites() → list[Site]；校验
    browser.py                # Chrome 生命周期、UA、代理、页面池
    search.py                 # url 模式 + form 模式
    detail.py                 # 详情页抽取
    store.py                  # SQLite 缓存 + 健康历史
    health.py                 # 巡检状态机
    web/
      __init__.py
      server.py               # FastAPI 路由 + SSE
      static/index.html       # 单页界面
  tests/
    fixtures/                 # 已有 8 份真实页面快照
    test_lang.py
    test_sites_yaml.py
    test_models.py
    test_search_parse.py
    test_detail_parse.py
    test_store.py
    test_health.py
  tools/
    smoke_live.py             # 手动真站冒烟
```

**任务边界说明**：`lang.py` 是纯函数、零依赖，单独成任务并先做 —— 它是语种路由的核心，且能立刻用 TDD 验证。`browser.py` 依赖 Playwright 但可离线验证「参数正确性」。搜索/详情抽取依赖 fixture，可完全离线测试。

---

### Task 1: 项目骨架与依赖自检

**Files:**
- Create: `finder/__init__.py`, `finder/web/__init__.py`
- Create: `tests/__init__.py`
- Create: `config.yaml`
- Create: `requirements.txt`
- Test: `tests/test_env.py`

**Interfaces:**
- Consumes: 无
- Produces: 可导入的 `finder` 包；`config.yaml` 含键 `proxy.server`、`browser.headless`、`browser.chrome_path`、`browser.profile_dir`、`search.timeout_ms`、`search.page_pool`、`cache.ttl_hours`、`health.interval_hours`、`health.probe_words.{zh,en,ja}`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_env.py
"""Environment sanity: the three things every later task assumes."""
from pathlib import Path
import yaml

PROJECT = Path(__file__).resolve().parent.parent


def test_project_importable():
    import finder
    assert finder.__file__.endswith("__init__.py")


def test_config_yaml_has_required_keys():
    cfg = yaml.safe_load((PROJECT / "config.yaml").read_text(encoding="utf-8"))
    assert cfg["proxy"]["server"] == "http://127.0.0.1:6234"
    assert cfg["browser"]["headless"] is True
    assert Path(cfg["browser"]["chrome_path"]).exists()
    assert cfg["search"]["timeout_ms"] > 0
    assert cfg["cache"]["ttl_hours"] > 0
    assert set(cfg["health"]["probe_words"]) == {"zh", "en", "ja"}


def test_playwright_importable():
    import playwright  # noqa: F401
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd "C:\Users\27025\Desktop\game-finder"; python -m pytest tests/test_env.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'finder'` 与 `FileNotFoundError: config.yaml`

- [ ] **Step 3: 建骨架与配置**

```bash
mkdir finder finder\web tests
```

`finder/__init__.py`（空文件即可，但写一行版本号便于断言）：
```python
"""Game Finder —— 游戏资源检索器。"""
__version__ = "0.1.0"
```

`finder/web/__init__.py` 与 `tests/__init__.py`：空文件。

`config.yaml`：
```yaml
proxy:
  enabled: true
  server: "http://127.0.0.1:6234"

browser:
  chrome_path: 'C:\Program Files\Google\Chrome\Application\chrome.exe'
  profile_dir: "chrome-profile"
  headless: true
  # 留空则启动时从 chrome.exe 动态读取真实版本拼 UA
  user_agent: ""

search:
  timeout_ms: 45000
  detail_timeout_ms: 45000
  page_pool: 4
  min_interval_ms: 1500
  max_detail_pages: 1

cache:
  ttl_hours: 12

health:
  interval_hours: 6
  start_delay_s: 60
  probe_words:
    zh: "终焉之莉莉"
    en: "enderlilies"
    ja: "制服カノジョ"

server:
  host: "127.0.0.1"
  port: 8734
```

`requirements.txt`：
```
fastapi
uvicorn
playwright==1.64.0
pyyaml
pytest
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd "C:\Users\27025\Desktop\game-finder"; python -m pytest tests/test_env.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
cd "C:\Users\27025\Desktop\game-finder"
git init
git add finder/__init__.py finder/web/__init__.py tests/__init__.py config.yaml requirements.txt tests/test_env.py
git commit -m "chore: project skeleton, config, env sanity tests"
```

---

### Task 2: 语种判定纯函数

**Files:**
- Create: `finder/lang.py`
- Test: `tests/test_lang.py`

**Interfaces:**
- Consumes: 无（纯标准库 `re`）
- Produces:
  - `detect_lang(text: str) -> str` 返回 `"zh" | "en" | "ja"`
  - `KANA_RE`, `CJK_RE` 模块级正则常量

- [ ] **Step 1: 写失败测试**

```python
# tests/test_lang.py
import pytest
from finder.lang import detect_lang


@pytest.mark.parametrize("text,expected", [
    # 中文：CJK 汉字，无假名
    ("终焉之莉莉", "zh"),
    ("千恋万花", "zh"),
    ("赛博朋克2077", "zh"),
    # 英文：无 CJK 无假名
    ("enderlilies", "en"),
    ("ENDER LILIES", "en"),
    ("Ender-Lilies", "en"),
    ("café 123", "en"),
    # 日文：含假名（优先于 CJK）
    ("終焉のリリィ", "ja"),
    ("リリィ", "ja"),
    ("サクラノ詩", "ja"),
    # 混排：假名优先 → ja
    ("ENDER LILIES 終焉のリリィ", "ja"),
    # 混排：中英无假名 → zh（CJK 优先于拉丁）
    ("Ender Lilies 终焉之莉莉", "zh"),
    # 边界：空与纯空白 → en（无 CJK 特征）
    ("", "en"),
    ("   ", "en"),
    ("123", "en"),
])
def test_detect_lang(text, expected):
    assert detect_lang(text) == expected


def test_detect_lang_accepts_none_like_whitespace():
    """前后空白不影响判定。"""
    assert detect_lang("  终焉之莉莉  ") == "zh"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd "C:\Users\27025\Desktop\game-finder"; python -m pytest tests/test_lang.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'finder.lang'`

- [ ] **Step 3: 写最小实现**

```python
# finder/lang.py
"""语种判定 —— 纯函数，无网络无 IO，可离线单测。

规则（与 spec §2.1.5 一致）：
  含日文假名            -> "ja"
  否则含 CJK 汉字       -> "zh"
  否则                  -> "en"
假名优先于汉字，因为日文常混用汉字；中英混排无假名时判为中文。
"""
from __future__ import annotations

import re

# 平假名 U+3040-U+309F + 片假名 U+30A0-U+30FF
KANA_RE = re.compile(r"[\u3040-\u30ff]")
# CJK 统一表意文字
CJK_RE = re.compile(r"[\u4e00-\u9fff]")

SUPPORTED_LANGS = ("zh", "en", "ja")


def detect_lang(text: str) -> str:
    """判定输入文本的语种，返回 'zh' | 'en' | 'ja'。"""
    if not text:
        return "en"
    if KANA_RE.search(text):
        return "ja"
    if CJK_RE.search(text):
        return "zh"
    return "en"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd "C:\Users\27025\Desktop\game-finder"; python -m pytest tests/test_lang.py -v`
Expected: 12 passed

- [ ] **Step 5: 提交**

```bash
cd "C:\Users\27025\Desktop\game-finder"
git add finder/lang.py tests/test_lang.py
git commit -m "feat(lang): language detection pure function with edge cases"
```

---

### Task 3: 数据模型与站点注册表

**Files:**
- Create: `finder/models.py`
- Create: `sites.yaml`
- Create: `finder/sites.py`
- Test: `tests/test_models.py`
- Test: `tests/test_sites_yaml.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `models.Site`（字段见下）、`models.SearchSpec`、`models.SearchHit`、`models.Download`、`models.GameDetail`、`models.HealthRecord`
  - `sites.load_sites(path: Path | None = None) -> list[Site]`
  - `sites.filter_sites_by_lang(all_sites: list[Site], lang: str) -> tuple[list[Site], list[Site]]` 返回 `(参与, 跳过)`

- [ ] **Step 1: 写失败测试（模型）**

```python
# tests/test_models.py
from finder.models import Site, SearchSpec, Download, GameDetail


def test_site_langs_is_a_set_of_supported_codes():
    s = Site(
        id="gamer520", name="Gamer520", homepage="https://www.gamer520.com/",
        kinds=["网盘"], langs={"zh", "en"}, url_searchable=True,
        search=SearchSpec(mode="url", url_template="https://www.gamer520.com/?s={q}"),
    )
    assert s.langs == {"zh", "en"}
    assert s.adapter_status == "untested"   # 默认值
    assert s.needs_login is False           # 默认值
    assert s.max_query_len is None          # 默认值


def test_search_spec_form_mode_allows_no_template():
    spec = SearchSpec(mode="form", input_selector="input#s")
    assert spec.mode == "form"
    assert spec.url_template is None


def test_download_kind_is_constrained():
    d = Download(kind="pan", url="https://pan.baidu.com/s/abc", label="百度网盘", code="1234")
    assert d.kind == "pan"
    assert d.code == "1234"


def test_game_detail_defaults():
    g = GameDetail(site_id="x", url="https://e.com/1", title="t")
    assert g.downloads == []
    assert g.intro is None
    assert g.extra == {}
```

- [ ] **Step 2: 运行确认失败**

Run: `cd "C:\Users\27025\Desktop\game-finder"; python -m pytest tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'finder.models'`

- [ ] **Step 3: 实现 models.py**

```python
# finder/models.py
"""数据模型。全部用 dataclass，无第三方依赖。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Lang = Literal["zh", "en", "ja"]
SearchMode = Literal["url", "form"]
DownloadKind = Literal["direct", "pan", "magnet", "unknown"]
AdapterStatus = Literal["verified", "untested", "broken"]


@dataclass
class SearchSpec:
    mode: SearchMode
    url_template: str | None = None          # mode="url" 时必需，含 {q}
    input_selector: str | None = None        # mode="form"
    submit_selector: str | None = None
    result_link_selector: str | None = None
    title_selector: str | None = None


@dataclass
class Site:
    id: str
    name: str
    homepage: str
    kinds: list[str]
    langs: set[str]
    url_searchable: bool
    search: SearchSpec
    tags: set[str] = field(default_factory=set)
    needs_login: bool = False
    max_query_len: int | None = None
    adapter_status: AdapterStatus = "untested"
    # 仅当 headless+真实UA 仍被 Cloudflare 拦时置 True，该站改用 headful
    force_headful: bool = False


@dataclass
class SearchHit:
    site_id: str
    title: str
    url: str
    score: float = 0.0


@dataclass
class Download:
    kind: DownloadKind
    url: str
    label: str = ""
    code: str | None = None


@dataclass
class GameDetail:
    site_id: str
    url: str
    title: str
    cover_url: str | None = None
    intro: str | None = None
    version: str | None = None
    size: str | None = None
    updated_at: str | None = None
    downloads: list[Download] = field(default_factory=list)
    error: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class HealthRecord:
    site_id: str
    status: str                  # ok / degraded / unreachable / needs_proxy / ...
    latency_ms: int = 0
    reason: str = ""
    checked_at: str = ""         # ISO8601
```

- [ ] **Step 4: 写失败测试（注册表）**

```python
# tests/test_sites_yaml.py
from pathlib import Path
import pytest
from finder.sites import load_sites

PROJECT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def sites():
    return load_sites(PROJECT / "sites.yaml")


def test_loads_all_22_sites(sites):
    assert len(sites) == 22


def test_ids_are_unique(sites):
    ids = [s.id for s in sites]
    assert len(ids) == len(set(ids))


def test_mode_counts_match_spec(sites):
    url = [s for s in sites if s.search.mode == "url"]
    form = [s for s in sites if s.search.mode == "form"]
    assert len(url) == 17, f"expected 17 url-mode, got {len(url)}: {[s.id for s in url]}"
    assert len(form) == 5, f"expected 5 form-mode, got {len(form)}: {[s.id for s in form]}"
    assert {s.id for s in form} == {
        "gamebounty", "sayafx", "touchgal", "zi0", "anime-sharing"
    }


def test_url_mode_always_has_template(sites):
    for s in sites:
        if s.search.mode == "url":
            assert s.search.url_template, f"{s.id} url mode needs url_template"
            assert "{q}" in s.search.url_template, f"{s.id} template needs {{q}}"


def test_url_searchable_agrees_with_mode(sites):
    for s in sites:
        assert s.url_searchable == (s.search.mode == "url"), f"{s.id} mismatch"


def test_langs_are_valid(sites):
    for s in sites:
        assert s.langs, f"{s.id} needs at least one lang"
        assert s.langs <= {"zh", "en", "ja"}, f"{s.id} bad langs {s.langs}"


def test_language_coverage_counts(sites):
    """spec §2.1.5 已核算：zh=17 / en=18 / ja=12。"""
    for lang, expected in (("zh", 17), ("en", 18), ("ja", 12)):
        got = sum(1 for s in sites if lang in s.langs)
        assert got == expected, f"{lang}: expected {expected}, got {got}"


def test_known_specials(sites):
    by_id = {s.id: s for s in sites}
    assert by_id["acggw"].max_query_len == 10, "ACG 港湾 搜索词 ≤10"
    assert by_id["galgame.dev"].needs_login is True, "真红需登录"
    assert "jidiyouxi" in by_id and by_id["jidiyouxi"].langs == {"zh"}


def test_filter_by_lang_returns_participating_and_skipped(sites):
    from finder.sites import filter_sites_by_lang
    part, skipped = filter_sites_by_lang(sites, "ja")
    assert len(part) == 12
    assert len(part) + len(skipped) == 22
    assert all("ja" in s.langs for s in part)
    assert all("ja" not in s.langs for s in skipped)
```

- [ ] **Step 5: 运行确认失败**

Run: `cd "C:\Users\27025\Desktop\game-finder"; python -m pytest tests/test_sites_yaml.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'finder.sites'` / `FileNotFoundError: sites.yaml`

- [ ] **Step 6: 写 sites.yaml（22 站，数据来自 spec §3）**

```yaml
# 站点注册表。来源：C:\Users\27025\Desktop\网站链接（更新）.md（2026-10-17 用户实测）
# mode=url 表示地址栏可用（用户给出模板）；mode=form 表示只能站内搜索。
# langs 来自用户逐站标注。url_searchable 必须与 mode 一致。

sites:
  # ===== 单机（7）=====
  - id: jidiyouxi
    name: 机地
    homepage: "https://www.jidiyouxi.com/"
    kinds: [网盘]
    langs: [zh]
    search:
      mode: url
      url_template: "https://www.jidiyouxi.com/search/detail/{q}"

  - id: playzip
    name: PLAYZIP
    homepage: "https://playzip.com/"
    kinds: [直链]
    langs: [en]
    search:
      mode: url
      url_template: "https://playzip.com/?keywords={q}"

  - id: byrutgame
    name: BYRUTOP
    homepage: "https://byrutgame.org/"
    kinds: [直链, 磁力]
    langs: [en]
    search:
      mode: url
      url_template: "https://byrutgame.org/index.php?do=search&subaction=search&search_start=0&full_search=0&story={q}"

  - id: gamer520
    name: Gamer520
    homepage: "https://www.gamer520.com/"
    kinds: [网盘]
    langs: [zh, en]
    search:
      mode: url
      url_template: "https://www.gamer520.com/?s={q}"

  - id: ankergames
    name: ANKERGAMES
    homepage: "https://ankergames.net/"
    kinds: [直链, 磁力]
    langs: [en]
    search:
      mode: url
      url_template: "https://ankergames.net/search/{q}"

  - id: gamebounty
    name: GAMEBOUNTY
    homepage: "https://gamebounty.world/zh"
    kinds: [直链]
    langs: [zh, en]
    search:
      mode: form
      input_selector: null

  - id: flysheep
    name: flysheep 资源避难所
    homepage: "https://www.flysheep6.com/"
    kinds: [网盘, 磁力]
    langs: [zh, en]
    search:
      mode: url
      url_template: "https://www.flysheep6.com/?s={q}"

  # ===== Galgame（15）=====
  - id: sayafx
    name: 月谣
    homepage: "https://www.sayafx.top/"
    kinds: [直链, 网盘]
    langs: [zh, ja]
    search:
      mode: form
      input_selector: null

  - id: nyaa
    name: Nyaa
    homepage: "https://sukebei.nyaa.si/"
    kinds: [磁力]
    langs: [en, ja]
    search:
      mode: url
      url_template: "https://sukebei.nyaa.si/?f=0&c=1_3&q={q}"

  - id: nysoure
    name: Nysoure
    homepage: "https://nysoure.com/"
    kinds: [直链]
    langs: [zh, en, ja]
    search:
      mode: url
      url_template: "https://nysoure.com/search?keyword={q}&sort=8"

  - id: iacg
    name: 爱之列车
    homepage: "https://iacg.love/"
    kinds: [网盘]
    langs: [zh, en]
    search:
      mode: url
      url_template: "https://iacg.love/?s={q}&type=post&trem=4"

  - id: inarigal
    name: 稻荷 GAL
    homepage: "https://inarigal.com/"
    kinds: [直链]
    langs: [zh, ja]
    search:
      mode: url
      url_template: "https://inarigal.com/?search={q}"

  - id: lzacg
    name: 量子 ACG
    homepage: "https://lzacg.cc/"
    kinds: [直链]
    langs: [zh]
    search:
      mode: url
      url_template: "https://lzacg.cc/?s={q}"

  - id: acggw
    name: ACG 港湾
    homepage: "https://www.acggw.me/"
    kinds: [网盘]
    langs: [zh, en]
    max_query_len: 10
    search:
      mode: url
      url_template: "https://www.acggw.me/?post_type=post&s={q}"

  - id: nekogal
    name: NekoGAL
    homepage: "https://www.nekogal.com/"
    kinds: [直链]
    langs: [zh, en, ja]
    search:
      mode: url
      url_template: "https://www.nekogal.com/?s={q}"

  - id: ggbases
    name: GGBases
    homepage: "https://ggbases.dlgal.com/"
    kinds: [磁力]
    langs: [en, ja]
    search:
      mode: url
      url_template: "https://ggbases.dlgal.com/search.so?p=0&title={q}"

  - id: touchgal
    name: TouchGal
    homepage: "https://www.touchgal.ink/"
    kinds: [直链, 网盘]
    langs: [zh, en, ja]
    search:
      mode: form
      input_selector: null

  - id: galgamex
    name: Galgamex
    homepage: "https://www.galgamex.net/"
    kinds: [直链, 网盘]
    langs: [zh, en, ja]
    search:
      mode: url
      url_template: "https://www.galgamex.net/search?q={q}"

  - id: kungal
    name: 鲲 Galgame
    homepage: "https://www.kungal.com/"
    kinds: [论坛网盘]
    langs: [zh, en, ja]
    search:
      mode: url
      url_template: "https://www.kungal.com/search?keywords={q}"

  - id: zi0
    name: 梓澪的妙妙屋
    homepage: "https://zi0.cc/"
    kinds: [直链]
    langs: [zh, en, ja]
    search:
      mode: form
      input_selector: null

  - id: anime-sharing
    name: Anime-Sharing
    homepage: "https://www.anime-sharing.com/"
    kinds: [直链]
    langs: [zh, en, ja]
    search:
      mode: form
      input_selector: null

  - id: galgame.dev
    name: 真红的资源讨论组
    homepage: "https://galgame.dev/"
    kinds: [论坛网盘, 直链]
    langs: [zh, en, ja]
    needs_login: true
    search:
      mode: url
      url_template: "https://galgame.dev/search?term={q}&in=titles"
```

- [ ] **Step 7: 实现 sites.py**

```python
# finder/sites.py
"""载入并校验站点注册表。"""
from __future__ import annotations

from pathlib import Path

import yaml

from .models import SearchSpec, Site

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "sites.yaml"


def load_sites(path: Path | str | None = None) -> list[Site]:
    p = Path(path) if path else DEFAULT_PATH
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    out: list[Site] = []
    for item in raw["sites"]:
        s = item["search"]
        spec = SearchSpec(
            mode=s["mode"],
            url_template=s.get("url_template"),
            input_selector=s.get("input_selector"),
            submit_selector=s.get("submit_selector"),
            result_link_selector=s.get("result_link_selector"),
            title_selector=s.get("title_selector"),
        )
        out.append(
            Site(
                id=item["id"],
                name=item["name"],
                homepage=item["homepage"],
                kinds=list(item.get("kinds") or []),
                langs=set(item.get("langs") or []),
                url_searchable=(spec.mode == "url"),
                search=spec,
                tags=set(item.get("tags") or []),
                needs_login=bool(item.get("needs_login", False)),
                max_query_len=item.get("max_query_len"),
                adapter_status=item.get("adapter_status", "untested"),
                force_headful=bool(item.get("force_headful", False)),
            )
        )
    return out


def filter_sites_by_lang(
    all_sites: list[Site], lang: str
) -> tuple[list[Site], list[Site]]:
    """按语种分流。返回 (参与搜索的站点, 被跳过的站点)。"""
    part = [s for s in all_sites if lang in s.langs]
    skipped = [s for s in all_sites if lang not in s.langs]
    return part, skipped
```

- [ ] **Step 8: 运行全部新测试确认通过**

Run: `cd "C:\Users\27025\Desktop\game-finder"; python -m pytest tests/test_models.py tests/test_sites_yaml.py -v`
Expected: 全部 PASS（models 4 + sites 9）

- [ ] **Step 9: 提交**

```bash
cd "C:\Users\27025\Desktop\game-finder"
git add finder/models.py finder/sites.py sites.yaml tests/test_models.py tests/test_sites_yaml.py
git commit -m "feat(sites): models + 22-site registry + lang filtering"
```

---

### Task 4: 浏览器层（专用 profile + UA + 代理）

**Files:**
- Create: `finder/browser.py`
- Test: `tests/test_browser.py`

**Interfaces:**
- Consumes: `config.yaml` 的 `browser.*`、`proxy.*`；`models.Site.force_headful`
- Produces:
  - `browser.read_chrome_version(chrome_path: str) -> str` 返回如 `"155.0.8059.80"`
  - `browser.build_user_agent(chrome_version: str) -> str`
  - `browser.resolve_profile_dir(project_root: Path, configured: str) -> Path`
  - `BrowserSession` 上下文管理器，属性 `.context`、`.new_page()`、`.close()`

- [ ] **Step 1: 写失败测试（纯函数部分，不需真启动浏览器）**

```python
# tests/test_browser.py
from pathlib import Path
import pytest
from finder.browser import build_user_agent, resolve_profile_dir

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def test_build_user_agent_uses_real_version():
    ua = build_user_agent("155.0.8059.80")
    assert "Chrome/155.0.0.0" in ua
    assert "Windows NT 10.0; Win64; x64" in ua
    assert ua.startswith("Mozilla/5.0")
    # 绝不能出现 headless 标记
    assert "Headless" not in ua


def test_resolve_profile_dir_is_not_chrome_default(tmp_path):
    p = resolve_profile_dir(tmp_path, "chrome-profile")
    assert p == tmp_path / "chrome-profile"
    # 关键：绝不能等于 Chrome 默认 user-data-dir
    default = Path.home() / "AppData" / "Local" / "Google" / "Chrome" / "User Data"
    assert p != default
    assert "Google/Chrome" not in str(p).replace("\\", "/")


def test_read_chrome_version_from_real_binary():
    from finder.browser import read_chrome_version
    if not Path(CHROME).exists():
        pytest.skip("chrome not installed")
    v = read_chrome_version(CHROME)
    assert v.count(".") >= 2
    assert v.split(".")[0].isdigit()
```

- [ ] **Step 2: 运行确认失败**

Run: `cd "C:\Users\27025\Desktop\game-finder"; python -m pytest tests/test_browser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'finder.browser'`

- [ ] **Step 3: 实现 browser.py**

```python
# finder/browser.py
"""Chrome 生命周期。

三条实测硬约束（见 spec §2.1.1/§2.1.2/§2.1.4）：
  1. profile 必须是非默认路径，否则 Chrome 拒绝开 DevTools
  2. 代理必须显式传 http://127.0.0.1:6234
  3. UA 必须显式设真实 Chrome UA，否则 headless 被 Cloudflare 拦
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

from .models import Site

DEFAULT_CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
ANTI_BOT_ARGS = ["--disable-blink-features=AutomationControlled"]


def read_chrome_version(chrome_path: str) -> str:
    """从 chrome.exe 读真实版本号；失败回退到注册表/常量。"""
    try:
        out = subprocess.run(
            [chrome_path, "--version"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        # "Google Chrome 155.0.8059.80"
        for tok in out.split():
            if tok and tok[0].isdigit() and tok.count(".") >= 2:
                return tok
    except Exception:  # noqa: BLE001
        pass
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Google\Chrome\BLBeacon",
        )
        v, _ = winreg.QueryValueEx(key, "version")
        return str(v)
    except Exception:  # noqa: BLE001
        return "155.0.0.0"


def build_user_agent(chrome_version: str) -> str:
    """拼真实 Chrome UA。major 版本 + .0.0.0 是 Chrome 的惯例写法。"""
    major = chrome_version.split(".")[0]
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{major}.0.0.0 Safari/537.36"
    )


def resolve_profile_dir(project_root: Path, configured: str) -> Path:
    """专用 profile 目录。绝不允许落到 Chrome 默认 user-data-dir。"""
    p = Path(configured)
    if not p.is_absolute():
        p = project_root / p
    return p


class BrowserSession:
    """包装 launch_persistent_context，统一注入 UA / 代理 / 反检测参数。"""

    def __init__(self, config: dict[str, Any], project_root: Path,
                 headful_override: bool = False):
        self._cfg = config
        self._root = project_root
        self._headful_override = headful_override
        self._pw = None
        self._ctx = None

    def __enter__(self) -> "BrowserSession":
        from playwright.sync_api import sync_playwright

        b = self._cfg["browser"]
        chrome_path = b.get("chrome_path") or DEFAULT_CHROME
        if not Path(chrome_path).exists():
            raise FileNotFoundError(f"chrome not found: {chrome_path}")

        profile = resolve_profile_dir(self._root, b["profile_dir"])
        profile.mkdir(parents=True, exist_ok=True)

        ua = b.get("user_agent") or build_user_agent(read_chrome_version(chrome_path))
        headless = b.get("headless", True) and not self._headful_override

        kwargs: dict[str, Any] = {
            "user_data_dir": str(profile),
            "channel": "chrome",
            "executable_path": chrome_path,
            "headless": headless,
            "user_agent": ua,
            "args": ANTI_BOT_ARGS,
        }
        px = self._cfg.get("proxy") or {}
        if px.get("enabled") and px.get("server"):
            kwargs["proxy"] = {"server": px["server"]}

        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(**kwargs)
        return self

    @property
    def context(self):
        return self._ctx

    def new_page(self):
        return self._ctx.new_page()

    def __exit__(self, *exc) -> None:
        try:
            if self._ctx:
                self._ctx.close()
        finally:
            if self._pw:
                self._pw.stop()
```

- [ ] **Step 4: 运行确认通过**

Run: `cd "C:\Users\27025\Desktop\game-finder"; python -m pytest tests/test_browser.py -v`
Expected: 3 passed

- [ ] **Step 5: 真启动冒烟（手动，验证 profile/UA/代理真的能用）**

```bash
cd "C:\Users\27025\Desktop\game-finder"
python -c "import yaml,pathlib;from finder.browser import BrowserSession;cfg=yaml.safe_load(open('config.yaml',encoding='utf-8'));root=pathlib.Path('.').resolve();s=BrowserSession(cfg,root).__enter__();p=s.new_page();p.goto('https://www.gamer520.com/',timeout=45000);print('TITLE_LEN',len(p.title()));print('UA',p.evaluate('navigator.userAgent'));s.__exit__()"
```
Expected: 打印 `TITLE_LEN` > 0 且 `UA` 含 `Chrome/155`、不含 `Headless`。

- [ ] **Step 6: 提交**

```bash
cd "C:\Users\27025\Desktop\game-finder"
git add finder/browser.py tests/test_browser.py
git commit -m "feat(browser): dedicated profile + real UA + explicit proxy"
```

---

### Task 5: 详情页抽取（离线 fixture 驱动）

**Files:**
- Create: `finder/detail.py`
- Test: `tests/test_detail_parse.py`

**Interfaces:**
- Consumes: `models.GameDetail`、`models.Download`
- Produces:
  - `detail.extract_downloads(html: str, page_url: str) -> list[Download]`
  - `detail.extract_card(html: str, page_url: str, site_id: str) -> GameDetail`
  - `detail.decode_qr_pan_links(html: str) -> list[str]`

**关键实测依据**（spec §2.1.3）：jidiyouxi 的网盘链接**不在 `<a>` 标签里**，只在整页 HTML 的 SSR JSON 中；gamer520 的链接藏在二维码 `data=` 参数里；jidiyouxi 的 `og:image` 是坏字符串 `"[object Object]"`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_detail_parse.py
from pathlib import Path
import pytest
from finder.detail import extract_card, extract_downloads, decode_qr_pan_links

FIX = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="module")
def jidi_html():
    return (FIX / "jidiyouxi" / "detail_xingxing.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def g520_landing_html():
    return (FIX / "gamer520" / "go_landing_sample.html").read_text(encoding="utf-8")


def test_jidi_downloads_found_outside_anchor_tags(jidi_html):
    """核心回归：链接在整页 HTML 里，不在 <a> 标签里。"""
    dl = extract_downloads(jidi_html, "https://www.jidiyouxi.com/topic/detail/171085167")
    assert len(dl) >= 10, f"expected many pan links, got {len(dl)}"
    assert all(d.kind == "pan" for d in dl)
    assert any("pan.baidu.com" in d.url for d in dl)
    assert any("pan.quark.cn" in d.url for d in dl)


def test_jidi_download_urls_have_pwd_or_code(jidi_html):
    dl = extract_downloads(jidi_html, "https://www.jidiyouxi.com/topic/detail/171085167")
    with_pwd = [d for d in dl if "pwd=" in d.url]
    assert with_pwd, "expected ?pwd= on baidu/xunlei links"


def test_jidi_cover_is_not_the_broken_og_image(jidi_html):
    """og:image 是 '[object Object]'，必须回退到 preload link。"""
    card = extract_card(jidi_html, "https://www.jidiyouxi.com/topic/detail/171085167",
                        "jidiyouxi")
    assert card.cover_url is not None
    assert "[object Object]" not in card.cover_url
    assert card.cover_url.startswith("http")


def test_jidi_card_has_title_and_intro(jidi_html):
    card = extract_card(jidi_html, "https://www.jidiyouxi.com/topic/detail/171085167",
                        "jidiyouxi")
    assert card.title and len(card.title) > 4
    assert card.intro and len(card.intro) > 20
    assert card.site_id == "jidiyouxi"


def test_g520_landing_links_extracted(g520_landing_html):
    dl = extract_downloads(g520_landing_html, "https://520.gamers520.com/41170.html")
    assert dl, "landing page must yield download links"
    kinds = {d.kind for d in dl}
    assert "pan" in kinds


def test_qr_encoded_pan_links_are_decoded(g520_landing_html):
    """gamer520 用 api.qrserver.com?...&data=<urlencoded> 藏链接。"""
    urls = decode_qr_pan_links(g520_landing_html)
    assert urls, "expected QR-embedded pan urls"
    assert any("pan.baidu.com" in u or "pan.quark.cn" in u for u in urls)


def test_empty_html_is_safe():
    card = extract_card("<html><body></body></html>", "https://x.com/", "x")
    assert card.downloads == []
    assert card.title == ""
```

- [ ] **Step 2: 运行确认失败**

Run: `cd "C:\Users\27025\Desktop\game-finder"; python -m pytest tests/test_detail_parse.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'finder.detail'`

- [ ] **Step 3: 实现 detail.py**

```python
# finder/detail.py
"""详情页抽取。

实测要点（spec §2.1.3）：
  - jidiyouxi 的网盘链接不在 <a> 标签，只在整页 HTML → 必须对 outerHTML 跑正则
  - jidiyouxi 的 og:image 是坏字符串 "[object Object]" → 回退 <link rel=preload as=image>
  - gamer520 落地页用二维码藏链接 → 解 data= 参数
"""
from __future__ import annotations

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

# 整页 HTML 里抓 pan/magnet 链接。排除紧跟的引号/反斜杠，避免把 JSON 转义带进来。
URL_RE = re.compile(
    r"https?://[^\s\"'<>\\]+",
)
MAGNET_RE = re.compile(r"magnet:\?xt=urn:btih:[a-zA-Z0-9]+")
CODE_RE = re.compile(r"(?:提取码|密码|访问码|pwd)\s*[:：=]?\s*([a-zA-Z0-9]{4,8})")
QR_RE = re.compile(
    r"https?://[^\s\"'<>\\]*qrserver[^\s\"'<>\\]*[?&]data=([^&\"'<>\\]+)"
)
PRELOAD_IMG_RE = re.compile(
    r'<link[^>]+rel=["\']preload["\'][^>]+as=["\']image["\'][^>]+href=["\']([^"\']+)',
    re.I,
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


def _classify(url: str) -> str:
    low = url.lower()
    if low.startswith("magnet:"):
        return "magnet"
    if any(d in low for d in PAN_DOMAINS):
        return "pan"
    if re.search(r"/(download|dl|down|file)", low):
        return "direct"
    return "unknown"


def decode_qr_pan_links(html: str) -> list[str]:
    """从二维码图片 URL 的 data= 参数里解出被编码的网盘链接。"""
    out: list[str] = []
    for m in QR_RE.finditer(html):
        raw = unquote(html_mod.unescape(m.group(1)))
        if any(d in raw for d in PAN_DOMAINS) or raw.startswith("magnet:"):
            out.append(raw)
    return out


def extract_downloads(html: str, page_url: str) -> list[Download]:
    """从整页 HTML 抽下载链接。不依赖 <a> 标签 —— 这是 jidiyouxi 的关键。"""
    seen: dict[str, Download] = {}
    decoded = html_mod.unescape(html)

    for m in URL_RE.finditer(decoded):
        url = m.group(0).rstrip(".,);]")
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

    cover = None
    m = OG_IMAGE_RE.search(html)
    if m:
        cand = _clean(m.group(1))
        # 已知 jidiyouxi 的 og:image 是坏字符串
        if cand and "[object Object]" not in cand and cand.startswith("http"):
            cover = cand
    if cover is None:
        m = PRELOAD_IMG_RE.search(html)
        if m:
            cand = _clean(m.group(1))
            if cand.startswith("http"):
                cover = cand

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
```

- [ ] **Step 4: 运行确认通过**

Run: `cd "C:\Users\27025\Desktop\game-finder"; python -m pytest tests/test_detail_parse.py -v`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
cd "C:\Users\27025\Desktop\game-finder"
git add finder/detail.py tests/test_detail_parse.py
git commit -m "feat(detail): whole-HTML pan extraction, QR decode, broken-og:image fallback"
```

---

### Task 6: 搜索层（url + form 双模式）

**Files:**
- Create: `finder/search.py`
- Test: `tests/test_search_parse.py`

**Interfaces:**
- Consumes: `models.Site`、`models.SearchHit`、`finder.detail`
- Produces:
  - `search.build_search_url(site: Site, query: str) -> str`
  - `search.clamp_query(site: Site, query: str) -> tuple[str, bool]` 返回 `(实际查询词, 是否被截断)`
  - `search.parse_result_links(html: str, page_url: str, site: Site) -> list[SearchHit]`
  - `search.pick_best(hits: list[SearchHit], query: str) -> SearchHit | None`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_search_parse.py
from pathlib import Path
import pytest
from finder.models import SearchSpec, Site
from finder.search import (
    build_search_url, clamp_query, parse_result_links, pick_best,
)

FIX = Path(__file__).resolve().parent / "fixtures"


def _site(mode="url", tpl="https://e.com/?s={q}", maxlen=None, sid="e"):
    return Site(id=sid, name=sid, homepage="https://e.com/", kinds=[], langs={"zh"},
                url_searchable=(mode == "url"),
                search=SearchSpec(mode=mode, url_template=tpl),
                max_query_len=maxlen)


def test_build_search_url_encodes_cjk():
    s = _site()
    url = build_search_url(s, "终焉之莉莉")
    assert "?" in url and "%" in url          # 被 URL 编码
    assert "终焉" not in url                  # 原始中文不应出现
    assert url.startswith("https://e.com/?s=")


def test_build_search_url_form_mode_raises():
    s = _site(mode="form")
    with pytest.raises(ValueError):
        build_search_url(s, "x")


def test_clamp_query_truncates_to_site_limit():
    s = _site(maxlen=10)
    q, truncated = clamp_query(s, "终焉之莉莉终焉之莉莉终焉之莉莉")   # 15 字
    assert len(q) == 10
    assert truncated is True


def test_clamp_query_no_limit_keeps_full():
    s = _site(maxlen=None)
    q, truncated = clamp_query(s, "终焉之莉莉")
    assert q == "终焉之莉莉"
    assert truncated is False


def test_parse_result_links_from_jidi_fixture():
    html = (FIX / "jidiyouxi" / "search_ai.html").read_text(encoding="utf-8")
    s = _site(tpl="https://www.jidiyouxi.com/search/detail/{q}", sid="jidiyouxi")
    hits = parse_result_links(html, "https://www.jidiyouxi.com/search/detail/AI", s)
    assert hits, "jidiyouxi search page must yield hits"
    assert all("jidiyouxi.com" in h.url for h in hits)


def test_parse_result_links_from_g520_fixture():
    html = (FIX / "gamer520" / "search_ai.html").read_text(encoding="utf-8")
    s = _site(tpl="https://www.gamer520.com/?s={q}", sid="gamer520")
    hits = parse_result_links(html, "https://www.gamer520.com/?s=AI", s)
    assert hits, "gamer520 search page must yield hits"
    assert any(h.url.rstrip('/').endswith('.html') for h in hits)


def test_pick_best_prefers_title_match():
    from finder.models import SearchHit
    hits = [
        SearchHit("x", "完全无关的内容", "https://e.com/1"),
        SearchHit("x", "终焉之莉莉 Ender Lilies", "https://e.com/2"),
        SearchHit("x", "其他游戏", "https://e.com/3"),
    ]
    best = pick_best(hits, "终焉之莉莉")
    assert best is not None
    assert best.url == "https://e.com/2"


def test_pick_best_returns_none_on_empty():
    assert pick_best([], "x") is None
```

- [ ] **Step 2: 运行确认失败**

Run: `cd "C:\Users\27025\Desktop\game-finder"; python -m pytest tests/test_search_parse.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'finder.search'`

- [ ] **Step 3: 实现 search.py**

```python
# finder/search.py
"""站内搜索：url 模式（17 站）+ form 模式（5 站）。

关键实测（spec §2.1.4）：jidiyouxi 正文仅 160 字节但能出结果
→ 判成败必须数链接，不能看正文长度。
"""
from __future__ import annotations

import re
from urllib.parse import quote, urlparse

from .models import SearchHit, Site

NAV_RE = re.compile(
    r"/(login|register|signup|tag|tags|category|page/\d+|about|contact|"
    r"privacy|terms|feed|rss|user|profile|search)(/|$|\?)", re.I
)
DETAILISH_RE = re.compile(
    r"(/\d{2,}|/game/|/detail|/post/|/topic/|/subject/|/entry/|\.html$|/item/)", re.I
)


def build_search_url(site: Site, query: str) -> str:
    """mode=url 时按模板构造搜索 URL。"""
    if site.search.mode != "url" or not site.search.url_template:
        raise ValueError(f"{site.id}: not url-mode or missing template")
    return site.search.url_template.format(q=quote(query, safe=""))


def clamp_query(site: Site, query: str) -> tuple[str, bool]:
    """按站点词长上限截断（ACG 港湾 max_query_len=10）。返回 (词, 是否截断)。"""
    limit = site.max_query_len
    if limit and len(query) > limit:
        return query[:limit], True
    return query, False


def _same_origin(url: str, page_url: str) -> bool:
    try:
        return urlparse(url).netloc == urlparse(page_url).netloc
    except Exception:  # noqa: BLE001
        return False


def parse_result_links(html: str, page_url: str, site: Site) -> list[SearchHit]:
    """从搜索结果页抽候选详情链接。同域 + 排除导航 + 优先详情形状。"""
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', html, re.I)
    seen: set[str] = set()
    hits: list[SearchHit] = []

    for h in hrefs:
        if not h.startswith("http"):
            continue
        if not _same_origin(h, page_url):
            continue
        if NAV_RE.search(urlparse(h).path or ""):
            continue
        if h in seen:
            continue
        seen.add(h)
        # 标题：取 href 附近文本（粗粒度，够用于打分）
        idx = html.find(h)
        window = html[max(0, idx - 300): idx + 400] if idx >= 0 else ""
        text = re.sub(r"<[^>]+>", " ", window)
        text = re.sub(r"\s+", " ", text).strip()
        score = 1.0 if DETAILISH_RE.search(h) else 0.5
        hits.append(SearchHit(site_id=site.id, title=text[:200], url=h, score=score))

    return hits


def _norm(s: str) -> str:
    return re.sub(r"[\s\-_·・:：,，.。()（）\[\]【】]+", "", (s or "").lower())


def pick_best(hits: list[SearchHit], query: str) -> SearchHit | None:
    """标题与关键词归一化匹配打分，取最高。"""
    if not hits:
        return None
    q = _norm(query)
    best = None
    best_score = -1.0
    for h in hits:
        t = _norm(h.title)
        score = 0.0
        if q and q in t:
            score += 10.0
        # 逐字命中率，缓解标题里混了别的东西
        if q:
            score += sum(1 for ch in q if ch in t) / len(q)
        score += h.score * 0.1
        if score > best_score:
            best_score = score
            best = h
    return best
```

- [ ] **Step 4: 运行确认通过**

Run: `cd "C:\Users\27025\Desktop\game-finder"; python -m pytest tests/test_search_parse.py -v`
Expected: 8 passed

- [ ] **Step 5: 提交**

```bash
cd "C:\Users\27025\Desktop\game-finder"
git add finder/search.py tests/test_search_parse.py
git commit -m "feat(search): url/form modes, query clamping, result parsing"
```

---

### Task 7: 端到端抓取管线（真站验证）

**Files:**
- Create: `finder/pipeline.py`
- Create: `tools/smoke_live.py`
- Test: 手动冒烟（真站，不进 pytest）

**Interfaces:**
- Consumes: `browser.BrowserSession`、`sites.load_sites`、`lang.detect_lang`、`sites.filter_sites_by_lang`、`search.*`、`detail.extract_card`
- Produces:
  - `pipeline.search_one(page, site: Site, query: str) -> GameDetail`
  - `pipeline.run(query: str, site_ids: list[str] | None = None) -> list[GameDetail]`

- [ ] **Step 1: 写 smoke 脚本（先跑通真站，再固化为模块）**

```python
# tools/smoke_live.py
"""真站冒烟：对指定站点跑一次完整抓取，输出 ASCII 摘要。

用法：
  python tools/smoke_live.py 终焉之莉莉
  python tools/smoke_live.py enderlilies --sites jidiyouxi gamer520
结果同时写 tools/smoke_result.json（UTF-8）。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from finder.browser import BrowserSession  # noqa: E402
from finder.detail import extract_card  # noqa: E402
from finder.lang import detect_lang  # noqa: E402
from finder.search import (  # noqa: E402
    build_search_url, clamp_query, parse_result_links, pick_best,
)
from finder.sites import filter_sites_by_lang, load_sites  # noqa: E402


def grab(page, site, query):
    q, truncated = clamp_query(site, query)
    url = build_search_url(site, q)
    page.goto(url, timeout=45000, wait_until="load")
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(2000)
    html = page.content()
    hits = parse_result_links(html, page.url, site)
    best = pick_best(hits, q)
    if not best:
        return {"site": site.id, "status": "no_hits", "hits": len(hits)}
    page.goto(best.url, timeout=45000, wait_until="load")
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(2000)
    card = extract_card(page.content(), page.url, site.id)
    return {
        "site": site.id,
        "status": "ok",
        "hits": len(hits),
        "detail_url": card.url,
        "title_len": len(card.title or ""),
        "downloads": len(card.downloads),
        "kinds": sorted({d.kind for d in card.downloads}),
        "cover": bool(card.cover_url),
        "truncated": truncated,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--sites", nargs="*")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    all_sites = load_sites(ROOT / "sites.yaml")
    lang = detect_lang(args.query)
    part, skipped = filter_sites_by_lang(all_sites, lang)
    if args.sites:
        part = [s for s in part if s.id in args.sites]
        skipped = []
    part = [s for s in part if s.search.mode == "url"]   # smoke 只测 url 模式

    print(f"lang={lang} participating={len(part)} skipped={len(skipped)}")
    results = []
    with BrowserSession(cfg, ROOT) as sess:
        for site in part:
            page = sess.new_page()
            t0 = time.time()
            try:
                r = grab(page, site, args.query)
            except Exception as exc:  # noqa: BLE001
                r = {"site": site.id, "status": "error",
                     "error": f"{type(exc).__name__}: {str(exc)[:120]}"}
            r["ms"] = int((time.time() - t0) * 1000)
            results.append(r)
            print(f"{r['status']:<8} {r['site']:<14} hits={r.get('hits')} "
                  f"dl={r.get('downloads')} {r['ms']}ms {r.get('error','')}")
            page.close()

    (ROOT / "tools" / "smoke_result.json").write_text(
        json.dumps({"query": args.query, "lang": lang, "results": results},
                   indent=2, ensure_ascii=False), encoding="utf-8")
    ok = sum(1 for r in results if r["status"] == "ok")
    print(f"SUMMARY ok={ok}/{len(results)}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 跑真站冒烟（这是本任务的验收动作）**

```bash
cd "C:\Users\27025\Desktop\game-finder"
python tools/smoke_live.py 终焉之莉莉 --sites jidiyouxi gamer520 flysheep
```
Expected: `jidiyouxi` 与 `gamer520` 至少一个 `status=ok` 且 `dl>0`；`SUMMARY ok>=1/3`。
若某站 `error`，记录错误文本到 `tools/smoke_result.json`，**不要假装成功**。

- [ ] **Step 3: 把冒烟里验证过的逻辑固化成 pipeline.py**

```python
# finder/pipeline.py
"""把 browser + search + detail 串成一条抓取管线。"""
from __future__ import annotations

from pathlib import Path

from .detail import extract_card
from .models import GameDetail, Site
from .search import build_search_url, clamp_query, parse_result_links, pick_best

SEARCH_TIMEOUT = 45000
DETAIL_TIMEOUT = 45000


def _settle(page, ms: int = 2000) -> None:
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:  # noqa: BLE001
        pass
    page.wait_for_timeout(ms)


def search_one(page, site: Site, query: str) -> GameDetail:
    """单站：搜索 → 选最佳结果 → 进详情页 → 抽卡。失败返回带 error 的 GameDetail。"""
    q, truncated = clamp_query(site, query)
    if site.search.mode == "url":
        url = build_search_url(site, q)
        page.goto(url, timeout=SEARCH_TIMEOUT, wait_until="load")
        _settle(page)
    else:
        page.goto(site.homepage, timeout=SEARCH_TIMEOUT, wait_until="load")
        _settle(page)
        sel = site.search.input_selector or "input[type=search], input[name*=s], input[type=text]"
        box = page.locator(sel).first
        box.fill(q)
        box.press("Enter")
        _settle(page, 3000)

    search_html = page.content()
    hits = parse_result_links(search_html, page.url, site)
    best = pick_best(hits, q)
    if best is None:
        return GameDetail(site_id=site.id, url=page.url, title="",
                          error="NO_RESULTS", extra={"truncated": truncated})

    page.goto(best.url, timeout=DETAIL_TIMEOUT, wait_until="load")
    _settle(page)
    card = extract_card(page.content(), page.url, site.id)
    card.extra["truncated"] = truncated
    card.extra["search_url"] = page.url
    return card


def run(config: dict, sites: list[Site], query: str, project_root: Path) -> list[GameDetail]:
    """对一组站点串行跑（同站串行、跨站并行留给 server 层做）。"""
    from .browser import BrowserSession

    out: list[GameDetail] = []
    with BrowserSession(config, project_root) as sess:
        for site in sites:
            page = sess.new_page()
            try:
                out.append(search_one(page, site, query))
            except Exception as exc:  # noqa: BLE001
                out.append(GameDetail(site_id=site.id, url=site.homepage, title="",
                                      error=f"{type(exc).__name__}: {str(exc)[:150]}"))
            finally:
                page.close()
    return out
```

- [ ] **Step 4: 用 pipeline 复跑同一组站点，确认结果一致**

```bash
cd "C:\Users\27025\Desktop\game-finder"
python -c "import yaml,pathlib;from finder.sites import load_sites;from finder.pipeline import run;cfg=yaml.safe_load(open('config.yaml',encoding='utf-8'));root=pathlib.Path('.').resolve();ss=[s for s in load_sites(root/'sites.yaml') if s.id in ('jidiyouxi','gamer520')];rs=run(cfg,ss,'终焉之莉莉',root);[print(r.site_id,r.error,len(r.downloads),bool(r.title)) for r in rs]"
```
Expected: 两站都不抛异常；至少一站 `downloads > 0`。

- [ ] **Step 5: 提交**

```bash
cd "C:\Users\27025\Desktop\game-finder"
git add finder/pipeline.py tools/smoke_live.py
git commit -m "feat(pipeline): end-to-end grab + live smoke script"
```

---

### Task 8: 存储层（缓存 + 健康历史）

**Files:**
- Create: `finder/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `models.GameDetail`、`models.HealthRecord`
- Produces:
  - `store.Store(db_path: Path, ttl_hours: int)` 上下文管理器
  - `.get_cached(query_norm: str, site_id: str) -> GameDetail | None`
  - `.put_cached(query_norm: str, detail: GameDetail) -> None`
  - `.record_health(rec: HealthRecord) -> None`
  - `.health_latest() -> dict[str, HealthRecord]`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_store.py
import time
from pathlib import Path
from finder.models import Download, GameDetail, HealthRecord
from finder.store import Store


def test_put_and_get_roundtrip(tmp_path):
    db = tmp_path / "t.db"
    with Store(db, ttl_hours=12) as st:
        d = GameDetail(site_id="s", url="https://e.com/1", title="t",
                       downloads=[Download(kind="pan", url="https://pan.baidu.com/s/x")])
        st.put_cached("q", d)
        got = st.get_cached("q", "s")
    assert got is not None
    assert got.title == "t"
    assert len(got.downloads) == 1
    assert got.downloads[0].kind == "pan"


def test_cache_miss_returns_none(tmp_path):
    with Store(tmp_path / "t.db", ttl_hours=12) as st:
        assert st.get_cached("nope", "s") is None


def test_expired_cache_returns_none(tmp_path):
    db = tmp_path / "t.db"
    with Store(db, ttl_hours=0) as st:
        st.put_cached("q", GameDetail(site_id="s", url="u", title="t"))
        time.sleep(0.01)
        assert st.get_cached("q", "s") is None


def test_health_record_and_latest(tmp_path):
    with Store(tmp_path / "t.db", ttl_hours=12) as st:
        st.record_health(HealthRecord(site_id="a", status="ok", latency_ms=100,
                                      checked_at="2026-10-17T00:00:00"))
        st.record_health(HealthRecord(site_id="a", status="degraded", latency_ms=200,
                                      checked_at="2026-10-17T01:00:00"))
        latest = st.health_latest()
    assert latest["a"].status == "degraded"   # 取最新
    assert latest["a"].latency_ms == 200
```

- [ ] **Step 2: 运行确认失败**

Run: `cd "C:\Users\27025\Desktop\game-finder"; python -m pytest tests/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'finder.store'`

- [ ] **Step 3: 实现 store.py**

```python
# finder/store.py
"""SQLite 缓存与健康历史。纯标准库，无 ORM。"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Download, GameDetail, HealthRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS search_cache (
    query_norm TEXT NOT NULL,
    site_id    TEXT NOT NULL,
    payload    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (query_norm, site_id)
);
CREATE TABLE IF NOT EXISTS health_history (
    site_id    TEXT NOT NULL,
    status     TEXT NOT NULL,
    latency_ms INTEGER NOT NULL,
    reason     TEXT NOT NULL,
    checked_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_health_site ON health_history(site_id, checked_at);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Store:
    def __init__(self, db_path: Path | str, ttl_hours: int = 12):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl = timedelta(hours=ttl_hours)
        self._con = sqlite3.connect(str(self.path))
        self._con.executescript(SCHEMA)
        self._con.commit()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self._con.close()

    def put_cached(self, query_norm: str, detail: GameDetail) -> None:
        self._con.execute(
            "INSERT OR REPLACE INTO search_cache VALUES (?,?,?,?)",
            (query_norm, detail.site_id,
             json.dumps(asdict(detail), ensure_ascii=False),
             _now().isoformat()),
        )
        self._con.commit()

    def get_cached(self, query_norm: str, site_id: str) -> GameDetail | None:
        row = self._con.execute(
            "SELECT payload, created_at FROM search_cache WHERE query_norm=? AND site_id=?",
            (query_norm, site_id),
        ).fetchone()
        if not row:
            return None
        payload, created = row
        try:
            created_dt = datetime.fromisoformat(created)
        except ValueError:
            return None
        if _now() - created_dt > self.ttl:
            return None
        data = json.loads(payload)
        data["downloads"] = [Download(**d) for d in data.get("downloads", [])]
        return GameDetail(**data)

    def record_health(self, rec: HealthRecord) -> None:
        self._con.execute(
            "INSERT INTO health_history VALUES (?,?,?,?,?)",
            (rec.site_id, rec.status, rec.latency_ms, rec.reason, rec.checked_at),
        )
        self._con.commit()

    def health_latest(self) -> dict[str, HealthRecord]:
        rows = self._con.execute(
            """SELECT h.site_id, h.status, h.latency_ms, h.reason, h.checked_at
               FROM health_history h
               JOIN (SELECT site_id, MAX(checked_at) mx FROM health_history GROUP BY site_id) m
                 ON h.site_id=m.site_id AND h.checked_at=m.mx"""
        ).fetchall()
        return {
            r[0]: HealthRecord(site_id=r[0], status=r[1], latency_ms=r[2],
                               reason=r[3], checked_at=r[4])
            for r in rows
        }
```

- [ ] **Step 4: 运行确认通过**

Run: `cd "C:\Users\27025\Desktop\game-finder"; python -m pytest tests/test_store.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
cd "C:\Users\27025\Desktop\game-finder"
git add finder/store.py tests/test_store.py
git commit -m "feat(store): sqlite cache with TTL + health history"
```

---

### Task 9: FastAPI 服务与 SSE 流式接口

**Files:**
- Create: `finder/web/server.py`
- Create: `app.py`
- Test: `tests/test_server.py`

**Interfaces:**
- Consumes: `sites.load_sites`、`lang.detect_lang`、`sites.filter_sites_by_lang`、`pipeline.run`、`store.Store`
- Produces:
  - `GET /api/sites` → `[{id,name,langs,mode,url_searchable}]`
  - `POST /api/search` body `{query}` → SSE 事件流：`start`（含 lang/participating/skipped）、`result`（每站一条）、`done`
  - `GET /api/health` → 最新健康状态
  - `app.py` 起 uvicorn 并 `webbrowser.open`

- [ ] **Step 1: 写失败测试（用 FastAPI TestClient，不触网）**

```python
# tests/test_server.py
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    # 让 server 不真的起浏览器：把 pipeline.run 替换成假实现
    from finder.web import server as srv
    monkeypatch.setattr(
        srv, "_run_pipeline",
        lambda config, sites, query, root: [
            __import__("finder.models", fromlist=["GameDetail"]).GameDetail(
                site_id=sites[0].id, url="https://e.com/1", title="fake") if sites else
            __import__("finder.models", fromlist=["GameDetail"]).GameDetail(
                site_id="none", url="u", title="")
        ],
    )
    return TestClient(srv.create_app())


def test_sites_endpoint_lists_22(client):
    r = client.get("/api/sites")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 22
    assert {"id", "name", "langs", "mode"} <= set(data[0])


def test_search_streams_start_result_done(client):
    with client.stream("POST", "/api/search", json={"query": "终焉之莉莉"}) as r:
        assert r.status_code == 200
        body = "".join(r.iter_text())
    assert "event: start" in body
    assert '"lang": "zh"' in body or '"lang":"zh"' in body
    assert "event: result" in body
    assert "event: done" in body


def test_search_lang_routing_counts(client):
    """zh 输入应报告 17 个参与站点。"""
    with client.stream("POST", "/api/search", json={"query": "终焉之莉莉"}) as r:
        body = "".join(r.iter_text())
    import re
    m = re.search(r'"participating":\s*(\d+)', body)
    assert m and int(m.group(1)) == 17


def test_health_endpoint_shape(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert isinstance(r.json(), dict)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd "C:\Users\27025\Desktop\game-finder"; python -m pytest tests/test_server.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'finder.web.server'`

- [ ] **Step 3: 实现 server.py**

```python
# finder/web/server.py
"""FastAPI + SSE。搜索按语种路由后流式推送。"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import yaml
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from ..lang import detect_lang
from ..models import GameDetail, Site
from ..sites import filter_sites_by_lang, load_sites
from ..store import Store

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def _run_pipeline(config: dict, sites: list[Site], query: str, root: Path) -> list[GameDetail]:
    """真实现。测试里会被 monkeypatch 掉，避免起浏览器。"""
    from ..pipeline import run
    return run(config, sites, query, root)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def create_app() -> FastAPI:
    app = FastAPI(title="Game Finder")
    all_sites = load_sites(ROOT / "sites.yaml")

    @app.get("/api/sites")
    def sites():
        return [
            {"id": s.id, "name": s.name, "langs": sorted(s.langs),
             "mode": s.search.mode, "url_searchable": s.url_searchable,
             "needs_login": s.needs_login, "max_query_len": s.max_query_len,
             "kinds": s.kinds}
            for s in all_sites
        ]

    @app.post("/api/search")
    def search(body: dict):
        query = (body.get("query") or "").strip()
        lang = detect_lang(query)
        part, skipped = filter_sites_by_lang(all_sites, lang)

        def gen():
            yield _sse("start", {
                "query": query, "lang": lang,
                "participating": len(part),
                "skipped": [{"id": s.id, "name": s.name,
                             "reason": "LANG_MISMATCH"} for s in skipped],
            })
            try:
                results = _run_pipeline(CONFIG, part, query, ROOT)
            except Exception as exc:  # noqa: BLE001
                yield _sse("error", {"message": f"{type(exc).__name__}: {str(exc)[:200]}"})
                yield _sse("done", {"ok": 0, "total": len(part)})
                return
            ok = 0
            for d in results:
                if not d.error:
                    ok += 1
                yield _sse("result", asdict(d))
            yield _sse("done", {"ok": ok, "total": len(results)})

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/api/health")
    def health():
        db = ROOT / "data" / "finder.db"
        if not db.exists():
            return {}
        with Store(db, CONFIG["cache"]["ttl_hours"]) as st:
            return {k: asdict(v) for k, v in st.health_latest().items()}

    static = Path(__file__).resolve().parent / "static"
    if static.exists():
        app.mount("/", StaticFiles(directory=str(static), html=True), name="static")
    return app


app = create_app()
```

- [ ] **Step 4: 实现 app.py（入口）**

```python
# app.py
"""启动本地服务并打开浏览器标签页。"""
from __future__ import annotations

import threading
import webbrowser
from pathlib import Path

import uvicorn
import yaml

ROOT = Path(__file__).resolve().parent


def main() -> None:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    host = cfg["server"]["host"]
    port = cfg["server"]["port"]
    url = f"http://{host}:{port}/"
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"[game-finder] serving at {url}")
    uvicorn.run("finder.web.server:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: 运行确认通过**

Run: `cd "C:\Users\27025\Desktop\game-finder"; python -m pytest tests/test_server.py -v`
Expected: 4 passed

- [ ] **Step 6: 提交**

```bash
cd "C:\Users\27025\Desktop\game-finder"
git add finder/web/server.py app.py tests/test_server.py
git commit -m "feat(web): FastAPI + SSE search with language routing"
```

---

### Task 10: 单页界面

**Files:**
- Create: `finder/web/static/index.html`

**Interfaces:**
- Consumes: `/api/sites`、`/api/search`（SSE）、`/api/health`
- Produces: 可用界面（无构建步骤、原生 JS）

- [ ] **Step 1: 写界面**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Game Finder</title>
<style>
  :root { --bg:#0f1115; --card:#171a21; --fg:#e6e6e6; --dim:#8b93a1;
          --accent:#4da3ff; --ok:#3fb950; --warn:#d29922; --bad:#f85149; }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--fg);
         font:14px/1.6 "Segoe UI", system-ui, sans-serif; }
  header { padding:24px; border-bottom:1px solid #23262e; }
  h1 { margin:0 0 12px; font-size:20px; }
  .row { display:flex; gap:8px; align-items:center; }
  input[type=text] { flex:1; padding:10px 12px; border-radius:8px;
    border:1px solid #2c303a; background:#12151b; color:var(--fg); font-size:15px; }
  button { padding:10px 18px; border-radius:8px; border:0;
    background:var(--accent); color:#04101f; font-weight:600; cursor:pointer; }
  button:disabled { opacity:.5; cursor:default; }
  .lang { margin-top:10px; color:var(--dim); font-size:13px; }
  .lang b { color:var(--accent); }
  .hint { margin-top:8px; padding:8px 12px; border-radius:8px;
          background:#1d2530; color:var(--warn); font-size:13px; display:none; }
  main { padding:24px; display:grid; gap:14px;
         grid-template-columns:repeat(auto-fill,minmax(340px,1fr)); }
  .card { background:var(--card); border:1px solid #23262e; border-radius:12px;
          padding:16px; display:flex; flex-direction:column; gap:10px; }
  .card h3 { margin:0; font-size:15px; }
  .card .meta { color:var(--dim); font-size:12px; display:flex; gap:10px; flex-wrap:wrap; }
  .cover { width:100%; max-height:150px; object-fit:cover; border-radius:8px; }
  .intro { color:#c3c9d4; font-size:13px; max-height:96px; overflow:hidden; }
  .dl { display:flex; flex-wrap:wrap; gap:6px; }
  .dl a { padding:5px 10px; border-radius:6px; text-decoration:none;
          font-size:12px; background:#222833; color:var(--fg); }
  .dl a.pan { background:#1f3a2b; color:#7ee2a8; }
  .dl a.magnet { background:#3a1f33; color:#f0a6d8; }
  .dl a.direct { background:#1f2f3a; color:#8fd0ff; }
  .err { color:var(--bad); font-size:12px; }
  .spin { color:var(--dim); font-size:12px; }
  .badge { font-size:11px; padding:2px 7px; border-radius:99px;
           background:#222833; color:var(--dim); }
  .badge.warn { background:#3a2f1a; color:var(--warn); }
</style>
</head>
<body>
<header>
  <h1>Game Finder</h1>
  <div class="row">
    <input id="q" type="text" placeholder="输入游戏名（中文 / English / 日本語）" autofocus>
    <button id="go">搜索</button>
  </div>
  <div class="lang" id="langLine">支持 22 个资源站 · 自动识别语种</div>
  <div class="hint" id="hint">
    没找到？试试用<b>英文名</b>或<b>日文名</b>再搜一次。
  </div>
</header>
<main id="out"></main>

<script>
const out = document.getElementById('out');
const goBtn = document.getElementById('go');
const input = document.getElementById('q');
const langLine = document.getElementById('langLine');
const hint = document.getElementById('hint');

const KIND_CLASS = { pan:'pan', magnet:'magnet', direct:'direct', unknown:'' };
const LANG_NAME = { zh:'中文', en:'英文', ja:'日文' };

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function renderCard(d) {
  const c = el('div','card');
  c.dataset.site = d.site_id;
  if (d.cover_url) {
    const img = el('img','cover'); img.src = d.cover_url; img.loading='lazy';
    img.onerror = () => img.remove();
    c.appendChild(img);
  }
  c.appendChild(el('h3', null, d.title || '（无标题）'));
  const meta = el('div','meta');
  meta.appendChild(el('span','badge', d.site_id));
  if (d.size)    meta.appendChild(el('span', null, d.size));
  if (d.version) meta.appendChild(el('span', null, d.version));
  if (d.updated_at) meta.appendChild(el('span', null, d.updated_at));
  c.appendChild(meta);
  if (d.intro) c.appendChild(el('div','intro', d.intro));
  if (d.error) c.appendChild(el('div','err', '失败：' + d.error));

  const dl = el('div','dl');
  (d.downloads || []).forEach(x => {
    const a = el('a', KIND_CLASS[x.kind] || '', x.label || x.kind);
    a.href = x.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
    a.title = x.url;
    if (x.code) a.textContent += ' · 码 ' + x.code;
    dl.appendChild(a);
  });
  if (dl.children.length) c.appendChild(dl);
  return c;
}

async function search() {
  const query = input.value.trim();
  if (!query) return;
  goBtn.disabled = true;
  out.innerHTML = '';
  hint.style.display = 'none';
  langLine.textContent = '搜索中…';

  const resp = await fetch('/api/search', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({query}),
  });
  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = '', gotAny = false, lang = null;

  while (true) {
    const {value, done} = await reader.read();
    if (done) break;
    buf += dec.decode(value, {stream:true});
    const blocks = buf.split('\n\n');
    buf = blocks.pop();
    for (const blk of blocks) {
      const evLine = blk.split('\n').find(l => l.startsWith('event:'));
      const dataLine = blk.split('\n').find(l => l.startsWith('data:'));
      if (!evLine || !dataLine) continue;
      const ev = evLine.slice(6).trim();
      const data = JSON.parse(dataLine.slice(5).trim());

      if (ev === 'start') {
        lang = data.lang;
        langLine.innerHTML =
          `识别语种：<b>${LANG_NAME[data.lang] || data.lang}</b> · ` +
          `参与 ${data.participating} 站 · 跳过 ${data.skipped.length} 站（不支持该语种）`;
      } else if (ev === 'result') {
        gotAny = true;
        out.appendChild(renderCard(data));
      } else if (ev === 'error') {
        out.appendChild(renderCard({site_id:'system', title:'出错', error:data.message,
                                    downloads:[]}));
      } else if (ev === 'done') {
        if (!gotAny) hint.style.display = 'block';
        langLine.textContent += ` · 完成（成功 ${data.ok}/${data.total}）`;
      }
    }
  }
  goBtn.disabled = false;
}

goBtn.addEventListener('click', search);
input.addEventListener('keydown', e => { if (e.key === 'Enter') search(); });
</script>
</body>
</html>
```

- [ ] **Step 2: 启动服务并肉眼验收**

```bash
cd "C:\Users\27025\Desktop\game-finder"
python app.py
```
Expected: 终端打印 `[game-finder] serving at http://127.0.0.1:8734/`，浏览器自动打开该页面。

在页面里输入 `终焉之莉莉`，点搜索：
- 顶部显示「识别语种：**中文** · 参与 17 站 · 跳过 5 站」
- 结果卡片流式出现（先出先显示，不用等全部）
- 卡片含封面/标题/简介/大小/版本，下载按钮按类型配色

- [ ] **Step 3: 验证语种路由真的生效**

在同一页面输入 `enderlilies` 再搜：
Expected: 顶部变为「识别语种：**英文** · 参与 **18** 站 · 跳过 4 站」。
这是语种路由的核心验收点。

- [ ] **Step 4: 提交**

```bash
cd "C:\Users\27025\Desktop\game-finder"
git add finder/web/static/index.html
git commit -m "feat(web): single-page UI with SSE cards and language hint"
```

---

### Task 11: 健康巡检

**Files:**
- Create: `finder/health.py`
- Test: `tests/test_health.py`

**Interfaces:**
- Consumes: `store.Store`、`models.HealthRecord`、`browser.BrowserSession`、`search.*`
- Produces:
  - `health.probe_word_for(site: Site, probe_words: dict[str, str]) -> str`
  - `health.classify(status_code: int | None, body: str, hits: int) -> str`
  - `health.check_site(page, site: Site, probe_words: dict) -> HealthRecord`

- [ ] **Step 1: 写失败测试（状态机纯逻辑，不触网）**

```python
# tests/test_health.py
from finder.health import classify, probe_word_for
from finder.models import SearchSpec, Site


def _site(langs, sid="s"):
    return Site(id=sid, name=sid, homepage="https://e.com/", kinds=[],
                langs=set(langs), url_searchable=True,
                search=SearchSpec(mode="url", url_template="https://e.com/?s={q}"))


def test_classify_ok():
    assert classify(200, "<html>results</html>", 5) == "ok"


def test_classify_degraded_when_page_ok_but_zero_hits():
    assert classify(200, "<html>nothing</html>", 0) == "degraded"


def test_classify_cloudflare():
    assert classify(403, "<title>Attention Required! | Cloudflare</title>", 0) == "cloudflare_block"


def test_classify_unreachable():
    assert classify(None, "", 0) == "unreachable"


def test_classify_needs_login():
    body = "<html><a href='/login'>请先登录</a></html>"
    assert classify(200, body, 0) == "needs_login"


def test_probe_word_prefers_zh_then_en_then_ja():
    words = {"zh": "终焉之莉莉", "en": "enderlilies", "ja": "制服カノジョ"}
    assert probe_word_for(_site(["zh", "en"]), words) == "终焉之莉莉"
    assert probe_word_for(_site(["en"]), words) == "enderlilies"
    assert probe_word_for(_site(["ja"]), words) == "制服カノジョ"
    assert probe_word_for(_site(["en", "ja"]), words) == "enderlilies"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd "C:\Users\27025\Desktop\game-finder"; python -m pytest tests/test_health.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'finder.health'`

- [ ] **Step 3: 实现 health.py**

```python
# finder/health.py
"""可用性巡检。判定标准：真实站内搜索返回 ≥1 条结果才算 ok。"""
from __future__ import annotations

from datetime import datetime, timezone

from .models import HealthRecord, Site
from .search import (
    build_search_url, clamp_query, parse_result_links,
)

CLOUDFLARE_HINTS = ("attention required", "just a moment", "cloudflare", "cf-error")
LOGIN_HINTS = ("请先登录", "请登录", "sign in", "log in to continue", "需要登录")


def probe_word_for(site: Site, probe_words: dict[str, str]) -> str:
    """按站点支持的语种，优先 zh → en → ja 取探测词。"""
    for lang in ("zh", "en", "ja"):
        if lang in site.langs and probe_words.get(lang):
            return probe_words[lang]
    return next(iter(probe_words.values()), "game")


def classify(status_code: int | None, body: str, hits: int) -> str:
    """把一次探测归类为状态机的某个状态。"""
    low = (body or "").lower()
    if any(h in low for h in CLOUDFLARE_HINTS):
        return "cloudflare_block"
    if any(h in low for h in LOGIN_HINTS):
        return "needs_login"
    if status_code is None:
        return "unreachable"
    if status_code >= 400:
        return "unreachable"
    if hits > 0:
        return "ok"
    return "degraded"


def check_site(page, site: Site, probe_words: dict[str, str],
               timeout_ms: int = 45000) -> HealthRecord:
    """对单站跑一次真实搜索探测。"""
    word = probe_word_for(site, probe_words)
    started = datetime.now(timezone.utc)
    status_code = None
    body = ""
    hits = 0
    reason = ""
    try:
        if site.search.mode == "url":
            q, _ = clamp_query(site, word)
            url = build_search_url(site, q)
            resp = page.goto(url, timeout=timeout_ms, wait_until="load")
            status_code = resp.status if resp else None
        else:
            page.goto(site.homepage, timeout=timeout_ms, wait_until="load")
            page.wait_for_timeout(2000)
            sel = site.search.input_selector or "input[type=search], input[type=text]"
            box = page.locator(sel).first
            box.fill(word)
            box.press("Enter")
            page.wait_for_timeout(3000)
            status_code = 200
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        body = page.content()
        hits = len(parse_result_links(body, page.url, site))
    except Exception as exc:  # noqa: BLE001
        reason = f"{type(exc).__name__}: {str(exc)[:120]}"

    status = classify(status_code, body, hits)
    if reason and status == "ok":
        status = "degraded"
    elapsed = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
    return HealthRecord(site_id=site.id, status=status, latency_ms=elapsed,
                        reason=reason or f"hits={hits}",
                        checked_at=started.isoformat())
```

- [ ] **Step 4: 运行确认通过**

Run: `cd "C:\Users\27025\Desktop\game-finder"; python -m pytest tests/test_health.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
cd "C:\Users\27025\Desktop\game-finder"
git add finder/health.py tests/test_health.py
git commit -m "feat(health): probe state machine with per-language probe words"
```

---

### Task 12: 全量回归与收尾

**Files:**
- Modify: `PROGRESS.md`（更新为已完成状态）
- Test: 全部测试

**Interfaces:**
- Consumes: 前面所有任务
- Produces: 可交付版本

- [ ] **Step 1: 跑全部离线测试**

```bash
cd "C:\Users\27025\Desktop\game-finder"
python -m pytest tests/ -v
```
Expected: 全部 PASS（约 45 个用例）。**若有 FAIL，逐个修到全绿再继续。**

- [ ] **Step 2: 真站冒烟复跑（确认没有回归）**

```bash
cd "C:\Users\27025\Desktop\game-finder"
python tools/smoke_live.py 终焉之莉莉 --sites jidiyouxi gamer520
python tools/smoke_live.py enderlilies --sites gamer520 nyaa
```
Expected: 中文那次 `lang=zh`，英文那次 `lang=en`；至少各 1 站 `status=ok` 且 `dl>0`。

- [ ] **Step 3: 更新 PROGRESS.md**

把 `## 三、当前进度` 一节替换为：
```markdown
## 三、当前进度：P0–P2 已实现

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 | 骨架 + config + sites.yaml(22) | ✅ |
| P1 | 浏览器层（专用 profile + UA + 代理） | ✅ |
| P2 | 搜索层（url 17 站 / form 5 站）+ 详情抽取 + 语种路由 | ✅ |
| P3 | 界面（SSE 卡片 + 语种提示） | ✅ |
| P4 | 健康巡检 | ✅ |
| P5 | 铺开 form 模式的 5 站选择器实测 | 待做 |
```

- [ ] **Step 4: 提交**

```bash
cd "C:\Users\27025\Desktop\game-finder"
git add PROGRESS.md
git commit -m "docs: mark P0-P4 complete in progress record"
```

---

## Self-Review

**1. Spec coverage：**

| Spec 章节 | 覆盖任务 |
|---|---|
| §1 目标/非目标 | Task 1（范围）、Task 10（UI 验收） |
| §2 约束表 | Global Constraints（全部硬约束逐条列出） |
| §2.1.1 专用 profile | Task 4（`resolve_profile_dir` + 断言不等于默认目录） |
| §2.1.2 代理 6234 | Task 1（config 断言）、Task 4（`BrowserSession` 注入） |
| §2.1.3 站点机制/模板 | Task 3（sites.yaml 17 模板）、Task 6（build_search_url） |
| §2.1.4 UA / 无头检测 | Task 4（`build_user_agent` + 断言无 `Headless`） |
| §2.1.5 语种路由 | Task 2（detect_lang）、Task 3（filter_sites_by_lang）、Task 9（SSE 报数）、Task 10（UI 提示） |
| §3 站点注册表（22 站） | Task 3（sites.yaml + 9 项校验测试） |
| §4 架构（文件清单） | File Structure 全覆盖；`lang.py` 已加入 |
| §4 数据流 | Task 9（SSE 管线）、Task 7（pipeline） |
| §4 detail.py 字段 | Task 5（extract_card 全字段 + 3 个实测坑） |
| §4 health.py | Task 11（状态机 + 按语种探测词） |
| §4 store.py | Task 8（SQLite + TTL） |
| §4 界面 | Task 10（含语种徽章与「试试英文名」提示） |
| §5 错误码 | Task 11（classify 产出状态）、Task 5/6（error 字段） |
| §6 测试策略 | 每个任务 TDD；Task 12 全量回归 |

**发现并已修正的缺口：**
- 原 spec 文件清单缺 `lang.py` → 已加入 File Structure 与 Task 2。
- 原 spec 缺「探测词按语种」→ 已在 Task 1 config 与 Task 11 实现。
- `QUERY_TOO_LONG` 错误码 → 由 `clamp_query` 的 `truncated` 标志承载（Task 6），在卡片 `extra` 里传递（Task 7）。

**2. Placeholder scan：** 无 TBD/TODO；每个代码步骤都有完整可运行代码；无「similar to Task N」引用。

**3. Type consistency 检查：**
- `detect_lang(text: str) -> str` — Task 2 定义，Task 9/10/11 使用，签名一致。
- `filter_sites_by_lang(all_sites, lang) -> tuple[list[Site], list[Site]]` — Task 3 定义，Task 9/7 使用一致。
- `SearchSpec(mode, url_template, input_selector, submit_selector, result_link_selector, title_selector)` — Task 3 定义，Task 5/6/11 使用一致。
- `GameDetail(site_id, url, title, cover_url, intro, version, size, updated_at, downloads, error, extra)` — Task 3 定义；Task 5 构造、Task 7 补 `extra`、Task 9 `asdict` 序列化，一致。
- `Download(kind, url, label, code)` — Task 3 定义，Task 5 构造，Task 8 反序列化，一致。
- `Store(db_path, ttl_hours)` / `.get_cached(query_norm, site_id)` — Task 8 定义，Task 9 使用一致。
- `parse_result_links(html, page_url, site) -> list[SearchHit]` — Task 6 定义，Task 7/11 使用一致。

---

## Execution Handoff

计划已保存到 `docs/superpowers/plans/2026-10-17-game-finder-implementation.md`。两种执行方式：

**1. Subagent-Driven（推荐）** — 每个任务派一个全新 subagent，任务之间我做两阶段 review，迭代快、上下文干净。

**2. Inline Execution** — 在当前会话里按 executing-plans 批量执行，带检查点。

选哪个？
