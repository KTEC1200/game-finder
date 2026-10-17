# 游戏资源检索器（Game Finder）设计文档

- 日期：2026-10-16；**2026-10-17 大改**（站点清单换新、新增语种路由、URL 模板实测验证）
- 状态：已评审，**待出实现计划**
- 项目根目录：`C:\Users\27025\Desktop\game-finder\`
- 站点清单来源：**`C:\Users\27025\Desktop\网站链接（更新）.md`**（2026-10-17 用户提供，22 站）
- 需求来源：用户 2026-10-16 提出；方案确认 m00044

> **修订摘要（三次实测推翻/修正原设计）**
> 1. **「复用用户已登录的真实 Chrome」不可实现** —— Chrome 155 禁止对*默认* user-data-dir 开放 DevTools（playwright 的 pipe 与 `--remote-debugging-port` 双双失效）；且 profile 副本的 cookie 会被启动时清空。→ 改为**应用专用 profile**（非默认路径），用户首次登录一次即可持久保留（已验证）。见 §2.1.1。
> 2. **代理端口不是 7890** —— 真实系统代理是 `127.0.0.1:6234`。实测：显式 6234 → 5/5 站可达；真直连 4/5（nyaa 挂）；跟随系统代理 4/5（机地挂）。→ 默认**显式** `http://127.0.0.1:6234`。见 §2.1.2。
> 3. **无头模式会被 Cloudflare 识别** —— ankergames 与爱之列车在 headless 下 403，但**headless + 显式真实 UA** 即 200。→ UA 必须显式设置。见 §2.1.4。
>
> **2026-10-17 需求变更**
> - 站点清单换新：**猫盘移除**（搜索 API 实测损坏）、备用/导航 URL 全部移除、**22 站**。
> - 用户**逐站实测给出了 17 个可用 URL 模板** + 5 个只能站内搜索的站 → 每站搜索模式**已钉死**，取消 `mode: auto` 试错。
> - 新增**按语言路由**：单输入框自动识别中/英/日，只查支持该语种的站。见 §2.1.5。

## 1. 目标

一个本地运行的 Windows 应用：用户输入**游戏名称**，应用在用户给定的资源站清单中做**站内搜索**，返回每个站的**内容介绍 + 下载链接**；并**定期检查站点可用性**。

### 成功判据

1. 输入一个游戏名，30 秒内在已适配站点上产出结果卡片（标题 / 简介 / 版本或大小 / 下载链接）。
2. 结果里的下载链接**可点击直达**，并标注类型（直链 / 网盘 / 磁力）。
3. 站点健康状态有独立面板，含状态、耗时、失败原因、上次检查时间。
4. 某站失败**不阻塞**其它站——结果流式渲染，先出先显示。
5. 每站解析逻辑可用离线 fixture 测试复现，不依赖网络。
6. **输入中文名时自动只查支持中文的 17 站，并提示「没找到可换英文名/日文名」**（§2.1.5）。

### 非目标（YAGNI，明确不做）

- 不做游戏本体下载/离线下载（只给链接）。
- 不做账号注册、不做破解、不做资源上传。
- 不做全站爬虫或全站索引；只做「关键词 → 站内搜索 → 取前若干条」。
- 不做云同步、多用户、移动端。
- 不做自动更新站点清单（站点清单是本地配置文件，手工维护）。

## 2. 关键约束（已与用户确认）

