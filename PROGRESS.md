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
| 代码 / 测试 | ✅ **324 个离线测试全绿** |
| 语种路由 | ✅ 中文→16 站，英文→17 站，日文→11 站（共 21 站，zi0 已移出） |
| UI | ✅ SSE 流式卡片 + 强制刷新按钮 |
| 并发 | ✅ `workers=3`，真站实测 **93.1s → 44.1s（2.1x）** |
| 缓存 | ✅ 重复搜索 **53.9s → 0.5s（115x）**，成功 12h / 失败 30min |
| **出下载的站（中文「终焉之莉莉」）** | **2 / 21** — jidiyouxi、touchgal |
| **出下载的站（英文「enderlilies」）** | **5 / 21** — ankergames、gamebounty、gamer520、playzip、touchgal |
| **出下载的站（日文「制服カノジョ」）** | **8 / 21** — sayafx、nyaa、inarigal、nekogal、ggbases、touchgal、galgamex、anime-sharing |
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
| **touchgal** | **dl=4** ✅ | **dl=4** ✅ | **dl=3** ✅ |
| **galgamex** | NO_RESULTS | NO_RESULTS | **dl=1** ✅ |
| **kungal** | NO_DOWNLOADS（该游戏本体页暂无） | NO_RESULTS | NO_DOWNLOADS（同上） |
| **ggbases** | NO_RESULTS（站点 0 条） | NO_RESULTS（站点 0 条） | **dl=7** ✅ |
| **anime-sharing** | NO_RESULTS | NO_RESULTS | **dl=3** ✅ |
| galgame.dev | NO_RESULTS | NO_RESULTS | NO_RESULTS |

**关键判断：「没结果」不等于「坏了」。** 必须先做对照实验——用本站必定存在的游戏
（`千恋万花` / `Summer Pockets`）验证搜索功能本身是否正常，再判断是「站上真没这款游戏」
还是「代码坏了」。上表里 gamebounty（中文 0 条）、sayafx（索引无该条）、acggw（全中文查询 0 条）
都属于**站点真的没有**，已用对照实验确认。

**kungal 的两个 NO_DOWNLOADS 也是站点事实**：`终焉之莉莉` 与 `制服カノジョ2` 的
「本体资源下载」标签页本身就写「暂无」。同一适配器查 `千恋万花` 能抽出 **dl=23**
（夸克/百度网盘），说明代码是通的 —— 判据是「标签页点开后有没有内容」，
不是「这一款有没有资源」。

**ggbases 三语从 WRONG_GAME 变成正确**：`制服カノジョ` → dl=7（rapidgator/katfile 直链
+ `magnet:?xt=urn:btih:`）；`终焉之莉莉`/`enderlilies` → `NO_RESULTS: 0 個資源`
（该站确实没有这两款，对照实验：`サノバウィッチ` 11 条、`制服カノジョ` 7 条）。

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
8. **嵌套锚点的标题被内层 `title=` 抢走**（ggbases，三语全 WRONG_GAME）
   结果行是 `<a href="view.so?id=N"><a class="keya" title="2D.G.F.">…</a><b>游戏名</b></a>`，
   旧实现把 `attrs + body[:400]` 一起找 `title=`，命中的是**上传者名**，
   游戏名整个丢失。改为先只看锚点自身 attrs，`ALT_ATTR_RE` 刻意不含 `title=`，
   最后按 `<a`/`</a>` 嵌套深度找配对结束标签。
9. **`/2257.so` 法务页被判成详情页**（ggbases）
   `DETAILISH_RE` 的 `/\d{2,}` 命中 `/2257.so` 判 1.0，而真详情 `view.so?id=N` 判 0.5，
   `pick_best` 的 `score >= 1.0` 池子里只剩法务页。收窄为 `/\d{2,}(?:/|$|\?|#)`
   并新增 `\.(?:so|php|aspx?|cgi)\?[^#]*\bid=\d+`。
10. **空结果页认不出（NBSP + HTML 实体）**（ggbases）
    真站文案是 `GGBases\xa0>\xa0 0\xa0個資源`（不间断空格 U+00A0）。
    根因比标记表更深：`_visible_text` 只去标签**没做实体反转义**，拿到的是字面
    `&nbsp;`。修法：加 `html.unescape` + `_SPACEY_RE` 归一化 U+00A0 一类空白。
11. **磁力 hash 要页面内 fetch 两步取**（ggbases）
    详情页无 `magnet:` 文本；hash 在 `magnet.so?id=N` 页由 JS 用
    `POST /magnet.so?downid=<uuid>&json=1&id=N` 取。**必须先真 `goto` 那个页面**
    （downid 是那页渲染时生成的），再用 `page.evaluate` 页面内 fetch。
    `page.request.post` 走独立 TLS 连接，实测 30s 超时 / ECONNRESET。
