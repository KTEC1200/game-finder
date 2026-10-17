# Game Finder — 工作进度记录（交接文档）

> 记录时间：2026-10-16（用户关机前）
> 项目根目录：`C:\Users\27025\Desktop\game-finder\`
> 设计文档：`docs\superpowers\specs\2026-10-16-game-finder-design.md`

---

## 一、任务目标（用户原始需求）

用户原话（m00001）：

> 开发一个简单的 windows 应用，主要功能是根据用户输入的游戏名称在提供的网站中进行检索并提供具体的内容介绍和下载链接（可以操纵浏览器），定期检查网站可用性，部分网站只能进行站内搜索，无法进行地址栏搜索，注意。

网站清单来源：`C:\Users\27025\Desktop\网站链接.md`（23 个站点 / 35 个 URL）。

**用户后续指令（m00123）**：

> 先按照阶段来，P6我等你把基础工作跑通准备测试网站再发你，没有？？？就是无待检查的意思

含义：按阶段推进；P6 等基础跑通、我准备好测试站点后，用户再发"哪些站点不能地址栏搜索"的清单；清单里没有 `？？？` 条目 = 当前没有待检查的站点。

---

## 二、已确认的设计决策（全部经用户确认）

| 项 | 决策 | 依据 |
|---|---|---|
| 形态 | **本地 Web UI**：Python + FastAPI + Playwright，起本地服务并开浏览器标签页 | m00044 选项 A |
| 浏览器 | 原计划：复用用户已登录的真实 Chrome profile | m00044 选项 (a) —— **已被实测推翻，见 §四** |
| 代理 | 自动使用本地代理 | **实测为 `http://127.0.0.1:6234`，不是 7890** |
| 适配策略 | 混合：能 URL 就 `mode: url`，只能站内搜索就 `mode: form`，默认 `mode: auto` | m00083 第 5 项 |
| 深度 | 结果列表 + **自动进详情页**抓简介和下载链接 | 用户选了推荐项 |
| 可用性判定 | 站点"可用"= **真实站内搜索返回 ≥1 条结果** | 用户选了推荐项，探测词默认 `AI` |
| `#` 站点 | **默认显示**（带警示色角标），另给临时"隐藏 # 站点"开关 | m00083 第 3 项 |
| Galgamex | 其 `#` 表示"站点自身可配置是否包含敏感内容" → `sensitive_configurable=True`，单独开关 | m00083 第 1 项 |
| 项目根 | `C:\Users\27025\Desktop\game-finder\` | m00083 第 4 项 |

非目标（YAGNI）：不下载游戏、不做账号注册、不整站爬取、不做云同步/多用户/移动端、不自动更新站点列表。本版**只给链接**，无"下载到本地"按钮。

---

## 三、当前进度：处于 P1（浏览器层）验证完成、P2（搜索层）适配器验证基本完成，但**实现代码一行未写**

### 阶段计划（spec §7）

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 | 骨架 | 未开始（目录结构已有，代码无） |
| P1 | 浏览器层 | **验证完成**（结论见 §四），代码未写 |
| P2 | 搜索层，3 个站点打通 = **可交付版本** | **2/3 站点已验证可抓**，第 3 个待定（见 §六） |
| P3 | UI / SSE | 未开始 |
| P4 | 健康巡检 | 未开始 |
| P5 | 铺开适配器（`=`/`%` 优先，`@` 最后） | 未开始 |
| P6 | 按用户实测清单固定搜索模式 | **等用户发清单** |

### 尚未完成的关键动作

1. **实现计划（writing-plans）尚未产出** —— 已加载 writing-plans 技能并宣布使用，但计划文档还没写。下一步就是它。
2. 所有探测脚本都在 `tools\probe_*.py`，**`finder\` 包、`app.py`、`config.yaml`、`sites.yaml` 都还不存在**。
3. `tests\fixtures\` 里已有 4 个真实页面快照，可直接用于离线解析测试。

---

## 四、重大架构修正（实测推翻原设计，写计划前必须采纳）

### 4.1 无法驱动用户的真实 Chrome profile（决定性）

**根因（Chrome 自己的原话，不是推断）**：

```
DevTools remote debugging requires a non-default data directory. Specify this using --user-data-dir.
```

Chrome ≥136 在 `--user-data-dir` 指向**默认目录**时**拒绝开启 DevTools 远程调试**。playwright 的 pipe 和 `--remote-debugging-port` 都被挡。

实测矩阵（详见 `tools\probe_profile_hang.py`、`probe_real_profile_cdp.py`、`probe_default_dir_ban.py`、`probe_chrome_stderr.py`）：

| 配置 | 结果 |
|---|---|
| 临时 profile + headless | OK |
| **真实 profile + headless** | **FAIL TimeoutError 45s** |
| **真实 profile + headful** | **FAIL** |
| 真实 profile + `--disable-extensions` | FAIL（推翻"扩展导致"假设） |
| 真实 profile + `--remote-debugging-port=9222` | FAIL，devtools 端点起不来 |
| **完整复制到非默认路径** | **OK**（推翻"体积/锁导致"假设） |
| 复制后用同一路径启动 | **cookie 行被清空**（文件大小不变） |

**结论**：既不能驱动真实 profile，也不能"复制一份来复用登录态"。

### 4.2 但专用 profile 是可用的，且能持久化登录态

- 非默认路径的专用 profile **能正常启动**，`headless=False` 和 headless 都行。
- 服务端下发的 cookie（带 `Max-Age`/`Expires`）**能跨启动持久化**。
- 早期"专用 profile 持久化 BROKEN"的结论是**我的实验做错了**：probe 7/12 用 `ctx.add_cookies()` 时没给 `expires`，创建的是会话 cookie，关浏览器就死——这是设计行为，不是 Chrome 缺陷。probe 8 用本地 HTTP 服务器下发 `Max-Age=86400` 的 cookie，**两次启动都在**。
- 因此：**用户在应用自己的浏览器里登录一次，登录态会留住**。这是可行方案。

### 4.3 代理必须显式设置，且端口是 6234

从 WinINET 注册表读到系统代理：`HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings` → `ProxyEnable=1`，**`ProxyServer=127.0.0.1:6234`**，端口由 `AtlasCore_amd64`（pid 20212）监听。spec 里写的 7890 是**错的**。

代理矩阵实测（`tools\probe_proxy_matrix.py` → `probe_proxy_matrix.json`）：

| 配置 | jidiyouxi | gamer520 | catcat | anime-sharing | nyaa |
|---|---|---|---|---|---|
| A `--no-proxy-server`（真直连） | OK | OK | OK | OK | **FAIL 超时 25s** |
| B 不传 proxy 参数（走系统代理） | **FAIL 超时 25s** | OK | OK | OK | OK |
| **C 显式 `proxy={"server":"http://127.0.0.1:6234"}`** | **OK 1588ms** | **OK 1114ms** | **OK 1515ms** | **OK 1895ms** | **OK 2412ms** |

→ **只有"显式 6234"这一个配置对所有站点都通。** 真直连挂 nyaa；走系统代理挂 jidiyouxi。

---

## 五、P2 两个站点已验证可抓（探测 #38 端到端实测）

探测脚本 `tools\probe_e2e.py`，查询词 `剑星`，结果 `tools\probe_e2e.json` / `_e2e.txt`。

### 5.1 机地 jidiyouxi.com —— `mode: url`

- 搜索 URL 模板：**`https://www.jidiyouxi.com/search/detail/{q}`**（`{q}` 需 URL 编码）
- 详情链接正则：`jidiyouxi\.com/topic/detail/\d+`，实测 **40 条**结果
- 详情页字段实测（3 张卡片全部成功）：