| 约束 | 决定 | 依据 |
|---|---|---|
| 浏览器 | ~~驱动用户已登录的真实 Chrome，复用其 user-data-dir~~ → **应用专用 profile**（`<project>/chrome-profile/`），首次登录后持久 | 实测推翻，见 §2.1.1 |
| 形态 | **本地 Web UI**：Python 起本地服务，浏览器开标签页 | 用户选 A |
| 代理 | **显式** `http://127.0.0.1:6234`（不是 7890） | 实测，见 §2.1.2 |
| UA | **必须显式设置真实 Chrome UA**，否则 headless 被 Cloudflare 拦 | 实测，见 §2.1.4 |
| 适配策略 | 每站模式**已由用户实测钉死**：17 站 `url` + 5 站 `form` | 用户 2026-10-17 清单 |
| 抓取深度 | 搜索结果列表 + **自动进详情页**抓简介与下载链 | 用户答「推荐」 |
| 可用性判定 | **跑一次真实站内搜索**能出结果才算可用 | 用户答「推荐」 |
| **语言路由** | **单输入框 + 自动识别 zh/en/ja，只查支持该语种的站** | 用户 2026-10-17 确认 |
| 语言覆盖 | zh=17 站 / en=18 站 / ja=12 站（共 22 站） | 已核算 |
| 项目落盘 | `C:\Users\27025\Desktop\game-finder\` | 用户指定 |

## 2.1 实测修订（2026-10-16，推翻原设计）

本机环境：**Chrome 155.0.8059.80**（`C:\Program Files\Google\Chrome\Application\chrome.exe`）、Python 3.14.6。

### 2.1.1 浏览器：专用 profile 取代「复用真实 profile」

| 实验 | 结果 |
|---|---|
| 临时 profile + `launch_persistent_context` | **OK** |
| **真实默认 profile** + headless | **FAIL**（超时） |
| 真实默认 profile + headful | **FAIL** |
| 真实默认 profile + `--profile-directory=Default` | **FAIL** |
| 真实默认 profile + `--disable-extensions` | **FAIL** |
| 真实默认 profile + `--remote-debugging-port=9222`（CDP） | **FAIL**（端点始终不出现） |
| **真实 profile 完整副本**（非默认路径，1258 MB） | **OK** → 证明**阻塞点是「路径是默认目录」**，不是内容/大小/锁 |
| 副本启动后读 cookie DB | 224 → **0**（启动即清空） |
| 专用 profile 中**服务端 Set-Cookie（带 `Max-Age`）** | **跨重启保留 OK**（headless 与 headful 均验证） |
| 专用 profile 中 `ctx.add_cookies()`（**无 `expires`**） | 重启后消失 |

**根因**：Chrome 136+ 出于安全（防 cookie 窃取）**拒绝对默认 user-data-dir 开放 DevTools** —— `--remote-debugging-port` 与 `--remote-debugging-pipe`（playwright 用的就是 pipe）都被忽略，所以表现为超时。把同一份 profile **复制到非默认路径**即可正常驱动，证明是路径而非内容问题。

**结论（架构级）**：
- 「复用用户真实 Chrome 的登录态」在本机**不可实现**，无论走 playwright 还是 CDP。原 §2 的「驱动用户已登录的真实 Chrome，复用其 user-data-dir」作废。
- 改为 **应用专用 profile**：`<project>/chrome-profile/`（非默认路径）。
- **登录态可持久**：站点通过 HTTP `Set-Cookie` 下发且带有效期（真实登录都是这种）→ 跨重启保留。仅「无 `expires` 的会话 cookie」不持久，这属浏览器标准行为，不是缺陷。
- **副带好处**：不再需要「用户先完全退出 Chrome」这条硬约束（§2 的 `PROFILE_IN_USE` 降级为「专用 profile 自身被占用」的罕见情形）。
- 实测登录态并未覆盖目标站（原 profile 224 个 cookie / 59 个 host，**无一**是目标站），所以「必须继承登录态」这个前提本身也不成立 —— 多数资源站是公开的，少数论坛（kungal / galgame.dev / anime-sharing）需要用户**在专用 profile 里首次登录一次**。

### 2.1.2 代理：端口 6234，且必须显式指定

原设计假设 `http://127.0.0.1:7890` —— **实测该端口无监听**（ConnectionRefused）。真实系统代理由 WinINET 指定：

```
HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings
  ProxyEnable = 1
  ProxyServer = 127.0.0.1:6234      # 进程：AtlasCore_amd64
```

三配置 × 5 站矩阵（headless）：

| 站 | A 真直连（`--no-proxy-server`） | B 跟随系统代理（不传 proxy） | C 显式 6234 |
|---|---|---|---|
| 机地 jidiyouxi | 200 (3377ms) | **超时 FAIL** | **200 (1588ms)** |
| Gamer520 | 200 (450ms) | 200 (890ms) | **200 (1114ms)** |
| 猫盘 catcat | 200 (1469ms) | 200 (1578ms) | **200 (1515ms)** |
| anime-sharing | 200 (1359ms) | 200 (1876ms) | **200 (1895ms)** |
| nyaa | **超时 FAIL** | 200 (2433ms) | **200 (2412ms)** |
| **合计** | **4/5** | 4/5 | **5/5** |

**结论**：**显式** `proxy={"server": "http://127.0.0.1:6234"}` 是唯一 5/5 的配置，且对所有站都通（含国内站）。
- 原 §4「整个 context 统一走 `config.proxy.server`（默认 7890）」的**思路正确**，只是端口错；改为 6234，且**显式传入**而不是依赖 Chrome 继承系统代理（B 配置下机地会挂）。
- `config.proxy.enabled: false` 仍保留（真直连模式），此时 nyaa 类站报 `NEEDS_PROXY`。

### 2.1.3 站点搜索机制（P2 两站实测 + 用户实测模板）

> **2026-10-17 重大更新**：用户提供了新清单 `网站链接（更新）.md`，**逐站实测给出了可用 URL 模板**。
> 这取代了之前所有靠推断得到的搜索模式 —— 用户的实测结果优先于我的推断。

**用户实测给出的 17 个 URL 模板**（`{q}` 需 URL 编码）：

