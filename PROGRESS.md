# Game Finder — 实现进度与真实状态

> 更新：2026-10-18（缓存 + 并发落地，实测于 commit `1a209ab` 之后）
> 项目根目录：`C:\Users\27025\Desktop\game-finder\`
> 设计文档：`docs\superpowers\specs\2026-10-16-game-finder-design.md`
> 实现计划：`docs\superpowers\plans\2026-10-17-game-finder-implementation.md`

**这份文档只写实测到的事实。凡是没测过的，标注「未实测」。**

---

## 一、怎么启动

```powershell
cd C:\Users\27025\Desktop\game-finder
python app.py
```

浏览器自动打开 `http://127.0.0.1:8734/`。输入游戏名（中文/英文/日文均可），点搜索。

---

## 二、状态总览

| 维度 | 结论 |
|---|---|
| 代码 / 测试 | ✅ **209 个离线测试全绿** |
| 语种路由 | ✅ 中文→16 站，英文→17 站，日文→11 站（共 21 站，zi0 已移出） |
| UI | ✅ SSE 流式卡片 + 强制刷新按钮 |
| 并发 | ✅ `workers=3`，真站实测 **93.1s → 44.1s（2.1x）** |
| 缓存 | ✅ 重复搜索 **53.9s → 0.5s（115x）**，成功 12h / 失败 30min |
| **出下载的站（中文「终焉之莉莉」）** | **2 / 21** — jidiyouxi、touchgal |
| **出下载的站（英文「enderlilies」）** | **3 / 21** — gamer520、gamebounty、touchgal |
| **出下载的站（日文「制服カノジョ」）** | **5 / 21** — sayafx、nyaa、touchgal、galgamex、anime-sharing |
| 健康巡检 | ⚠️ 状态机完成；**无定时器、无快照、无 UI 面板**（用户明确说不需要定时器） |

「诚实报错」是本版的重要目标：宁可显示「没找到」，也不给用户一张错误的卡片。

### 三语全站清扫（2026-10-18，21 站，每站独立子进程 + 150s 硬超时）

| 站 | 中文 | 英文 | 日文 |
|---|---|---|---|
| jidiyouxi | **dl=2** ✅ | NO_RESULTS | NO_RESULTS |
| playzip | NO_RESULTS | NO_RESULTS | NO_RESULTS |
| byrutgame | NO_RESULTS | NO_RESULTS | NO_RESULTS |
| gamer520 | NO_DOWNLOADS | **dl=3** ✅ | NO_DOWNLOADS |
| ankergames | NO_RESULTS | NO_DOWNLOADS | NO_RESULTS |
| **gamebounty** | NO_RESULTS（中文确实 0 条） | **dl=4** ✅ | WRONG_GAME |
| flysheep | NO_RESULTS | NO_RESULTS | NO_RESULTS |
| **sayafx** | NO_RESULTS（索引里真没有） | NO_RESULTS | **dl=2** ✅ |
| **nyaa** | NO_RESULTS | NO_RESULTS | **dl=8** ✅ |
| nysoure | BLOCKED_SEARCH | BLOCKED_SEARCH | BLOCKED_SEARCH |
| iacg | NO_RESULTS | NO_RESULTS | NO_RESULTS |
| inarigal | NO_RESULTS | NO_RESULTS | NO_DOWNLOADS |
| lzacg | BLOCKED_SEARCH | BLOCKED_SEARCH | BLOCKED_SEARCH |
| acggw | NO_RESULTS | NO_RESULTS | NO_RESULTS |
| nekogal | NO_RESULTS | NO_RESULTS | NO_RESULTS |
| ggbases | WRONG_GAME | WRONG_GAME | WRONG_GAME |
| **touchgal** | **dl=4** ✅ | **dl=4** ✅ | **dl=3** ✅ |
| **galgamex** | NO_RESULTS | NO_RESULTS | **dl=1** ✅ |
| kungal | NO_DOWNLOADS | NO_RESULTS | NO_DOWNLOADS |
| **anime-sharing** | NO_RESULTS | NO_RESULTS | **dl=10** ✅ |
| galgame.dev | NO_RESULTS | NO_RESULTS | NO_RESULTS |

**关键判断：「没结果」不等于「坏了」。** 必须先做对照实验——用本站必定存在的游戏
（`千恋万花` / `Summer Pockets`）验证搜索功能本身是否正常，再判断是「站上真没这款游戏」
还是「代码坏了」。上表里 gamebounty（中文 0 条）、sayafx（索引无该条）、acggw（全中文查询 0 条）
都属于**站点真的没有**，已用对照实验确认。

---

## 三、21 站适配状态（逐站实测结论）

### mode = url（19 站）

地址栏模板直接可用。其中两站是 2026-10-18 从 form 改过来的：

- **gamebounty** → `https://gamebounty.world/zh/search?q={q}`
  首页只有 Ctrl+K 命令面板（回车不检索），但 `/zh/search` 是真搜索页。
  详情页下载按钮是 `/api/dl/{slug}/{base64url}` 跳板，由 `decode_gb_dl_links` 解出真链。
  中文查询 0 条是站点事实（`total: 0`）。