| 字段 | 来源 | 实测样例 |
|---|---|---|
| title | `og:title` | `剑星中文版学习版免费下载 攻略秘籍剧情游戏讨论分享存档吐槽` |
| **cover** | **`<link rel="preload" as="image">` 的 href**（`og:image` 是坏的，见下） | `https://img2.52jidi.com/topic/cover/id/649608/sz/420` |
| intro | `og:description` | `2026年10月13日 更新 领略由韩国开发商 SHIFT UP 倾情制作…` |
| size | 正文 `\d+(?:\.\d+)?\s?(?:GB\|MB)` | `75GB` |
| version | 正文版本号正则 | `V1.4.1.FIX5` |
| date | `20\d{2}[-/年.]\d{1,2}[-/月.]\d{1,2}` | `2025/6/12`（游戏发行日期） |
| 网盘链接 | 整页 HTML 正则 | **20 条**，如 `https://pan.baidu.com/s/1Uf4KDyLPwWFvGUbp1U3jBw?pwd=h2bb` |
| 提取码 | `(?:提取码\|密码\|pwd)\s*[:：=]?\s*([a-zA-Z0-9]{4})` | `['6dfb','8888','9ht2','ba53','h2bb','jidi','lqtz','rfd8']` |

**两个坑（必须写进适配器）**：