| 站点 | URL 模板 | 语言 |
|---|---|---|
| 机地 | `https://www.jidiyouxi.com/search/detail/{q}` | 中文 |
| PLAYZIP | `https://playzip.com/?keywords={q}` | 英文 |
| BYRUTOP | `https://byrutgame.org/index.php?do=search&subaction=search&search_start=0&full_search=0&story={q}` | 英文 |
| Gamer520 | `https://www.gamer520.com/?s={q}` | 中/英 |
| ANKERGAMES | `https://ankergames.net/search/{q}` | 英文 |
| flysheep | `https://www.flysheep6.com/?s={q}` | 中/英 |
| Nyaa | `https://sukebei.nyaa.si/?f=0&c=1_3&q={q}` | 英/日 |
| Nysoure | `https://nysoure.com/search?keyword={q}&sort=8` | 中/英/日 |
| 爱之列车 | `https://iacg.love/?s={q}&type=post&trem=4` | 中/英 |
| 稻荷 GAL | `https://inarigal.com/?search={q}` | 中/日 |
| 量子 ACG | `https://lzacg.cc/?s={q}` | 中文 |
| ACG 港湾 | `https://www.acggw.me/?post_type=post&s={q}` | 中/英（**词长 ≤10**） |
| NekoGAL | `https://www.nekogal.com/?s={q}` | 中/英/日 |
| GGBases | `https://ggbases.dlgal.com/search.so?p=0&title={q}` | 英/日 |
| Galgamex | `https://www.galgamex.net/search?q={q}` | 中/英/日 |
| 鲲 Galgame | `https://www.kungal.com/search?keywords={q}` | 中/英/日 |
| 真红(galgame.dev) | `https://galgame.dev/search?term={q}&in=titles` | 中/英/日（**需登录**） |
| 真红(shinnku) | `https://www.shinnku.com/search?q={q}` | 中/英/日 |

**只能站内搜索的 5 个站**（无 URL 模板，必须驱动搜索框）：
GAMEBOUNTY（`https://gamebounty.world/zh`）、月谣（`https://www.sayafx.top/`）、
TouchGal（`https://www.touchgal.ink/`）、梓澪（`https://zi0.cc/`）、Anime-Sharing（`https://www.anime-sharing.com/`）。

**猫盘 catcat.cloud 已从清单移除** —— 与我的实测结论一致（其 `/api/fs/search` 返回 500，meilisearch 后端损坏）。原设计规划的 `browse` 第三种 adapter 形态**随之取消**，只保留 `url` / `form` 两种。

**机地详情页实测结构**（`/topic/detail/20093940`）：
- 有：标题、封面、评分、大小（`70GB`）、类型、发行日期、Steam 好评率、完整「游戏介绍」长文、修改器列表、讨论区。
- **网盘链接不在 `<a>` 标签里**，而在整页 HTML 的 SSR JSON 中 → 提取器必须对 `document.documentElement.outerHTML` 跑正则。

### 2.1.4 URL 模板二次验证与无头检测（2026-10-17 实测）

用户给出的 17 个 URL 模板，我逐条实测（`tools\probe_verify_templates2.py`）：**16/18 通过**。
未通过的 2 个（`ankergames`、`iacg` 爱之列车）返回 **403**，进一步诊断（`tools\probe_403.py`）发现：

| 站点 | headless（默认 UA） | headful | **headless + 真实 Chrome UA** |
|---|---|---|---|
| ANKERGAMES | **403 Cloudflare** | **200（421 链接）** | **200（421 链接）** |
| 爱之列车 iacg | **403** | **200（100 链接）** | **200（100 链接）** |

→ **根因是无头模式被检测（headless fingerprint），不是站点真的拒绝。**
关键：**headless + 显式真实 UA 就能过**，不需要开窗口。

**架构决定**：

- 浏览器 context **必须显式设置真实 Chrome UA**（`user_agent=`），不能留空让 playwright 用默认 headless UA。
  - 推荐值：`Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{实际版本}.0.0.0 Safari/537.36`
  - 应**动态从 `chrome.exe --version` 或注册表读取真实版本号**，避免 UA 与真实内核不符。
- 默认仍可 `headless=True`（快、不打扰用户），但 `config.yaml` 提供 `headless: false` 开关；个别站点若在 headless+UA 下仍 403，可对该站单独降级为 headful。
- 检测到 Cloudflare 拦截页（title 含 `Attention Required` / `Just a moment` / body 含 `Cloudflare`）→ 报 `CLOUDFLARE_BLOCK`，并**建议用户开 headful 重试**。

**其余 16 站实测均可用**，含 `shinnku`（29746 字节正文、203 个候选链接）、`byrutgame`（97 个候选链接）、`nekogal`（40）、`ggbases`（20）、`gamer520`（21）、`acggw`（19）、`kungal`（17）、`galgamex`（13）。

**注意**：`jidiyouxi` 首页正文只有 160 字节但候选链接 8 个 —— 它是纯前端渲染，**不能靠 body 文本判断成败，必须数链接**。

### 2.1.5 按语言路由（2026-10-17 新增，用户确认）

用户要求：「提前告知用户如果中文名搜索不到可以再尝试英文名和日文名，后面备注了什么搜索就代表要用什么，比如中文搜索就是只能用中文，只能用英文名的网站就不纳入」。

**决策（用户已选）**：**单输入框 + 自动识别语种路由**。

- 用户只填一个搜索框。程序用字符集判定语种：
  - 含假名（`\u3040-\u30ff`）→ **日文**
  - 否则含 CJK 汉字（`\u4e00-\u9fff`）→ **中文**
  - 否则 → **英文**