- **anime-sharing** → `https://www.anime-sharing.com/search/1/?q={q}`
  比首页那个半隐藏的 keywords 表单稳，无需登录。帖子正文给 rapidgator/katfile 直链。

### mode = index（1 站）

- **sayafx** → `index_url: https://www.sayafx.vip/search.xml`
  全站是 SPA，搜索框回车不触发检索、也没有任何检索 API；但站点**下发了客户端搜索索引**
  （760 条 `<entry><title>/<url>`），浏览器端就是拿它在本地过滤的 → 用 index 模式复刻。
  匹配刻意保守：整词命中或所有词都命中，**不做逐字模糊**（逐字会让「终焉之莉莉」
  命中 118 条无关条目）。

### mode = form（1 站）

- **touchgal** → `form_url: https://www.touchgal.ink/search`
  首页无可见 input，但 `/search` 页有；7 个 URL 参数全部无效。
  **详情页还有第二层**：网盘链不在 HTML 里，要点「下载」按钮后才渲染出
  `/{game}/resource/{id}` 链接，真链在 resource 页正文。
  由 `detail_open_selector` + `detail_follow_pattern` + `_follow_detail_gate` 处理。

### 已移出注册表

- **zi0（梓澪的妙妙屋）**：首页 5 个 input 全不可见，`Control+k` 唤不出，
  唯一搜索入口是外链 `https://www.searchgal.top` → 不可站内搜索。

---

## 四、本轮修复的关键缺陷（都来自真站实测）

1. **slug 型详情页被判成非详情页**（`SLUG_DETAIL_RE`）
   gamebounty 的 `/xxx-free-pc-download` 和 touchgal 的 `/6a4e9cad`（8 位十六进制 id）
   都被 `DETAILISH_RE` 判成 0.5 分，导致 `pick_best` 一个都选不中。
   收窄判据：路径以 `-download` 结尾，或整条路径就是一个 8–40 位十六进制 id。
2. **Markdown 污染的 URL 尾巴**（`_trim_url`）
   touchgal 正文里有 `[工具](https://pan.quark.cn/s/xxx)`，直接跑 URL_RE 会得到
   `...xxx](https://pan.quark.cn/s/xxx` 这种畸形串，污染结果且去重失效。
   **注意不能按 `[` 截断**：sayafx 直链合法包含 `[200214][ゆずソフト]`，按 `[` 截会把 7 条砍到 5 条。
3. **网盘链接藏在整页 HTML 而非 `<a>` 标签里**（jidiyouxi，早前已修）
   提取器必须对 `document.documentElement.outerHTML` 跑正则。
4. **二维码图片被当下载链**（gamer520 落地页）
   `api.qrserver.com/...&data=<urlencoded>` 要排除，载荷用 `unquote(data)` 解。
5. **gamebounty 跳板本身不是下载链接**
   点击 `/api/dl/...` 返回 JSON，不是文件。必须解码后丢弃包装 URL。
6. **sqlite 跨线程使用**（并发化时暴露，最隐蔽）
   `ProgrammingError: SQLite objects created in a thread can only be used in that
   same thread.` 该异常被单站兜底逻辑吞成 `.error` 字段，表现为「并发整批 0 成功、
   0.5s 就结束」，从日志完全看不出是 sqlite 问题。
   修法：`sqlite3.connect(..., check_same_thread=False)` + `threading.Lock()` 包住每次操作。
7. **并发时 profile 必须队列发放，不能按下标取模**
   Chrome 会锁 `user-data-dir`，两个线程共用一个目录必有一个
   `TargetClosedError`。11 站 3 槽时 `idx % 3` 会让多线程撞同一目录。
   改成 `queue.Queue` 发放 + 用完归还。`test_each_concurrent_worker_gets_a_distinct_profile`
   已锁住（临时改回取模会失败）。

---

## 五、站点机制备忘（后续改适配器前必看）

- **jidiyouxi**：URL 模板 `search/detail/{q}`；详情页网盘链在整页 HTML 的 `#appState`
  SSR 数据里，`<a>` 标签 0 条外链；`og:image` 是坏字符串 `"[object Object]"`（站点自己的 bug）；
  不同游戏默认 tab 不同（本体/修改器/讨论求助）。
- **gamer520**：`?s={q}`；详情页无直接网盘链，只有 `/go?post_id=` 跳板。
  搜索页混着大量 WordPress 导航菜单链接，必须剥离站点外壳（平衡扫描，不是正则）。
- **gamebounty**：`/api/v1/search?q=&page=&size=` 也能用（返回 JSON）；
  `/api/dl/` 是 base64url 包装。
- **kungal**：wiki + 论坛，`/galgame/<id>` 是 wiki 页「本体资源下载」标签页可能是「暂无」；
  `/galgame/resource/<id>` 才是资源条目。注意不同游戏的 resource 会混在搜索结果里。