1. **`og:image` 的值是字符串 `"[object Object]"`** —— 站点自己的 React bug。封面必须从 `<link rel="preload" as="image" href="https://img2.52jidi.com/topic/cover/id/{id}/sz/420">` 取。
2. **网盘链接不在可见 DOM 的 `<a>` 里**，而在页面内嵌的 `#appState`（SSR JSON，`window.APP_INITIAL_STATE=` 前缀）以及 HTML 正则里。**详情页 `<a>` 标签里 0 个外部链接**，但整页 HTML 正则能抓到 20 条。→ 提取器应对 `document.documentElement.outerHTML` 跑正则，不要只扫 `a[href]`。

**文件夹机制（探测 #32–#37）**：
- 详情页有 tab 栏：`本体 / mod / 修改器 / 讨论求助`（class `flex cursor-pointer flex-col`）。
- `folder_list` 形如 `[{"folder_id":7,"folder_name":"本体"...},{"folder_id":8,"folder_name":"修改器"},{"folder_id":10,"folder_name":"讨论求助"}]`。
- **不同游戏默认 tab 不同**：剑星默认 `selectedNav=7`（本体，SSR 就带 18 条网盘链接）；AI LIMIT 默认 `selectedNav=8`（修改器，只有修改器链接）。
- 点 tab **确实切换 DOM**（点 mod 后 mod 标题出现）。早期"点击无效"是我的**测量错误**：`#appState` 是服务端渲染的 script 标签，客户端切 tab 后**不会更新**，我却拿它当判据。**要测 tab 切换必须读渲染后的 DOM / `body.innerText`，不能读 `#appState`。**
- 游戏本体资源列表在"本体" tab 下渲染，每条资源带 助手/迅雷/百度/夸克 按钮和版本号（如 `【亲测】解压即撸\| Build.24463856 \|赠超级MOD整合包-豪华中文-全DLC+预购特典《剑星》`）。

### 5.2 Gamer520 —— `mode: url` + **两步下载跳转**

- 搜索 URL 模板：**`https://www.gamer520.com/?s={q}`**（`{q}` 需 URL 编码）
- 详情链接正则：`gamer520\.com/\d+\.html`
- 详情页字段实测：

| 字段 | 实测样例 |
|---|---|
| title | `剑星\|豪华中文\|Build.24463856+超级MOD整合+预购特典+全DLC-支持手柄\|解压即撸\|-Switch520` |
| cover | `https://img.odbgo.com/i/2026/10/13/6acd90b27e3e7.jpg`（`og:image` 正常） |
| intro | `og:description` / `meta[description]` |
| size | 正文 `16 GB` |
| date | `2026年10月13` |

**下载流程（探测 #39–#41，关键）**：

1. 详情页上**没有直接网盘链接**，控制按钮是：
   ```html
   <a class="go-downblank btn btn--secondary btn--block" href="https://www.gamer520.com/go?post_id=123857">立即下载</a>
   ```
2. 该链接**开新标签页（popup）**，主页面不跳转。playwright 要用 `page.expect_popup()`。
3. **popup 落到第三方域名 `https://520.gamers520.com/{article_id}.html`**（本例 `/41170.html`），那里才有真链接。
4. 但 **`https://www.gamer520.com/go?post_id={id}` 直接 `page.goto` 也能到同一个落地页**（探测 #41 的 `direct` 结果与 popup 完全一致）→ **适配器可以直接 goto，不必处理 popup**，更稳。
5. 落地页字段（`https://520.gamers520.com/41170.html`，title `A311150-白嫖者联盟-游戏小乐园`）：
   - 百度：`https://pan.baidu.com/s/1Vrpjt1Gmb1Tgg8T4XBHzxQ?pwd=dysb`，**提取码 `wtes`**（注意：链接里的 pwd 和页面写的提取码可能不同，页面文字是权威）
   - 夸克：`https://pan.quark.cn/s/492f5bfa24da`（页面文字给 `492f5bfa24da`，另有二维码）
   - 迅雷：`https://pan.xunlei.com/s/VP3mzThYqBiBrRYPUBfqfP7gA1?pwd=bgqp`
   - 解压密码：`laoquzhang.com`（页面文字 `解压密码:laoquzhang.com`）
   - **另有二维码形式的链接**：`https://api.qrserver.com/v1/create-qr-code/?...&data=<urlencoded pan url>` → 适配器应 `unquote(data参数)` 把二维码里的链接也解出来。
6. 详情页还有 **`文件密码：A311150`** 和 `有效期/最近更新` 字段（在 `.pay-box` / `.pay--content` 里）。

**注意**：Gamer520 搜索结果的**第 2 条曾返回 Cloudflare 拦截页**（title `Access denied | www.gamer520.com used Cloudflare to restrict access`，探测 #38）。适配器必须能识别这种拦截页并报 `SELECTOR_BROKEN` / `NEEDS_PROXY`，而不是当成正常卡片。