- 只查询**声明支持该语种**的站点，其余站点跳过（不发起请求，UI 显示「此站不支持该语种，已跳过」）。
- **各语种实际参与站点数（已核算）**：**中文 17 站 / 英文 18 站 / 日文 12 站**（共 22 站）。
- UI 明确提示：**「没找到？试试用英文名或日文名再搜一次」**，并在输入框下方展示当前识别到的语种。
- **严格按文档执行**：日文输入时只查标了日文的 12 个站；「仅中文」「仅英文」的站跳过（用户已确认此行为）。
- 各站声明的语言如下表（来自用户清单逐站标注）：

| 语言组合 | 站点数 | 站点 |
|---|---|---|
| 仅中文 | 2 | 机地、量子 ACG |
| 仅英文 | 3 | PLAYZIP、BYRUTOP、ANKERGAMES |
| 中+英 | 5 | Gamer520、GAMEBOUNTY、flysheep、爱之列车、ACG 港湾 |
| 中+日 | 2 | 月谣、稻荷 GAL |
| 英+日 | 2 | Nyaa、GGBases |
| 中+英+日 | 8 | Nysoure、NekoGAL、TouchGal、Galgamex、鲲、梓澪、Anime-Sharing、真红 |

**已知缺口**：日文输入时只有 12 个站参与；若某游戏只有日文名而资源全在中文站，会漏。UI 的「试试中文名/英文名」提示即为此设计。


## 3. 站点注册表

来源：**`C:\Users\27025\Desktop\网站链接（更新）.md`**（2026-10-17 用户提供，22 个站点）。

> 相对旧清单的变化：**猫盘 catcat.cloud 已移除**（其搜索 API 实测损坏）；
> **所有备用站/导航页 URL 已移除**（flysheep6.top、ysepan、zi1/zi6/gal.games、acggw.cc、gal.red、moyu.moe、nav.kungal.org、aosoraclub.com、shinnku 备用域名等）；
> **新增每站的语言标注与「地址栏可用/只能站内搜索」标注**。

结构化字段：

```python
@dataclass
class Site:
    id: str                       # 稳定 slug，如 "jidiyouxi"
    name: str                     # 显示名，如 "机地"
    homepage: str                 # 主页
    kinds: list[str]              # 直链 / 网盘 / 磁力
    langs: set[str]               # {"zh", "en", "ja"} —— 由用户清单标注
    url_searchable: bool          # True=地址栏可用；False=只能站内搜索
    search: SearchSpec            # 见下
    tags: set[str]                # "%", "=", "#", "@"（旧清单符号，保留兼容）
    needs_login: bool             # galgame.dev = True
    max_query_len: int | None     # ACG 港湾 = 10
    adapter_status: str           # "verified" | "untested" | "broken"


@dataclass
class SearchSpec:
    mode: str                     # "url" | "form"
    url_template: str | None      # mode=url 时必需，含 {q}
    input_selector: str | None    # mode=form 时用
    submit_selector: str | None
    result_link_selector: str | None
    title_selector: str | None
```

### 3.1 单机（7 站）

| 站点 | 主页 | 类型 | 语言 | 搜索模式 | URL 模板 / 备注 |
|---|---|---|---|---|---|
| 机地 | `https://www.jidiyouxi.com/` | 网盘 | zh | **url** | `https://www.jidiyouxi.com/search/detail/{q}` |
| PLAYZIP | `https://playzip.com/` | 直链 | en | **url** | `https://playzip.com/?keywords={q}` |
| BYRUTOP | `https://byrutgame.org/` | 直链+磁力 | en | **url** | `https://byrutgame.org/index.php?do=search&subaction=search&search_start=0&full_search=0&story={q}` |
| Gamer520 | `https://www.gamer520.com/` | 网盘 | zh,en | **url** | `https://www.gamer520.com/?s={q}` |
| ANKERGAMES | `https://ankergames.net/` | 直链+磁力 | en | **url** | `https://ankergames.net/search/{q}` |
| GAMEBOUNTY | `https://gamebounty.world/zh` | 直链 | zh,en | **form** | 只能站内搜索 |
| flysheep 资源避难所 | `https://www.flysheep6.com/` | 网盘+磁力 | zh,en | **url** | `https://www.flysheep6.com/?s={q}` |

### 3.2 Galgame（15 站）