12. **下载链藏在 SPA 标签页后面**（kungal）
    `/galgame/{id}` 默认停在「游戏介绍」，正文零网盘链；点「本体资源下载」后
    **同页**渲染出资源列表（不跳转）。原有 `_follow_detail_gate` 要求
    `detail_follow_pattern` 才动作，这种「只点不开」的站永远不触发。
    新增 reveal 分支：只配 `detail_open_selector` 即就地重抽。
13. **内嵌 JSON 的 `\u002F` 转义斜杠**（kungal）
    资源页正文在 Nuxt payload 里，链接写作 `"https:\u002F\u002Fpan.baidu.com…"`。
    `URL_RE` 排除反斜杠 → 整页 685 处 `\u002F` 一条都抽不出。
    `html.unescape` 只处理 `&amp;`，不动 JSON 转义，必须单独还原斜杠形态。
14. **base64 封面把卡片标题挤掉**（kungal）
    单张结果卡的 innerHTML 有 8201 字符、其中 8000+ 是内联 base64 PNG；
    `_anchor_title` 只拿到 700 字符窗口 → 游戏名永远在窗口外，标题退化成
    `'<div class="kun-image-blur '`。扫描前压掉 data URI 载荷 + 内层扫描上限提到 20k。
15. **讨论帖盖过游戏条目页**（kungal）
    查「千恋万花」同时命中 `/topic/3887`（十周年讨论帖）与 `/galgame/15`（游戏条目）。
    帖子标题以查询词开头拿满位置分，条目页标题前面有统计数字 → 选中讨论帖，
    用户拿不到下载。`pick_best` 对 `/topic/<n>`、`/post/<n>` 这类**纯讨论串形状**
    压 6 分（压分不排除，只有帖子命中时仍返回）。
16. **官方名带排版装饰导致匹配失败**（kungal）
    站点官方名是「千恋＊万花」（全角星号 U+FF0A），用户输入「千恋万花」时
17. **论坛帖 slug 被判 0.5 分**（anime-sharing 回归）
    收紧 `DETAILISH_RE` 的 `/\d{2,}(?:/|$|\?|#)`（为挡 ggbases 的 `/2257.so`）
    连带把 XenForo 的 `/threads/<slug>/` 打掉——数字埋在 slug 中间、无扩展名。
    20 条帖子全掉到 0.5 分，`pick_best` 的 `>=1.0` 候选池空了，该站从 dl=10
    退化成 `NO_RESULTS`。修法：`DETAILISH_RE` 增加 `/threads/[^/?#]+/?` 分支，
    **只认 `/threads/`**（不放宽 `/数字`，也不碰 `/members/<name>.<id>/`）。

18. **求资源帖盖过发布帖**（anime-sharing）
    `[Request] 制服カノジョ 2` 标题以查询词开头、位置分拿满，压过前面带日期
    和厂商前缀的真发布帖，于是抽出 0 条下载、报 `NO_DOWNLOADS`。
    修法：新增 `REQUEST_RE`（`[Request]`/`[REQ]`/`[求档]`/`[求资源]` 等前缀），
    命中压 6 分；压分不排除——站上只有求资源帖时仍如实返回。

19. **页面装饰资源被当成下载**（anime-sharing）
    `assets.katfile.com/favicon.ico`（域名命中 filehost）与
    `p.anime-sharing.com/proxy.php?image=...`（路径含 `/file`）都混进了下载列表。
    修法：新增 `ASSET_URL_RE`，跳过 favicon / 图片代理 / 图片样式扩展名。
    实测该站 dl=5 → 3（rapidgator / filejoker / krakenfiles）。
    子串匹配直接失败。`_norm` 增加装饰符号清理；CJK 查询额外允许「去空格后」
    再匹配一次（拉丁短查询不启用，否则 `AI` 会命中 `Chained`）。

20. **登录墙被报成「没有结果」**（galgame.dev）
    搜索 URL `302` 到 `/login`，页面上只剩导航链接，被解析成 6 条 0.5 分候选；
    `pick_best` 返回 None，旧代码据此报 `NO_RESULTS: pick_best returned None`。
    用户会以为站上没有这款游戏，实际是**这个站的搜索要登录**。
    修法：新增 `looks_login_wall(url)`，**只认落地 URL 的路径**
    （`/login` `/signin` `/auth` `/account/login`），不扫正文 —— 导航里到处
    都有「登录」字样，扫 HTML 会把每个带登录入口的搜索页都误判成墙。
    优先级：拦截 > 登录墙 > 明确无结果。