### 5.3 猫盘 catcat.cloud —— **不能作为 P2 搜索站点**

- 它是 **Alist/OpenList 网盘**，不是普通搜索站：`/api/public/settings`、`/api/fs/list`、`/api/fs/get` 等接口，页面有 `Book, CosAV, GalGame, PikPak, Strong, comic, ftp` 目录，标注 `GalGame 默认解压密码：south-plus`。
- 它自己的搜索 API **是坏的**：
  ```
  POST /api/fs/search → HTTP 200，body:
  {"code":500,"message":"unaccepted status code found: 403 expected: [200],
   MeilisearchApiError Message: empty meilisearch message
   (path \"POST /indexes/openlist/search\" ...)","data":null}
  ```
- Ctrl+K 能唤出搜索面板（1 个可见 input），但后端 500。
- **→ spec 里把 catcat 列为 P2 三个站点之一是不成立的。** P2 需要一个替代站点。

---

## 六、当前唯一未决问题：P2 的第三个站点选谁

探测 #42（`tools\probe_gal.py`）**刚被用户关机打断，未产出结果**（`probe_gal.json` / `_gal.txt` 均未写入，后台任务 pwsh-160 已 kill）。

该探测的设计：对 4 个 galgame 候选站点测试搜索 URL 模板 + 详情链接数 + 单卡提取：
- `touchgal.ink` —— 试 `/?q={q}`、`/search?q={q}`、`/?s={q}`
- `ggbases.dlgal.com` —— 试 `/search?q={q}`、`/?q={q}`、`/search.html?q={q}`
- `nekogal.com` —— 试 `/search?q={q}`、`/?s={q}`、`/search/{q}`
- `lzacg.cc` —— 试 `/?s={q}`、`/search?q={q}`、`/search/{q}`

测试查询词：`千恋万花`。脚本会自动选详情链接最多的那次尝试，并提取 1 张卡片（title/og:*/网盘链接/magnet 数/正文头部）。

**恢复后第一件事**：直接重跑 `python tools\probe_gal.py`，从 4 个候选里挑一个能用的作为 P2 第三站。

其它候选（还没测）：`kungal.com`（探测 #10 显示 200/2632ms 可达）、`galgamex.net`、`sayafx.top`、`iacg.love`、`acggw.me`、`zi0.cc`、`anime-sharing.com`。

---

## 七、环境与工具事实（避免重复踩坑）

- **Python 3.14.6**；已装 `playwright 1.64.0`、`pyyaml`、`uvicorn`、`pytest`、`pytest-asyncio`。**不需要** spec 里说的 3.12 venv 兜底 —— playwright 在 3.14 上跑得通。
- Chrome：`C:\Program Files\Google\Chrome\Application\chrome.exe`，版本 **155.0.8059.80**。
- `python -m playwright install chromium` 已执行。
- 探测脚本统一用的启动配置：
  ```python
  p.chromium.launch_persistent_context(
      user_data_dir=r"D:\K\deepseek\_gf_<probe_name>",   # 非默认路径！
      channel="chrome",
      executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
      headless=True,
      timeout=60_000,
      proxy={"server": "http://127.0.0.1:6234"},
  )
  ```
- **Windows 控制台是 GBK**：任何打印页面标题/正文的脚本都会因 emoji 崩掉。已踩 3 次（`U+1F433`、`U+1F48B`、`U+2757`、`U+1F447`）。**规则：脚本只把结果写 UTF-8 文件，stdout 只打 ASCII；读结果用 `Get-Content -Encoding UTF8`。**
- **不要在 pwsh 命令里写 CJK 字面量**（会乱码），让 Python 自己从文件系统/常量里取。
- 探测用的 profile 目录在 `D:\K\deepseek\_gf_*`，**可以随时删**（除 cookie 持久化测试外无价值）。
- 用户环境为**完全权限**，**不要传 `sandbox_permissions`**（会被自动拒绝）。

---

## 八、已产出的资产

### 设计文档
`docs\superpowers\specs\2026-10-16-game-finder-design.md`（29158 字节）
章节：1 目标/非目标、2 约束、3 站点注册表、4 架构（`browser.py`/`sites.py`/`search.py`/`detail.py`/`health.py`/`store.py`/`models.py`/`web/server.py` + `static/index.html`）、5 错误码、6 测试策略、7 阶段 P0–P6、8 风险与开放问题。
**注意：§2 的浏览器约束、§4 的 `browser.py`、代理端口都已被实测推翻/修正，写实现计划时必须按 §四 采纳新结论。**