| 站点 | 主页 | 类型 | 语言 | 搜索模式 | URL 模板 / 备注 |
|---|---|---|---|---|---|
| 月谣 | `https://www.sayafx.top/` | 直链+网盘 | zh,ja | **form** | 只能站内搜索 |
| Nyaa | `https://sukebei.nyaa.si/` | 磁链 | en,ja | **url** | `https://sukebei.nyaa.si/?f=0&c=1_3&q={q}` |
| Nysoure | `https://nysoure.com/` | 直链 | zh,en,ja | **url** | `https://nysoure.com/search?keyword={q}&sort=8` |
| 爱之列车 | `https://iacg.love/` | 网盘 | zh,en | **url** | `https://iacg.love/?s={q}&type=post&trem=4` |
| 稻荷 GAL | `https://inarigal.com/` | 直链 | zh,ja | **url** | `https://inarigal.com/?search={q}` |
| 量子 ACG | `https://lzacg.cc/` | 直链 | zh | **url** | `https://lzacg.cc/?s={q}` |
| ACG 港湾 | `https://www.acggw.me/` | 网盘 | zh,en | **url** | `https://www.acggw.me/?post_type=post&s={q}`，**搜索词 ≤10 字符** |
| NekoGAL | `https://www.nekogal.com/` | 直链 | zh,en,ja | **url** | `https://www.nekogal.com/?s={q}` |
| GGBases | `https://ggbases.dlgal.com/` | 磁力 | en,ja | **url** | `https://ggbases.dlgal.com/search.so?p=0&title={q}` |
| TouchGal | `https://www.touchgal.ink/` | 直链+网盘 | zh,en,ja | **form** | 只能站内搜索 |
| Galgamex | `https://www.galgamex.net/` | 直链+网盘 | zh,en,ja | **url** | `https://www.galgamex.net/search?q={q}` |
| 鲲 Galgame | `https://www.kungal.com/` | 论坛网盘 | zh,en,ja | **url** | `https://www.kungal.com/search?keywords={q}` |
| 梓澪的妙妙屋 | `https://zi0.cc/` | 直链 | zh,en,ja | **form** | 只能站内搜索 |
| Anime-Sharing | `https://www.anime-sharing.com/` | 直链 | zh,en,ja | **form** | 只能站内搜索 |
| 真红的资源讨论组 | `https://galgame.dev/` | 论坛网盘+直链 | zh,en,ja | **url** | `https://galgame.dev/search?term={q}&in=titles`，**需登录** |

> 真红还有 `https://www.shinnku.com/search?q={q}` 模板（同为 url 模式）。用户标注「1 是论坛网盘，2 和 3 是直链」，但新清单只列了 `galgame.dev` 与 `shinnku.com` 两个可用模板，按此实现。

### 3.3 统计

- 总站点：**22**（单机 7 + Galgame 15）
- **url 模式**：17 站（用户实测给出模板）
- **form 模式**：5 站（GAMEBOUNTY、月谣、TouchGal、梓澪、Anime-Sharing）
- **需登录**：1 站（galgame.dev）
- **特殊限制**：1 站（ACG 港湾 ≤10 字符）

## 4. 架构

```
game-finder/
  app.py                 # 入口：起本地服务 + 打开浏览器标签页
  config.yaml            # 代理、超时、并发、端口、缓存 TTL、巡检间隔
  sites.yaml             # 站点注册表（第 3 节的结构）
  finder/
    browser.py           # Chrome 生命周期、profile 检测、UA、代理注入、页面池
    sites.py             # 载入 sites.yaml → Site 对象
    lang.py              # 语种判定（纯函数）+ 按语种筛选站点（纯函数，可离线单测）
    search.py            # 站内搜索：url / form 双模式
    detail.py            # 详情页抽取：简介/版本/大小/下载链
    health.py            # 可用性巡检 + 状态落盘
    store.py             # SQLite：结果缓存 + 健康历史
    models.py            # dataclass：Site / SearchSpec / SearchHit / GameDetail / HealthRecord
    web/
      server.py          # FastAPI 路由 + SSE 流式推送
      static/index.html  # 单页界面
  tests/
    fixtures/<site_id>/*.html   # 存档 HTML，离线回归
    test_lang_route.py          # 语种判定与路由（纯函数，无网络）
    test_sites_yaml.py          # 22 条目载入与字段合法性
    test_search_parse.py
    test_detail_parse.py
    test_health_state.py
  tools/
    smoke_live.py        # 手动跑真站冒烟
```

### 数据流

```
用户输入关键词
  → POST /api/search  {query, site_ids?}
  → lang.detect(query) → "zh" | "en" | "ja"
  → lang.filter_sites(all_sites, lang) → 参与站点集合（其余标记 LANG_MISMATCH）
  → 为每个参与站点起一个 asyncio task
       ├─ 打开/复用 page → url 模式 goto 模板 / form 模式驱动搜索框
       ├─ 取前 N 条结果 → 选最匹配的一条 → 进详情页（detail.py）
       └─ 产出 GameDetail，SSE 推给前端（先完成先渲染）
  → 结果写入 SQLite 缓存（TTL 内同关键词直接命中）
```

### 浏览器层 `browser.py`

- 接法：`playwright.chromium.launch_persistent_context(user_data_dir=<专用 profile>, channel="chrome", headless=..., proxy=..., user_agent=...)`。
- **profile 路径**：`<project>/chrome-profile/`（**非默认路径**，见 §2.1.1；用默认路径会被 Chrome 拒绝开启 DevTools）。
- **UA 必须显式设置**（见 §2.1.4）：不留空，否则 headless 默认 UA 会被 Cloudflare 识别。UA 中的 Chrome 版本应动态读取真实版本。
- **headless 默认 `True`**，`config.yaml` 可切 `False`；个别站在 headless+UA 下仍 403 时，该站单独降级为 headful。
- **占用检测**：以「启动失败 + 捕获错误」为判据（锁文件机制不可靠）→ 返回 `PROFILE_IN_USE`。
- **并发**：单个 browser context，页面池上限默认 4（`config.yaml` 可调）。同站请求串行，跨站并行——避免把单站打出风控。
- **代理**：Playwright 的 `proxy` 是 **context 级**，而持久化 profile **只能开一个 context** → **做不到按站点分流代理**。
  - 采用：**整个 context 统一走 `config.proxy.server`**（**`http://127.0.0.1:6234`**，见 §2.1.2）。
  - `config.proxy.enabled: false` 时纯直连；失败报 `NEEDS_PROXY`。