- **ggbases**：三语查询全部 `WRONG_GAME`，搜索结果标题与查询词无证据 → 适配器待查。
- **nysoure / lzacg**：Cloudflare 拦截（`cf-error-details` / `attention required`），
  属代理出口 IP 被拒，不是代码问题。

---

## 六、已知限制

1. **健康巡检没有定时器**（用户 m02579 明确说不需要）。`finder/health.py` 状态机
   （ok / ok_no_hits / degraded / cloudflare_block / needs_login / unreachable）已完成并测试，
   但没有后台任务调它，也没有 UI 面板。
2. **并发不是无上限的**。`search.workers` 默认 3，每个 worker 一份 Chrome profile
   （`chrome-profile-w<N>`，播种登录态约 0.02s）。调高会吃内存，且站点本身有限流。
3. **缓存命中失败也会缓存 30 分钟**。站点刚恢复时最多要等 30 分钟（或点「强制刷新」）。
   这是刻意取舍：不缓存的话 6 个失败站会让重复搜索慢回首次水平。
4. **整站串行清扫会卡死**，必须每站一个子进程 + 硬超时（`sweep_driver.py` 这么做）。
   没有单站超时的串行扫描不可用（实测 22 站跑了 50 分钟、CPU 仅 0.84s）。
5. **串行跑完立刻并发会假失败**：残留 Chrome 进程会让并发整批 0 成功（0.4s 全灭）。
   跑基准前必须清掉本项目的 chrome 进程。这是环境问题，不是应用缺陷。
6. **profile 是独占资源**，同一目录不能并发（Chrome 锁 user-data-dir），
   所以并发靠「每 worker 一份目录 + 队列发放」，不是共享。

---

## 七、环境

- Chrome：`C:\Program Files\Google\Chrome\Application\chrome.exe`，版本 **155.0.8059.80**
- **不能复用默认 profile**：Chrome ≥136 拒绝为默认 user-data-dir 开 DevTools，
  报 `DevTools remote debugging requires a non-default data directory`。
  用专用 profile `game-finder\chrome-profile`（首次需手动登录目标站，cookie 会持久化）。
- **代理必须显式传** `http://127.0.0.1:6234`（系统代理端口，不是 7890）。
  实测：不传 proxy 跟随系统 4/5 站，显式传 5/5 站。
- **UA 必须显式设成真实 Chrome UA**：ankergames 与 iacg 在纯无头指纹下返回 403，
  加真实 UA 后 200。
- 清理孤儿 Chrome（只杀项目 profile，不碰用户浏览器）：
  ```powershell
  Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
    Where-Object { $_.CommandLine -like "*game-finder\chrome-profile*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
  ```

---

## 八、代码地图

```
app.py                      启动 uvicorn + 开浏览器
config.yaml                 profile 路径、代理、超时
sites.yaml                  21 站注册表
finder/lang.py              detect_lang（zh/en/ja）
finder/models.py            Site / SearchSpec / SearchHit / Download / GameDetail
finder/sites.py             load_sites / filter_sites_by_lang
finder/browser.py           BrowserSession（专用 profile + 真 UA + 显式代理）
finder/search.py            build_search_url / parse_result_links / pick_best / strip_chrome
finder/detail.py            extract_card / extract_downloads / decode_gb_dl_links
finder/pipeline.py          search_one（url/form/index 三模式）/ _follow_detail_gate
                            run（缓存 + 并发）/ normalize_query / resolve_worker_primary
finder/health.py            classify / check_site（状态机就绪，无定时器）
finder/store.py             SQLite 缓存（成功 12h / 失败 30min）+ 健康历史，线程安全
finder/web/server.py        FastAPI + SSE，支持 refresh 强制刷新
finder/web/static/index.html  单页 UI
tests/                      209 个离线测试 + fixtures
```

---

## 九、下一步建议（按价值排序）

1. **查 ggbases** 三语全部 WRONG_GAME 的原因。
2. **kungal** 的 resource 页需要点标签页才渲染，目前 `NO_DOWNLOADS`。
3. **接上健康巡检定时器** —— 用户 m02579 已明确说「定期检查可用性，不需要了」，
   所以**不做**。`health.py` 的状态机保留，供将来手动巡检或 UI 面板复用。

### 本轮已完成（原建议 2、3）

- **Store 缓存接线**：`pipeline.run(..., store=...)`，缓存键 = `(归一化截断后查询词, site_id)`。
  成功结果 12h，失败结果 30min（`fail_ttl_minutes`），`refresh=true` 绕过。
  实测重复搜索 53.9s → **0.5s**，`cached=11/11`。
- **并发化**：`config.yaml` 的 `search.workers`（默认 3），每 worker 一份独立
  `chrome-profile-w<N>`，从主 profile 播种登录态（0.02s，只拷 cookies 等小文件）。
  实测 93.1s → **44.1s（2.1x）**，出下载的站与串行完全一致。