---

## 五、站点机制备忘（后续改适配器前必看）

- **jidiyouxi**：URL 模板 `search/detail/{q}`；详情页网盘链在整页 HTML 的 `#appState`
  SSR 数据里，`<a>` 标签 0 条外链；`og:image` 是坏字符串 `"[object Object]"`（站点自己的 bug）；
  不同游戏默认 tab 不同（本体/修改器/讨论求助）。
- **gamer520**：`?s={q}`；详情页无直接网盘链，只有 `/go?post_id=` 跳板。
  搜索页混着大量 WordPress 导航菜单链接，必须剥离站点外壳（平衡扫描，不是正则）。
- **gamebounty**：`/api/v1/search?q=&page=&size=` 也能用（返回 JSON）；
  `/api/dl/` 是 base64url 包装。
- **kungal**：wiki + 论坛。`/galgame/<id>` 是 wiki 页，默认停在「游戏介绍」，
  要点「本体资源下载」标签页才在**同页**渲染资源列表（`detail_open_selector`，
  不配 `detail_follow_pattern`）；有些游戏的该标签页直接是「暂无」。
  `/galgame/resource/<id>` 才是具体资源条目。正文在 Nuxt payload 里，
  链接是 `\u002F` 转义形态。搜索结果混着 `/topic/<n>` 讨论帖，`pick_best` 会压分。
- **ggbases**：`search.so?p=0&title={q}`；结果行是**嵌套锚点**（内层 title= 是
  上传者名）；详情 `view.so?id=N`；磁力要 goto `magnet.so?id=N` 再页面内 fetch 取 hash。
  空结果是 `0 個資源`（NBSP）。`kinds: [磁力, 直链]` 两种都服务。
- **galgame.dev**：`search?term={q}&in=titles` **会 302 到 `/login`** —— 
  站内搜索要登录（sites.yaml 标了 `needs_login: true`）。管线现在认这个跳转，
  报 `NEEDS_LOGIN: 该站搜索需要先登录（搜索页被重定向到登录页）`，
  而不是误导性的 `NO_RESULTS`。
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
tests/                      324 个离线测试 + fixtures
```

---

## 九、下一步建议（按价值排序）

### 已修完的站（原建议 1、2）

- **ggbases** ✅ 三语 WRONG_GAME → 日文 dl=7、中文/英文 `NO_RESULTS: 0 個資源`（站点真 0 条）
- **kungal** ✅ SPA 标签页 + `\u002F` 转义 + base64 封面 + 讨论帖压分，`千恋万花` → dl=23
- **anime-sharing** ✅ 论坛帖 slug + 求资源帖压分 + 页面装饰过滤，`制服カノジョ` → dl=3

### 仍待处理

1. **`NO_RESULTS: pick_best returned None` 的 5 站**（jidiyouxi / byrutgame / ankergames /
   nekogal / galgame.dev）。要先做对照实验区分两种成因：
   - 候选全是 0.5 分（详情形状判据不认该站 URL）→ 改 `DETAILISH_RE` 或给站点配 `detail_pattern`
   - 候选有 1.0 分但标题里没有查询词（该站用别的语言/罗马音命名）→ 站点事实
   实测：jidiyouxi 查日文 0 命中属正常（它是中文站，语种路由已排除它）。
2. **gamebounty 的 `WRONG_GAME`**（查日文）：搜索返回 1 条但页面证据 0。该站 `/zh/` 前缀
   强制中文界面，查日文游戏名匹配不到正文 —— 可能需要去掉 `/zh/` 或按语种切前缀。
3. **两个 `BLOCKED_SEARCH`**（nysoure、lzacg）：Cloudflare 按出口 IP 拦。属基础设施问题，
   用户换节点或加登录态后才可能通，代码侧无解。
4. **健康巡检定时器** —— 用户 m02579 已明确说「定期检查可用性，不需要了」，**不做**。
   `health.py` 的状态机保留，供将来手动巡检或 UI 面板复用。

### 已完成的基础设施

- **Store 缓存接线**：缓存键 = `(归一化截断后查询词, site_id)`，成功 12h / 失败 30min，
  `refresh=true` 绕过。实测重复搜索 53.9s → **0.5s**。
- **并发化**：`config.yaml` 的 `search.workers`（默认 3），每 worker 一份独立
  `chrome-profile-w<N>`，从主 profile 播种登录态（0.02s）。实测 93.1s → **44.1s（2.1x）**。