- **反风控**：`--disable-blink-features=AutomationControlled` + 真实 UA；不做激进注入。
- **礼貌**：同域请求最小间隔（默认 1.5s）、单次搜索每站最多抓 1 个详情页。

### 搜索层 `search.py`

**核心：双模式，每站模式已在 §3 钉死（用户实测给出），不需要 `auto` 试错。**

```yaml
search:
  mode: url          # "url"（地址栏） | "form"（驱动搜索框）
  url_template: "https://example.com/?s={q}"   # mode=url 时必需；{q} 会被 URL 编码
  # mode=form 时用以下覆盖配置：
  input_selector: "input#search"
  submit_selector: "button[type=submit]"
  result_link_selector: ".post h2 a"
  title_selector: ".post h2 a"
```

**模式 A：`url`（17 站）** —— 直接 `page.goto(url_template.format(q=quote(query)))`。快、稳。

**模式 B：`form`（5 站：GAMEBOUNTY、月谣、TouchGal、梓澪、Anime-Sharing）** —— 只能站内搜索，必须驱动搜索框：
- 站点配置优先；配置缺失或选择器 0 命中时回退通用启发式。
- 通用启发式找搜索框：`input[type=search]` → `input[name*=s|q|kw|wd|keyword|search]` → `input[id*=search|kw]` → placeholder 含 `搜索|search|关键词` → 任意可见 `input[type=text]`（最后手段，需可见且有 form 祖先）。
- 提交：优先按 Enter（`press("Enter")`），次选同 form 的 `button[type=submit]` / `input[type=submit]` / 文本含「搜索」的按钮。
- **绝不用地址栏做「搜索引擎式」搜索**（不把 `site:xxx 关键词` 丢给百度/Google）。

**语种路由（新增，§2.1.5）**：
- 搜索前先判定语种（zh/en/ja），**只对 `langs` 含该语种的站点发起请求**。
- 被跳过的站点返回 `LANG_MISMATCH`，UI 置灰显示，不占耗时。
- **ACG 港湾特例**：`max_query_len=10`，超长时先按字符截断再搜，并在卡片上标注「已截断」。
- **galgame.dev 特例**：`needs_login=True`，未登录时会被重定向 → 报 `NEEDS_LOGIN`。

**结果抽取（两种模式共用）**：
- **必须数链接，不能看正文长度**：`jidiyouxi` 正文仅 160 字节但能出结果（§2.1.4）。
- 先试常见结果容器（`article`、`.post`、`.entry`、`.item`、`li`、`tr`、`.result`、`.thread`）内的 `<a href>`，再退回全页链接——**过滤掉导航/页脚/外链**（同域优先、排除 `login|register|tag|category|page/\d|javascript:`）。
- **Cloudflare 识别**：title 含 `Attention Required` / `Just a moment`，或 body 含 `Cloudflare` → 报 `CLOUDFLARE_BLOCK`（不是 `SELECTOR_BROKEN`）。
- **超时**：单站搜索 15s、详情页 15s（可配）。超时按 `TIMEOUT` 记录。
- **结果匹配**：结果标题与用户关键词做归一化匹配（大小写、全半角、繁简、去符号）打分，取最高分；低于阈值仍返回前 1 条但标记 `low_confidence`。

### 详情层 `detail.py`

抽取字段（缺就留空，不猜）：

- `title`、`cover_url`（`og:image` 优先）
- `intro`：优先 `og:description` / `meta[name=description]`，再退回正文容器（`article`、`.content`、`.post-content`、`.entry-content`、`.markdown-body`）取前 ~1500 字
- `version` / `size` / `updated_at`：正则扫正文与表格（`v?\d+(\.\d+)+`、`\d+(\.\d+)?\s?(GB|MB|G|M)`、`20\d{2}[-/年.]\d{1,2}[-/月.]\d{1,2}`）
- `downloads: list[Download]`，`Download = {kind: direct|pan|magnet|unknown, url, label, code?}`
  - `magnet:` 前缀 → `magnet`
  - 已知网盘域（`pan.baidu.com`、`pan.quark.cn`、`aliyundrive.com`/`alipan.com`、`115.com`、`123pan.com`、`lanzou*.com`、`cowtransfer.com`、`mega.nz`、`1fichier.com`、`mediafire.com`、`drive.google.com`、`mypikpak.com`…）→ `pan`，并在同页文本里找提取码（`提取码|密码|访问码|pwd|code` 后 4 位字母数字）
  - 同域且路径含 `download|dl|down|file` → `direct`
  - 其余 http(s) → `unknown`（仍展示，用户自行判断）

### 健康巡检 `health.py`