错误码（spec §5）：`PROFILE_IN_USE`、`BROWSER_NOT_FOUND`、`NEEDS_PROXY`、`NEEDS_LOGIN`、`SELECTOR_BROKEN`、`TIMEOUT`、`UNSUPPORTED`。

### 离线测试夹具（可直接用）
- `tests\fixtures\jidiyouxi\search_ai.html`（146 KB）—— 搜索结果页
- `tests\fixtures\jidiyouxi\detail_xingxing.html`（1.68 MB）—— 剑星详情页完整 DOM（默认"本体" tab，含 18+ 条网盘链接）
- `tests\fixtures\jidiyouxi\detail_ailimit.html`（991 KB）—— AI LIMIT 详情页完整 DOM（默认"修改器" tab，对比用）
- `tests\fixtures\gamer520\search_ai.html`（79 KB）—— 搜索结果页
- `tests\fixtures\gamer520\detail_sample.html`（67 KB）—— 详情页（含 `a.go-downblank` 按钮）
- `tests\fixtures\gamer520\go_landing_sample.html`（51 KB）—— **`/go` 跳转落地页**（第三方域 `520.gamers520.com`，含百度/夸克/迅雷真链接 + 二维码）
- `tests\fixtures\gamer520\_go_landing_note.txt` —— 落地页文字说明（提取码、解压密码、锚点清单）
- `tests\fixtures\catcat\home.html`（76 KB）—— Alist 首页（证明其非搜索站）

这两份 jidiyouxi 详情页夹具是**唯一**能离线验证"网盘链接藏在整页 HTML 而非 `<a>` 标签"这一关键结论的样本，别删。

### 探测脚本（`tools\`，共 30+ 个 `probe_*.py`）
有价值的几个：
- `probe_proxy_matrix.py` → 代理三配置矩阵（§4.3）
- `probe_chrome_stderr.py` → Chrome 拒绝默认目录的原话（§4.1）
- `probe_cookie_and_proxy.py` → cookie 持久化正解（§4.2）
- `probe_e2e.py` → P2 两站端到端抓取（§五）
- `probe_go2.py` → Gamer520 下载跳转落地页（§5.2）
- `probe_folder5.py` / `probe_body.py` → jidiyouxi tab 机制与本体 tab 内容（§5.1）
- `probe_gal.py` → **未跑完**，P2 第三站选型（§六）

### 待清理
`tools\_*.txt` / `tools\_*.html` / `tools\_*.json` / `tools\_*.js` 是探测中间产物（约 4 MB，其中 `_body_after_tab.html` 1.68 MB、`_topic_full.html` 991 KB、`_appstate.json` 899 KB、`_appstate_raw.js` 620 KB）。**结论已全部转写进本文档**，可以删。
> 例外：`_body_after_tab.html` 与 `_topic_full.html` **已复制到 `tests\fixtures\jidiyouxi\`**，删原文件无妨。
> 探测用的浏览器 profile 目录 `D:\K\deepseek\_gf_*`（17 个）**可整个删掉**，重启探测会自动重建。
> 关机前已确认：**无残留 chrome 进程**。

---

## 九、恢复后的下一步（按顺序）

1. **重跑 `python tools\probe_gal.py`**，从 touchgal / ggbases / nekogal / lzacg 里定下 P2 第三个站点（补齐 `mode` 与选择器）。
2. **用 writing-plans 技能写出实现计划**（已加载技能，尚未产出文档）。计划里必须采纳 §四 的架构修正：
   - 浏览器层 = 专用 profile（非默认路径），**不是**用户真实 profile
   - 代理 = 显式 `http://127.0.0.1:6234`
   - 登录态靠"用户在应用浏览器里登录一次"
3. 实现 P0 骨架 → P1 浏览器层 → P2 搜索层（jidiyouxi + gamer520 + 第三站）→ 交付可用版本。
4. P2 跑通后，**通知用户可以发"不能地址栏搜索的站点清单"**（P6 输入）。
5. P3 UI → P4 健康巡检 → P5 铺开适配器。

### 仍未兑现的承诺 / 开放项
- 我**没有**承诺 30 个站点全部抓得通。`@` 站点（BYRUTOP、Nyaa、Nysoure、梓澪）和论坛型站点有强反爬/Cloudflare，成功率必须逐站实测。
- 用户待发：不能地址栏搜索的站点清单（P6）。
- spec §8 开放项：是否要"下载到本地"按钮（当前只给链接，用户未反对）；探测词 `AI` 是否合适。
- 用户清单里**没有任何 `？？？` 条目** → 所有站点初始 `adapter_status = untested`，靠巡检收敛。