- 触发：应用启动后延迟 60s 跑一次；之后每 `config.health.interval_hours`（默认 6h）跑一次；UI 有「立即检查」按钮。
- 判定（用户已选「跑一次站内搜索才算可用」）：
  1. 打开首页 → 记录 `reachable`（HTTP 成功且非错误页）
  2. **按该站自己的模式**跑一次真实搜索（`url` 模式构造 URL；`form` 模式驱动搜索框）→ 有 ≥1 条结果则 `ok`
  3. 状态机：`ok` / `degraded`（首页能开但搜索 0 结果）/ `unreachable`（网络失败）/ `needs_proxy` / `needs_login` / `cloudflare_block` / `selector_broken` / `unknown`
- **探测词按语种分别配置**（2026-10-17 新增，替代旧的单一 `AI`）：
  ```yaml
  health:
    probe_words:
      zh: "终焉之莉莉"
      en: "enderlilies"
      ja: "制服カノジョ"
  ```
  巡检某站时，**用该站支持的第一个语种的探测词**（优先 zh → en → ja）。
  这样既保证探测词在该站确实有结果，也顺带验证语种路由的正确性。
- 落盘：`health.json`（当前状态快照，UI 读）+ SQLite `health_history`（历史）。
- 结果同时**回写 `sites.yaml` 的 `adapter_status`**（ok 多次 → `verified`；连续失败 → `broken`）。

### 存储 `store.py`

SQLite（`data/finder.db`）：

- `search_cache(query_norm, site_id, payload_json, created_at)`，TTL 默认 12h
- `health_history(site_id, status, latency_ms, reason, checked_at)`
- 纯标准库 `sqlite3`，无 ORM。

### 界面（单页）

- 顶部：搜索框 + 「搜索」按钮。
- **语种提示（2026-10-17 新增）**：搜索框下方实时显示识别到的语种徽章（中文 / 英文 / 日文），并在搜索后若结果为空，显示醒目提示：
  **「没找到？试试用英文名或日文名再搜一次」** —— 这是用户明确要求的引导。
- **语种路由可视化**：结果区顶部显示「本次参与搜索 N 个站点（中文），已跳过 M 个不支持该语种的站点」。
- 站点多选：按语言分组展示；不支持当前语种的站点置灰并标注「不支持中文/英文/日文」。
- 中部：结果区，按站点分组的卡片流。每张卡片：站点名 + 健康徽章 + 模式徽章（`URL` / `搜索框`）、封面缩略图、标题、简介（可展开）、版本/大小/更新时间、下载按钮组（直链/网盘/磁力配色区分，网盘显示提取码并带一键复制）。
- 右侧/底部：站点健康面板（表格：站名 / 状态 / 语言 / 有效模式 / 耗时 / 原因 / 上次检查 / 「立即检查」）。
- 状态可见：正在搜索的站点显示 spinner；失败的站点卡片显示具体原因（`TIMEOUT` / `PROFILE_IN_USE` / `NEEDS_LOGIN` / `NEEDS_PROXY` / `SELECTOR_BROKEN` / `LANG_MISMATCH`），**不吞错**。
- 技术：FastAPI + `text/event-stream`（SSE）流式推送；前端单个 `index.html`（原生 JS，无构建步骤，无 npm 依赖）。

## 5. 错误处理

统一错误码，UI 直显原因与建议动作：

| 码 | 含义 | UI 提示 |
|---|---|---|
| `PROFILE_IN_USE` | 专用 profile 被占用 | 「浏览器 profile 被占用，请关闭上次残留的窗口后重试」 |
| `BROWSER_NOT_FOUND` | 找不到 chrome.exe | 「请在 config.yaml 指定 chrome_path」 |
| `NEEDS_PROXY` | 站点连不上且代理未启用 | 「此站连不上，请确认代理已开 + config.yaml 端口正确」 |
| `NEEDS_LOGIN` | 跳到登录页（galgame.dev） | 「此站需登录，请在打开的浏览器里登录一次（登录态会持久化）」 |
| `CLOUDFLARE_BLOCK` | 被 Cloudflare 拦截 | 「此站拦了自动访问，可在 config.yaml 开 headless: false 重试」 |
| `SELECTOR_BROKEN` | 站点改版，选择器失效 | 「此站解析失效，需更新 sites.yaml」 |
| `TIMEOUT` | 超时 | 「站点响应超时，稍后重试」 |
| `LANG_MISMATCH` | 该站不支持当前输入语种 | 「此站只支持英文/日文，已跳过」 |
| `QUERY_TOO_LONG` | 超出站点词长限制（ACG 港湾 ≤10） | 「搜索词超过此站 10 字上限，已截断」 |
| `UNSUPPORTED` | 该站不支持搜索 | 「此站不支持搜索，仅作入口」 |

## 6. 测试策略

遵循工作区既有纪律：**验收看产物，不看退出码**。

1. **离线解析测试**（主）：每站抓一份真实搜索结果页 + 详情页存为 `tests/fixtures/<site_id>/*.html`，用 pytest 断言解析出的字段。不打网络，可重复。
2. **站点注册表测试**：`sites.yaml` 能完整载入 **22 条目**；每个 `Site` 字段合法；`langs` 合法（⊆ {zh,en,ja}）；`url_searchable` 与 `search.mode` 一致（url_searchable=True ⇒ mode="url"）；`max_query_len` 对 ACG 港湾生效。
3. **语种路由测试**（2026-10-17 新增）：给定 `终焉之莉莉`→zh、`enderlilies`→en、`リリィ`→ja、混合串的判定正确；断言各语种被选中的站点集合大小恰好是 **zh=17 / en=18 / ja=12**（已核算）。**这是纯函数，必须离线单测。**
4. **健康状态机测试**：给定 mock 的探测结果序列，断言状态转移与 `health.json` 内容。
5. **冒烟测试**（手动，`tools/smoke_live.py`）：对指定站点跑真站搜索，输出「站名 / 状态 / 结果数 / 耗时」，用于适配新站时验证。
6. **验收判据**（每站适配完成的定义）：`smoke_live.py` 对该站跑通 → 保存 fixture → pytest 通过 → 该站 `adapter_status = verified`。

**不写**：端到端全站自动化（网络不稳定，会变成 flaky 测试垃圾场）。

## 7. 分期实施

- **P0 骨架**：项目结构、`config.yaml`、`sites.yaml`（**22 条目**结构化）、models（含 `langs`）、语种判定纯函数、SQLite store、FastAPI 空壳 + 能起服务开标签页。
- **P1 浏览器层**：Chrome 持久化 context（**专用 profile，非默认路径**）、profile 占用检测、**显式代理 `http://127.0.0.1:6234`**、页面池。
- **P2 搜索层**：`url` 模式（17 站模板已由用户实测给出）+ `form` 模式（5 站）+ 详情页抽取；**首批打通 2 站：机地（中文）+ Gamer520（中英）** —— 两站都已端到端实测可抓，且能验证语种路由的两条分支。
- **P3 界面**：SSE 流式结果卡片 + 下载链 + 健康面板 + **语种徽章与「试试英文名/日文名」提示**。
- **P4 健康巡检**：状态机、定时、落盘、回写 `adapter_status`。
- **P5 铺开适配**：按站点逐批补选择器 + fixture，优先 url 模式的 17 站（模板已有，只需验证解析）；5 个 form 模式的站最后（需要实测搜索框）。
- ~~**P6 用用户实测结果校准模式**~~ → **已完成**：用户 2026-10-17 直接提供了每站的可用 URL 模板与「地址栏可用/只能站内搜索」标注，已写入 §3。**不再需要 `mode: auto` 试错机制**，每站模式已钉死。

**P2 结束即可交付可用版本**（2 站能搜能出链接 + 语种路由生效），之后是增量铺站点。

## 8. 风险与未决问题

### 风险

1. **抓取成功率不承诺**：22 个站里有论坛型（鲲、真红）和可能带 Cloudflare 的站，真实成功率**必须逐站实测**才知道。缓解：先做 url 模式的 17 站（模板已知，风险最低），失败明确报码，不假装成功。
2. **`form` 模式的 5 站是最大不确定项**：GAMEBOUNTY、月谣、TouchGal、梓澪、Anime-Sharing 只能站内搜索，搜索框选择器尚未实测。缓解：P5 阶段逐站实测并固化选择器；失败则该站降级为「仅给主页入口」。
3. **galgame.dev 需登录**：未登录时搜索会被拦截。缓解：`NEEDS_LOGIN` 错误码 + 引导用户在专用 profile 里登录一次（登录态可持久化，已验证）。
4. **站点改版**会让选择器失效。缓解：`SELECTOR_BROKEN` 状态 + 通用回退 + fixture 回归；巡检回写 `adapter_status` 让失效可见。
5. **日文输入覆盖面窄**：只有 12 个站支持日文，若某游戏资源全在中文站会漏。缓解：UI 明确提示换语种重搜（用户已确认此设计）。
6. **法律/合规**：这些站点分发的是盗版游戏资源。本项目定位**个人自用检索工具**，不下载、不分发、不绕过付费墙；不做公开部署。此为个人使用边界，用户已知悉。

### 已解决的历史风险（保留记录，勿再踩）

- ~~Python 3.14 兼容性~~ → **已实测通过**：playwright 1.64.0 在 Python 3.14.6 上可正常驱动 Chrome，无需 3.12 venv。
- ~~复用用户真实 Chrome profile~~ → **已实测推翻**：Chrome 155 禁止对默认 user-data-dir 开放 DevTools。改用专用 profile，见 §2.1.1。
- ~~代理端口 7890~~ → **实测为 6234**，见 §2.1.2。
- ~~猫盘作为 P2 站点~~ → 其搜索 API 返回 500，用户已从清单移除。

### 未决问题

**已确认（用户 2026-10-17）**：

1. ~~哪些站不能地址栏搜索~~ → 用户已提供完整实测清单（5 个 form 站），见 §3。
2. ~~搜索语言策略~~ → **单输入框 + 自动识别语种路由**，只查声明支持该语种的站点。
3. ~~日文输入时是否放宽~~ → **严格按文档**：只查标了日文的 12 个站。

**仍待确认**：

1. **是否需要「下载到本地」按钮** —— 本设计只给链接。**暂按「只给链接」实现**。
2. **探测词** —— 已改为**按语种各一个**（zh=`终焉之莉莉`、en=`enderlilies`、ja=`制服カノジョ`），见 §4 健康巡检。**已由用户确认**。
