# Game Finder — 实现进度与真实状态

> 更新：2026-10-21（免代理自动回退 + Windows 便携版打包，实测于 commit `77fce60` 之后）
> 项目根目录：`C:\Users\27025\Desktop\game-finder\`
> 设计文档：`docs\superpowers\specs\2026-10-16-game-finder-design.md`
> 实现计划：`docs\superpowers\plans\2026-10-17-game-finder-implementation.md`
> 使用说明：`README.md`（面向拿到 zip 的用户）

**这份文档只写实测到的事实。凡是没测过的，标注「未实测」。**

---

## 一、怎么启动

**便携版（用户拿到 zip）**：解压 → 双击 `game-finder.exe`。首次运行在 exe 旁边
生成 `config.yaml` / `sites.yaml` / `data/` / `logs/`。详见 `README.md`。

**从源码**：

```powershell
cd C:\Users\27025\Desktop\game-finder
python app.py
```

浏览器自动打开 `http://127.0.0.1:8734/`。输入游戏名（中文/英文/日文均可），点搜索。

诊断：`python app.py --check`（打印运行形态 / 路径 / Chrome 版本，不启动服务）。

---

## 二、状态总览

| 维度 | 结论 |
|---|---|
| 代码 / 测试 | ✅ **578 个离线测试全绿**（2026-10-22 复跑；新增 33 例免代理回退 + 打包路径，43 例引擎兜底，6 例启动器 CLI，61 例手动登录） |
| 免代理 | ✅ **自动探测 + 回退直连**：`proxy.auto_detect` 探 6234，不通就直连（实测 18/19 站直连可用） |
| 便携版 | ✅ **PyInstaller onedir + zip**，142.8 MB / 60.9 MB 压缩包，解压双击即用，已在新路径实测 |
| 引擎兜底 | ✅ 有下载链接的站点 < 3 时，结果区上方给必应/百度/谷歌/Yandex **跳转链接**（只拼 URL，不发请求） |
| 手动登录 | ✅ 需要登录的站（galgame.dev）卡片上给「打开浏览器登录」，开**有头**窗口落到登录页，登完自动重搜 |
| 语种路由 | ✅ 中文→16 站，英文→17 站，日文→11 站（共 21 站，zi0 已移出） |
| UI | ✅ SSE 流式卡片 + 强制刷新按钮 + 换名提示 |
| 并发 | ✅ `workers=3`，真站实测 **93.1s → 44.1s（2.1x）** |
| 缓存 | ✅ 重复搜索 **53.9s → 0.5s（115x）**，成功 12h / 失败 30min |
| **出下载的站（中文「终焉之莉莉」）** | **2 / 16** — jidiyouxi、touchgal |
| **出下载的站（英文「enderlilies」）** | **5 / 17** — ankergames、gamebounty、gamer520、playzip、touchgal |
| **出下载的站（日文「制服カノジョ」）** | **8 / 11** — sayafx、nyaa、inarigal、nekogal、ggbases、touchgal、galgamex、anime-sharing |
| 健康巡检 | ⚠️ 状态机完成；**无定时器、无快照、无 UI 面板**（用户明确说不需要定时器） |

> ⚠️ **分母要以语种为准**（2026-10-18 修正）。早先报的「x / 21」是错的：
> 清扫脚本直接遍历全部 21 站，**没走语种路由**，于是把 en-only 的 playzip
> 在中文/日文查询下的结果、以及 acggw/nekogal/galgamex 在英文查询下的结果
> 都算了进去。真正会参与检索的站数是 **中 16 / 英 17 / 日 11**。
> `sweep_par.py` 已修：只扫该语种参与的站（`filter_sites_by_lang`）。
> 用真 UI 端到端复证过：中文查询显式显示「参与 16 站」「参与 11 站（日文）」。

「诚实报错」是本版的重要目标：宁可显示「没找到」，也不给用户一张错误的卡片。

### 三语全站清扫（2026-10-18，每站独立子进程 + 150s 硬超时）

> **这张表是「审计视图」**：为了查站点行为，它对**每个语种都查了全部 21 站**，
> 故意比真正的语种路由更宽。所以「某站 × 它不支持的语种」那一格**不代表用户
> 会遇到的结果**（例如 playzip 是 en-only，它的中文格永远不会被真实查询触发）。
> 用户真实看到的数字只看**参与站**：**中 2/16、英 5/17、日 8/11**（见上文）。
> `sweep_par.py` 已改成只扫该语种参与的站，与本表口径不同是有意的。

| 站 | 中文 | 英文 | 日文 |
|---|---|---|---|
| jidiyouxi | **dl=2** ✅ | 无结果 | 搜索导航失败 |
| playzip | 坐错游戏 | **dl=1** ✅ | 详情 404 |
| byrutgame | 无结果 | 无结果 | 无结果 |
| gamer520 | 仅跳板 | **dl=3** ✅ | 仅跳板 |
| ankergames | 无结果 | **dl=1** ✅ | 无结果 |
| gamebounty | 无结果（中文确实 0 条） | **dl=4** ✅ | 坐错游戏 |
| flysheep | 无结果 | 无结果 | 无结果 |
| sayafx | 无结果（索引里真没有） | 无结果 | **dl=2** ✅ |
| nyaa | 无结果 | 无结果 | **dl=8** ✅ |
| nysoure | 被拦 | 被拦 | 被拦 |
| iacg | 无结果 | 无结果 | 无结果 |
| inarigal | 无结果 | 无结果 | **dl=1** ✅ |
| lzacg | 被拦 | 被拦 | 被拦 |
| acggw | 无结果 | 无结果 | 无结果 |
| nekogal | 无结果 | 无结果 | **dl=1** ✅ |
| touchgal | **dl=3** ✅ | **dl=3** ✅ | **dl=3** ✅ |
| galgamex | 无结果 | 无结果 | **dl=1** ✅ |
| kungal | 无下载（该游戏本体页暂无） | 无结果 | 无下载（同上） |
| ggbases | 无结果（站点 0 条） | 无结果（站点 0 条） | **dl=7** ✅ |
| anime-sharing | 无结果 | 无结果 | **dl=5** ✅ |
| galgame.dev | 需登录 | 需登录 | 需登录 |

（审计口径合计：中 2/21、英 5/21、日 8/21；**用户真正的分母见上文** 中 16 / 英 17 / 日 11。
非参与语种的格子里的报错——如 playzip 日文的「详情 404」、jidiyouxi 日文的
「搜索导航失败」——**永远不会被真实查询触发**，不必修。）

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

21. **「只有跳板、没有直链」被报成「站点没有资源」**（gamer520，中文通道）
    中文查「终焉之莉莉」只返回 `/18985.html`（英文查才返回有直链的 `/18974.html`，
    两个帖子是同一游戏的不同版本），该页 **0 条网盘链**，只有一个
    `/go?post_id=18985` 跳板。
    **决定不自动跟进**，依据是硬证据不是猜测：跟随两次结果逐字节一致（确定性），
    但落地页 `520.gamers520.com/8191.html` 是第三方聚合站的**用户上传帖**
    （面包屑 `白嫖者联盟-游戏小乐园 > 322369521 > 5009 牛夫人`，2024-06-04），
    正文 716 字里游戏名出现 **0 次**、`_query_evidence`=0，而且它的百度盘链接
    `.../1Vrpjt1Gmb1Tgg8T4XBHzxQ?pwd=dysb` 还出现在**另一个帖子**（123857）的
    落地页上 → 落地页与本次查询的游戏**无归属关系**。
    修法：`_classify_empty_detail(html, gate_links)` 新增第 4 类
    `NEEDS_GATE: 详情页只有 N 条站内跳板链接、没有直链；跳板落地页无法确认
    属于本游戏，未自动跟进`，并保留 `card.extra["gate_links"]` 作证据。
    优先级：登录/评论门槛 > 跳板 > 站点自述不可用 > 裸 NO_DOWNLOADS。

22. **连写英文名匹配不到（站点整词检索）**（byrutgame）
    `Ender Lilies`（带空格）→ 命中正确页；`enderlilies`（连写）→ 0 条。
    实测边界：`ender`（5 字）能命中、`enderl`（6 字）不行 →
    **严格整词匹配**（标题里 `ENDER`/`LILIES` 是独立词），连写词在索引里不存在。
    已排除的替代路径：`full_search=1` 无效；`story=enderlilies*` 通配符无效；
    去掉 `search_start` 无效；DLE 的 `/engine/ajax/search.php?q=` 联想接口
    不存在（返回首页）。
    → **站点引擎限制，报 `NO_RESULTS` 是诚实结果**，靠 UI 的换名提示引导用户
    改用带空格的英文名。不要再试通配符。

23. **换名提示永不出现**（UI，用户明确要求过）
    用户要求（m00629）「提前告知用户如果中文名搜索不到可以再尝试英文名和日文名」。
    旧触发条件是 `if (!gotAny)`，而 `gotAny` 只要收到过任一 `result` 帧就为 true ——
    每个站（哪怕 `NO_RESULTS`）都会回一帧 → **实测两次真站查询一次都没显示过**。
    修法：改为 `data.ok === 0`（无任何站点出下载）时显示，并按**已识别语种**给
    具体例子（中文输入建议 `Ender Lilies` / `制服カノジョ`；英文输入建议日文原名、
    中文译名；日文输入建议英文名、中文译名），未知语种走兜底文案。
    另外新增**常驻**说明 `#note`（输入框下一直可见）—— 这才是「提前」告知。
    `#hint` 初始置空，避免显示上一次查询的旧文案。
    守则：提示的 `innerHTML` 右值必须**严格来自常量表**（有测试卡这条），
    站点返回的字符串一律不许进 `innerHTML`（其余 UI 走 `el()` → `textContent`）。

24. **自己造出来的「站点抖动」**（jidiyouxi，最隐蔽的一条）
    现象：同一个中文查询时好时坏 —— 3 次里 1 次 `dl=2`、2 次 `NO_RESULTS`，
    45s 间隔重测仍是「失败/失败/成功」，看着像站点随机空响应。
    **先证伪了「限流」假设**（拉开间隔没改善），再直接轮询同一个页面：
    **+4.0s 就 `hits=1`，两次都是** —— 说明结果本来就在，是我们自己弄丢的。
    根因在暂态重试循环：`_TRANSIENT_TEXT_MIN = 300` 是按「正文至少 300 字」
    猜的，而 jidiyouxi 是 JS 渲染页，**出结果时 `_visible_text` 也只有 250 字**
    → `_looks_transient` 恒为 True → 每轮都 `_goto` 重载 → **把已经解析出来的
    候选冲掉**，还要重新碰站点的空响应。
    修法（`4a10d7f` + `c44779d`）：循环改成真正的轮询 ——
    ① 任何时候解析出候选就 `break`，绝不重载；
    ② 等待 4s 之后**必须再查一次候选**才决定要不要重载（只查一次不够，
    第一版就漏在这里：22 站并行清扫下 jidiyouxi 依旧 hits=0）；
    ③ `search_transient_retries` 只统计真正的重载次数。
    效果：3/3 `dl=2`，耗时从 20–44s 降到 7–15s。
    教训：**「站点不稳定」的结论必须先排除自己**。判据是「直接轮询原始页面」
    这个不经过我们代码的观测。

25. **搜索页长得像详情页 → 抖动被报成 `WRONG_GAME`**（jidiyouxi）
    该站搜索模板是 `/search/detail/{q}`，路径形状与详情页一致。搜索页渲染成
    空壳时 `_looks_detail_page` 只看路径 → 把搜索页当详情页去抽卡 → 报
    `WRONG_GAME: no query evidence in page`（误导：像是「页面内容对不上查询」，
    实际是站点抖了）。
    修法：`_is_site_search_url(site, url)` —— 先按站点自己的 `url_template`
    前缀排除搜索 URL，再退回通用 `/search|find|query` 路径段；
    `_looks_detail_page` 命中即返回 False。
    回归保护：inarigal 的「搜索 302 到 `/detail/64`」必须仍然认成详情页。

### 2026-10-20 第二轮（W4 五项，全部有测试锁定）

26. **半截词拿去搜 → 搜出别的游戏**（acggw，`max_query_len: 10`）
    用户查 `summer clover`（13 字）被截成 `summer clo`。acggw 的详情页命中
    `summer` 但不命中 `clo`，而整句 `summer clo` 又是 `Summer Clover` 的**子串**
    —— 连「整句匹配」都挡不住。修法：新增 `clamp_query_detail()` 返回
    `(词, 是否截断, 是否切在词中间)`，切在词中间时**在发任何请求之前**就放弃该站，
    报 `QUERY_TOO_LONG`（`extra["query_truncation"]="mid_word"`）。
    `clamp_query()` 保持旧两值契约（缓存键等旧调用方依赖）。
    切在空格上或完整 token 之后算干净截断，照旧去搜；CJK/假名没有词边界，
    硬截断永远放行（混合查询只要含 CJK 就跟随 CJK 规则）。
27. **证据闸门写成 `>0` → 只命中一半也放行**（galgamex/acggw）
    旧闸门只要命中**任一**词就通过。改为 `_query_evidence_ok()`：
    拉丁查询要求 >=3 字的 token **全部**命中（`_evidence_counts` 同时算出
    命中数与所需数，两者永远用同一套计法）。`_query_evidence()` 保留旧语义
    供诊断与既有测试用。3–4 字词不做「去分隔符紧致匹配」（`clo` 不能命中
    `clover`），>=5 字才允许（`enderlilies` 要能对上 `Ender Lilies`）。
28. **form 模式把「站点说没有」报成「表单没生效」**（touchgal）
    查 `夏色四叶草` 时页面逐字显示 `未找到相關內容`，但 URL 不变、也不新增锚点，
    于是 `FormOutcome.effective == False` → 报误导性的 `FORM_FAILED`。
    修法：在判失败之前先复查站点自己的空结果文案，命中则报 `NO_RESULTS: <原文>`。
    守卫：**没有空结果文案时绝不能因为页面有链接就报成功**（首页残留链接
    不是结果）；空文案命中时也仍然只能报 `NO_RESULTS`。
    两条长标记必须排在笼统的「未找到相关」**之前**（标记表按顺序取首个命中，
    否则报错里只剩短标记，丢掉站方原文）。
29. **WRONG_GAME 卡片仍挂着错游戏的标题**（ankergames）
    查 `summer clover` 时 `pick_best` 选中 Castlevania（28 条候选里评分最高），
    证据 0 → 报 `WRONG_GAME`，但卡片标题还是 `Castlevania: Symphony of the Night`，
    配着 `match=strong` 看起来像「找到了」。修法：产生 WRONG_GAME 时清空
    `card.title`，原值留进 `extra["wrong_game_title"]` / `extra["wrong_game_url"]`
    （**即使原标题是空串也要留键**，方便区分「抽不到标题」与「抽到别的标题」）。
    `pick_best` 选择逻辑一个字都没动。
30. **下载链由 JS 现场生成，抽 HTML 永远抽不到**（galgamex）
    详情页 48 个锚点里没有一条是下载链。真链要「点资源下载标签页 → 点供应商按钮」
    才出现，开新窗口 `https://www.galgamex.net/redirect?url=<真链>`。
    新增 `download_flow: popup_redirect` + `_fetch_popup_redirect_links()`：
    `context.route("**/redirect*")` 读 URL 后 `route.abort()`（不加载网盘页，
    省流量且不触发风控），`context.on("page")` 兜 `window.open` 直接开新页的情形
    并立刻 close，收尾必须 `context.unroute`。
    纪律：单按钮坏掉只记 `extra["galgamex_errors"]` 不拖死其它按钮；同一 URL 去重；
    无 selector 时返回空且不抛；点击上限 `MAX_PROVIDER_CLICKS = 12`。
    过滤 `javascript:void(0)` 与站点图标（复用 `ASSET_URL_RE`）。
    配套修：`_follow_detail_gate` 只在**还没拿到链接**时兜底 —— 它原本无条件调用，
    reveal_only 分支会把 popup 流程刚点出来的链接整体丢掉。

32. **选择器不能靠猜：`a.download-provider` 在真站根本不存在**（galgamex，真机复测）
    写测试时用的 `a.download-provider` 是**凭空想的**：真站静态 HTML 里
    `download-provider` 出现 **0 次**，供应商控件全是 `<button>`，纯客户端渲染。
    真机 Playwright 逐元素量出来：资源卡片里「分卷 1 / 分卷 2 / 百度网盘」三个按钮
    的 class **完全相同**（shadcn 的一长串工具类），只有 `data-variant` / `data-size`
    能把它们和「复制」（`data-variant="ghost"`）、顶部「登录」（`data-size="default"`）
    分开。最终选择器：
    `button[data-slot='button'][data-variant='default'][data-size='sm']`（实测恰好 3 个）。
    **教训：离线测试全绿 ≠ 真站能用；选择器必须在真机上量，量不到就得改测试。**

33. **点完供应商按钮只等固定 400ms → 漏掉最后一个供应商**（galgamex，真机复现）
    真机跑 `_fetch_popup_redirect_links` 时，3 个按钮都点到了、`galgamex_errors` 为空，
    但**只回 2 条链**（两个分卷直链），`pan.baidu.com` 那条丢了。
    逐按钮加日志才发现：「分卷」是直接跳转（几十毫秒命中 route），
    「百度网盘」要先开弹窗再跳，**400ms 内 route 还没触发**。
    修法：固定 sleep 改成**轮询**（`_PROVIDER_POLL_MS = 200`，
    上限 `_PROVIDER_WAIT_MS = 4000`），拿到候选立刻收工，命中后再给一个 poll 余量
    让重复跳转落齐。修后真机 3/3 全取到（含 `https://pan.baidu.com/s/1aCmoplMimsXAb16i9tfP_A?pwd=us6i`）。
    **教训：「点了但没链」不等于「按钮没链」，先怀疑等待时机。**

34. **分卷包 `.z01` 被判成 `unknown`**
    galgamex 直链形如 `Gamex-005103/%23A8824.z01`（7z 分卷）与 `%23A8824.zip` 成对出现。
    `_classify` 的扩展名白名单只认 `.zip`，第一卷落进 `unknown`，卡片上看起来像「没认出来」。
    修法：白名单补 `z\d{2,3}` / `r\d{2,3}` / `part\d+`（7z、rar 分卷、partN 通用形状）。

31. **`page.content()` 读失败被当成「空结果页」**
    `_NoNavPage` 这类不含 `content()` 的页面直接 AttributeError 崩溃；真站上页面
    被关掉/导航中抛异常时，一次读失败会被下游「暂态」判定接手，最后谎报成
    `NO_RESULTS` 并进失败缓存 30 分钟。修法：`search_one` / `_extract_detail`
    一律走已有的 `_page_content()` 助手（读不出返回 None），None 时报
    `PAGE_READ_FAILED`，**绝不**当空结果。

### 2026-10-21 第三轮（免代理 + 便携版）

35. **代理没开 → 全部站点失败**（最常见的第一次运行失败原因）
    `config.yaml` 里 `proxy.enabled: true` + 固定 `http://127.0.0.1:6234`。
    用户没开本地代理时，每个 `BrowserSession` 都带 `proxy` 参数，全部站点
    报 `ERR_PROXY_CONNECTION_FAILED`，看起来像「程序坏了」。
    实测（`tools/probe_no_proxy_run.py`，完整 `run()`）：
    **19 站里 18 站直连可用**，只有 nyaa(sukebei.nyaa.si) 直连超时。
    修法：新增 `finder/proxy.py`（`parse_server` / `probe_alive` / `resolve` /
    `apply`），启动时探一次 TCP 端口（0.5s，进程内缓存），活着用代理、
    死了直连并打日志；`proxy.auto_detect: false` 可退回旧行为。
    **代理只在真正需要 nyaa 时才是必需的。**

36. **打包后 `ROOT` 指向 PyInstaller 临时目录 → 用户数据全丢**
    `finder/web/server.py` 原来用 `Path(__file__).parent.parent.parent`。
    onedir 打包后这个路径落在 `_internal/`（或 `_MEIPASS` 临时目录），
    `config.yaml` 改了没用、`data/finder.db` 写不进去、Chrome profile 每次重建。
    修法：新增 `finder/paths.py`，把「只读资源」（`bundle_root()`）与
    「可写数据」（`app_root()` = exe 旁边）分开；首次运行
    `ensure_runtime_files()` 从 `_internal/` 复制 `config.yaml`/`sites.yaml`
    到 exe 旁边，**已存在的绝不覆盖**（升级不吞用户改动）。

37. **Playwright 自带 Chromium 过不了 Cloudflare**（所以不打包浏览器）
    `tools/probe_bundled_chromium.py` 实测 6 个 CF 站：
    galgamex / gamer520 / ankergames / iacg / anime-sharing 都 200，
    但 **touchgal 403 `Just a moment...`（6059 字节、0 锚点）**；
    系统 Chrome 访问同一页正常。打包自带浏览器 = +150 MB 体积 + 更差的结果，
    所以只依赖系统 Chrome，找不到时给中文安装指引（`app.py::_preflight`）。

38. **`uvicorn.run("finder.web.server:app")` 字符串形式在打包后失效**
    打包后没有可导入的模块路径，必须传 app 对象：
    `from finder.web.server import app as fastapi_app` + `uvicorn.run(fastapi_app, ...)`。

### 2026-10-21 第四轮（搜索引擎兜底）

用户要求（原文，m01166）：「增加功能，如果出来的结果少于三个，在必应、百度、谷歌、
Yandex也进行搜索和整合，不过不用给出结果，给跳转链接就行」。
三个口径经确认（m01187）：**有下载链接的站点数 < 3** 触发、**查询词原样**传引擎、
**结果区上方单独一块**。

39. **「少于三个」的计数口径不能沿用 `done.ok`**
    `ok` 数的是「error 为空」的站，其中包含 `no_links`（站点找到游戏但抽不到链接）
    和只有 `NO_RESULTS` 之外错误的站。按 `ok` 触发会出现「已经有 3 张卡却仍推引擎链接」，
    而那些卡对用户来说一个链接都点不了。
    修法：`finder/engines.py::linked_site_count` 只数**downloads 里至少有一条非空 URL
    的站点**，`needs_fallback` = 该数 < `MIN_LINKED_SITES`（3）。
    `kind` 判不准（`unknown`）也算 —— URL 有了用户就能点。计数单位是**站点**，
    同一站给 3 条网盘仍只算 1（`GameDetail` 本来就是一站一条）。

40. **引擎兜底绝不能真去抓引擎结果页**
    用户明说「不用给出结果，给跳转链接就行」。`engine_links()` 是**纯函数**：
    只做 `quote(query, safe="")` + 字符串拼接，不发任何网络请求。
    好处是零延迟、零反爬风险，也不会把引擎页的无关结果混成「找到的游戏」。
    空格用 `%20` 而不是 `+`（`+` 在部分引擎里是字面加号，会搜出别的东西）。

41. **兜底块必须清空，否则会串上一次查询的链接**
    单页 UI 里 `#engines` 是常驻容器，`search()` 开头必须
    `engines.innerHTML = ''` + `display:none`，收到 `engines` 帧才 `display:block`。
    静态测试 `tests/test_ui_engines.py` 锁住这条（以及「容器必须在 `<main>` 之前」、
    「链接必须过 `safeUrl()`」）。

42. **打包验收脚本要指定端口，但 `app.py` 没有 `--port`**
    写 `tools/probe_packaged_engines.py` 时想用 `game-finder.exe --port 8795`
    避开用户正在跑的服务，结果 exe 直接
    `error: unrecognized arguments: --port 8795` 退出，验收脚本报
    「packaged server did not start」——看起来像打包坏了，其实是参数不存在。
    修法：`app.py` 加 `--port`（覆盖 `server.port`，被占仍自动往后找），
    并补 `tests/test_app_cli.py` 6 例锁住「`--port` 生效 / 缺省用 config /
    `--check` 不起服务 / `--no-browser` 不开浏览器」。
    **教训**：验收脚本自己也是代码，报错先怀疑脚本与产物的接口对不上。

### 2026-10-22 第五轮（手动登录 galgame.dev）

用户问（m01518）：「真红讨论组这个站点如果我提前在浏览器登录过也不行吗」。
实测答案：**不行**。程序用**专用** profile（`chrome-profile`），用户在**自己** Chrome
里登录的 Cookie 在默认 user-data-dir 里；而 Chrome 136+ 禁止对默认目录开 DevTools
（`is_chrome_default_profile` 守卫会直接抛错）。所以必须让用户**在程序自己的 profile 里**
登一次。方案经确认（m01660）：卡片上给按钮 → 开有头窗口 → 登完自动重搜。

43. **`needs_login` 曾经是个纯装饰字段**
    它只出现在 `models.Site`、`sites.py` 解析、`/api/sites` 输出里，
    **不驱动任何行为** —— 配置写了 `needs_login: true`，程序照旧去搜，
    撞上 302 登录页后只报一句 `NEEDS_LOGIN`，用户无从下手。
    修法：`needs_login` 现在真的长出登录入口（`login_url_for` → `/api/sites`
    → 前端 `renderLogin`），并且只有它才给入口（不需要登录的站绝不显示按钮）。

44. **登录窗口必须有头，且必须落到登录页**
    `LoginSession._open()` 用 `headful_override=True` 起浏览器（`headless` 下用户
    根本没法输密码），起来直接 `goto(login_url)`，不让用户自己找入口。
    `tests/test_login.py::test_session_opens_headful_on_the_login_page` 锁这两条。

45. **登录成功不能只看 URL**
    `galgame.dev` 首页**未登录也能打开**，只看 URL 会立刻误报成功。
    判据必须是「不在登录路径上」**且**「正文出现登录态标记」
    （`LOGGED_IN_MARKERS`：退出/登出/我的帐号/个人中心/Sign out/Log out/My account），
    站点可用 `login_success_pattern` 覆盖；配置里的正则写错要**退回通用判据**
    而不是把功能卡死（`test_broken_success_pattern_falls_back_to_markers`）。

46. **用户中途关窗口是正常路径，不是失败**
    关掉窗口时 Playwright 抛 `Target page, context or browser has been closed`。
    必须识别成 `cancelled=True`（`message="登录窗口已关闭"`），既不抛异常、
    也不刷 `log.exception`。超时同理返回 `ok=False` + 人话（「可以再点一次」）。

47. **登录写主 profile，搜索跑 worker profile —— 这条链路必须锁住**
    并发路径下每个 worker 用 `chrome-profile-w<N>`，由
    `seed_worker_profile(primary, worker)` 从**主** profile 播种。
    登录若写到别的目录，用户登完还是搜不到，**而且没有任何报错**。
    `tests/test_login.py` 末尾三条用例钉死：`resolve_worker_primary` ==
    `resolve_profile_dir(主 profile)`、`LoginSession` 不传 `profile_override`、
    `SEED_ENTRIES` 含 `Default/Network/Cookies` 与 `Local State`。

48. **登录态写进 profile 后，缓存里的 `NEEDS_LOGIN` 已经过时**
    失败结果缓存 30 分钟。登完必须 `search(true)` 强制刷新，否则用户看到
    的还是「需要登录」，会以为登录没生效（`test_login_success_forces_a_refresh`）。

49. **页面显示「退出」≠ Cookie 已落盘**
    `wait_for_login` 的判据是**页面**看起来已登录；Cookie 要等 Chrome 异步刷盘。
    用户登完立刻关窗口时，页面已经是「退出」但磁盘上可能还没有 —— 重搜仍是登录墙，
    用户会以为功能坏了。修法：`LoginSession.cookie_snapshot()` 在关窗前主动
    `context.cookies()` 问一次浏览器（这一步本身会促成刷盘），把本站 Cookie 条数
    回给前端做诊断。**它只是诊断**：快照失败绝不能把「登录成功」变成失败
    （`server.py` 里单独 try 包住；这条是被 `test_api_login_returns_ok_when_session_succeeds` 抓出来的）。

50. **UI 判据只认 `d.outcome`，不许在 JS 里解析 error 字串**
    第一版写成 `String(d.error||'').split(':')[0]` 判前缀，直接被
    `tests/test_result_order.py::test_html_does_not_parse_error_prefixes` 拦下 ——
    那条规则是第三轮为了「四档排序只认后端」立的。
    改用 `d.outcome !== 'not_found' && d.outcome !== 'no_links'`。
    真机复核：galgame.dev 搜「千恋万花」→ `NEEDS_LOGIN` →
    `outcome_of` 因 `extra["search_login_wall"]` 存在而归 `not_found`，
    登录框正常出现；`direct`/`pan` 卡片不长按钮；nyaa/touchgal 也不长。

---

## 五、站点机制备忘（后续改适配器前必看）

- **galgamex**：`search?q={q}`。详情页 `/game/{id}` 原始 HTML **一条下载链都没有**
  （48 个锚点全是导航/封面）。真链是 JS 现场生成的：点「资源下载」标签页
  （`detail_open_selector: button:has-text('资源下载')`）→ 渲染出资源卡片按钮
  （分卷 N / 百度网盘 / 夸克…）→ 点按钮开新窗口
  `https://www.galgamex.net/redirect?url=<quote(真链)>`，`unquote(url 参数)` 才是真链，
  同时打 `POST /api/game/resource/<id>/download`。走 `download_flow: popup_redirect`
  （路由拦截 + popup 兜底）。**不要指望抽 HTML**。
  ⚠️ 供应商按钮的 class 与「分卷」按钮**完全一样**，只能靠
  `button[data-slot='button'][data-variant='default'][data-size='sm']` 定位
  （见缺陷 32）；点完要**轮询**等跳转，固定 sleep 会漏（缺陷 33）。
- **galgame.dev（真紅論壇）**：`search?term={q}&in=titles`，**未登录 302 到 `/login`**，
  `/api/search` 回 401 `not-authorised`。但**帖子详情页完全公开**
  （`/topic/<slug>`，slug 自带 tid 前缀，不能再拼 tid），正文里就有网盘链。
  分类 API 未登录可枚举：`/api/category/21/网赚盘资源?page=N`（20 条/页、4504 页）。
  现在的做法是**让用户登录一次**（`login_url` + `/api/login` + 前端按钮），
  登录态存进程序自己的 profile 并由 worker 播种。**注意**：用户在**自己** Chrome
  里登录过不算数（专用 profile + Chrome 136 默认目录禁令）。
- **jidiyouxi**：URL 模板 `search/detail/{q}`；详情页网盘链在整页 HTML 的 `#appState`
  SSR 数据里，`<a>` 标签 0 条外链；`og:image` 是坏字符串 `"[object Object]"`（站点自己的 bug）；
  不同游戏默认 tab 不同（本体/修改器/讨论求助）。
- **gamer520**：`?s={q}`；搜索页混着大量 WordPress 导航菜单链接，必须剥离站点外壳
  （平衡扫描，不是正则）。详情页分两种：**有些帖子的 HTML 直接带 3 条百度盘链**
  （如 `/18974.html`，英文查询命中），**有些帖子只有 `/go?post_id=` 跳板**且页面写
  `文件密码：xxxx`（如中文查询命中的 `/18985.html`）。跳板落地页是第三方聚合站的
  **用户上传帖**，与本次查询的游戏无归属关系 → 报 `NEEDS_GATE`，**不自动跟进**。
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
  （2026-10-21 打包验证时本机已是 **155.0.8059.86**，UA 由 `read_chrome_version` 现读）
- **不能复用默认 profile**：Chrome ≥136 拒绝为默认 user-data-dir 开 DevTools，
  报 `DevTools remote debugging requires a non-default data directory`。
  用专用 profile `game-finder\chrome-profile`（首次需手动登录目标站，cookie 会持久化）。
- **代理必须显式传** `http://127.0.0.1:6234`（系统代理端口，不是 7890）。
  实测：不传 proxy 跟随系统 4/5 站，显式传 5/5 站。
  **2026-10-21 补充**：这只是「需要代理时」的要求；实测 18/19 站直连可用，
  所以默认改为自动探测 + 回退直连（见缺陷 35）。
- **UA 必须显式设成真实 Chrome UA**：ankergames 与 iacg 在纯无头指纹下返回 403，
  加真实 UA 后 200。
- 清理孤儿 Chrome（只杀项目 profile，不碰用户浏览器）：
  ```powershell
  Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
    Where-Object { $_.CommandLine -like "*game-finder\chrome-profile*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
  ```

### 打包（2026-10-21 实测）

- **PyInstaller 6.22.3**，Python 3.14.6，onedir 模式（`game-finder.spec`）。
- 产物：`dist/game-finder/` **142.8 MB**；`dist/game-finder-0.1.0-win64.zip` **60.9 MB / 834 文件**。
- 体积构成：Playwright `driver/`（node.exe 89 MB + package/）约 102 MB，是主要部分。
- 构建：`python tools/build_portable.py`（自动剔掉 `data/`、`logs/`、`chrome-profile-*`）。
- **打包版实测**（解压到 `D:\K\deepseek\_ziptest`，全新路径）：
  - `--check` 正确报告 frozen / bundle_root / app_root / chrome 版本
  - 首次运行自动在 exe 旁生成 `config.yaml` / `sites.yaml` / `data/` / `logs/`
  - `/api/sites` 19 站；`/` 返回 UI（13187 字节）
  - **中文「夏色四叶草」→ ok=5/14**（inarigal 1 / galgamex 3 / anime-sharing 21 / acggw 2 / kungal 4）
  - **英文「enderlilies」→ ok=4~5/16**（playzip 1 / gamebounty 4 / touchgal 3 / gamer520 3 / ankergames 1）
  - 直连与走代理的**结果一致**（nyaa 直连超时属预期）


---

## 八、代码地图

```
app.py                      启动 uvicorn + 开浏览器；--check 诊断；--no-browser；--port 覆盖端口
config.yaml                 profile 路径、代理（auto_detect）、超时
sites.yaml                  21 站注册表
game-finder.spec            PyInstaller 打包定义（onedir）
README.md                   面向拿到 zip 的用户的使用说明
finder/paths.py             运行形态路径：bundle_root（只读）/ app_root（exe 旁可写）
finder/proxy.py             代理探测：parse_server / probe_alive / resolve / apply
finder/engines.py           引擎兜底：engine_links（纯 URL 拼接）/ linked_site_count / needs_fallback
finder/login.py             手动登录：LoginSession（有头窗口）/ looks_logged_in / login_state（只读 Cookie）
finder/lang.py              detect_lang（zh/en/ja）
finder/models.py            Site / SearchSpec / SearchHit / Download / GameDetail
finder/sites.py             load_sites / filter_sites_by_lang
finder/browser.py           BrowserSession（专用 profile + 真 UA + 自动代理）
                            find_chrome（配置路径 → 候选表）
finder/search.py            build_search_url / parse_result_links / pick_best / strip_chrome
                            clamp_query_detail（半截词判定）
finder/detail.py            extract_card / extract_downloads / decode_gb_dl_links
finder/pipeline.py          search_one（url/form/index 三模式）/ _follow_detail_gate
                            _query_evidence_ok（全 token 证据闸）/ _fetch_popup_redirect_links
                            run（缓存 + 并发）/ normalize_query / resolve_worker_primary
finder/health.py            classify / check_site（状态机就绪，无定时器）
finder/store.py             SQLite 缓存（成功 12h / 失败 30min）+ 健康历史，线程安全
finder/web/server.py        FastAPI + SSE，支持 refresh 强制刷新；有链接站点 < 3 时发 engines 帧
                            /api/login（开窗口等用户登录）+ /api/login/state（只读探测）
finder/web/static/index.html  单页 UI（引擎兜底块 + 需要登录的站卡片上的登录按钮）
tests/                      578 个离线测试 + fixtures
tools/build_portable.py     构建便携版 + 打 zip
tools/probe_engines_ui.py   真机验证引擎兜底块（真 Chrome + 真服务，结果写 JSON）
tools/probe_packaged_engines.py  同上，但跑解压后的 exe（验 _internal 里的静态资源）
tools/probe_login_flow.py   真机验证登录窗口（有头 + 落在登录页 + 超时人话）
tools/probe_login_ui.py     真机验证登录框只在 needs_login 且无链接的卡片上出现
tools/probe_login_outcome.py 真机确认 galgame.dev 未登录搜索 → outcome=not_found
tools/probe_packaged_login.py  同上但跑解压后的 exe（验 _internal 里的静态资源与 JS）
```

---

## 九、下一步建议（按价值排序）

### 已修完的站（原建议 1、2）

- **ggbases** ✅ 三语 WRONG_GAME → 日文 dl=7、中文/英文 `NO_RESULTS: 0 個資源`（站点真 0 条）
- **kungal** ✅ SPA 标签页 + `\u002F` 转义 + base64 封面 + 讨论帖压分，`千恋万花` → dl=23
- **anime-sharing** ✅ 论坛帖 slug + 求资源帖压分 + 页面装饰过滤，`制服カノジョ` → dl=3
- **galgamex** ✅（2026-10-20）`popup_redirect` 流程接入，详见缺陷 30。
  **真站已复测**（2026-10-20，Playwright 直连 + 真实 UA）：
  `/game/cbe7d89e` 上 `_fetch_popup_redirect_links` 点 3 个资源按钮 → 取回 **3/3** 条链
  （2 个分卷直链 + `https://pan.baidu.com/s/1aCmoplMimsXAb16i9tfP_A?pwd=us6i`），
  `galgamex_errors` 为空。期间发现并修掉三个真机才暴露的问题：
  选择器是猜的（缺陷 32）、固定 sleep 漏最后一条（缺陷 33）、`.z01` 分卷判 unknown（缺陷 34）。

### 已修完的站（2026-10-22 增补）

- **galgame.dev（真紅論壇）** ✅ 登录墙已解决 —— 不是绕过，而是给用户一个**登录入口**：
  卡片上「打开浏览器登录」→ 有头窗口落到 `/login` → 登完自动重搜。
  真机验证（2026-10-22）：`LoginSession` 12s 超时正确返回人话；落地页
  `https://galgame.dev/login`、title `登录帐号 | 真紅論壇`；
  未登录搜索 `NEEDS_LOGIN` → `outcome=not_found` → 登录框出现（真 Chrome 跑真 JS 确认）；
  `direct`/`pan` 卡片与 nyaa/touchgal 均不长按钮。
  **打包版也已验证**（`tools/probe_packaged_login.py`，跑解压后的 exe）：
  19 站带 `needs_login`/`login_url`、`/api/login` 拒绝不需要登录的站、
  真浏览器里 `renderLogin` 在 `_internal` 的静态资源上同样长按钮。

### 仍待处理

0. **本机直连 `github.com` 不通，但 `api.github.com` / `uploads.github.com` 通** ——
   `github.com` 解析到 `20.205.243.166`（被墙），`git push` 与 Release 下载都会
   `Failed to connect to github.com:443`。**推拉都要显式走代理**：
   `git -c http.proxy=http://127.0.0.1:6234 -c https.proxy=http://127.0.0.1:6234 push`
   （或 `git config --local http.proxy`）。API 上传不需要代理。
   `140.82.113.4` / `140.82.114.4` / `140.82.121.3` 直连均 200，需要时可 `--resolve`。
1. **`NO_RESULTS: pick_best returned None`**。要先做对照实验区分两种成因：
   - 候选全是 0.5 分（详情形状判据不认该站 URL）→ 改 `DETAILISH_RE` 或给站点配 `detail_pattern`
   - 候选有 1.0 分但标题里没有查询词（该站用别的语言/罗马音命名）→ 站点事实
   已结案的：**byrutgame** = 站点整词检索，连写英文名匹配不到（缺陷 22，无解）；
   **jidiyouxi 查日文** 0 命中属正常（中文站，语种路由已排除）。
2. **gamebounty 的 `WRONG_GAME`**（查日文）：搜索返回 1 条但页面证据 0。该站 `/zh/` 前缀
   强制中文界面，查日文游戏名匹配不到正文 —— 可能需要去掉 `/zh/` 或按语种切前缀。
3. **两个 `BLOCKED_SEARCH`**（nysoure、lzacg）：Cloudflare 按出口 IP 拦。属基础设施问题，
   用户换节点或加登录态后才可能通，代码侧无解。
4. **gamer520 中文通道无直链**（缺陷 21）：`/go` 跳板落地页是第三方用户上传帖，
   归属无法确认 → 已改成报 `NEEDS_GATE` 并留存跳板证据。**除非能验证落地页归属，
   否则不要自动跟进**（跟进等于把别的游戏的链接挂给用户）。
5. **健康巡检定时器** —— 用户 m02579 已明确说「定期检查可用性，不需要了」，**不做**。
   `health.py` 的状态机保留，供将来手动巡检或 UI 面板复用。
6. ~~发布到 GitHub~~ ✅ **已完成（2026-10-21）**
   仓库 <https://github.com/KTEC1200/game-finder>（**公开**，MIT），
   Release **v0.1.0** 附件 `game-finder-0.1.0-win64.zip`（60.9 MB / 834 文件）。
   用户拍板：公开仓库 + zip 放 Release 附件 + MIT + 仓库名 `game-finder`。
   发布前审过：无 token/密码/密钥；只有本机代理端口 `127.0.0.1:6234` 与
   若干 `C:\Users\27025\Desktop\...` 绝对路径（自己的机器路径，不影响功能）。
   `chrome-profile/`、`data/`、`logs/` 均未被跟踪（`.gitignore` 覆盖）。
   **发布验证**：从 Release 真下载 → SHA256 与本地一致
   （`5c0de990554ff738fd3287840845b01320d9724b15d0996d73cac6c860b1cb8e`，63872343 字节）
   → 解压到全新路径 → `--check` 正确 → 真跑「终焉之莉莉」2/14 →
   `#engines display:block` + 四条链接正确。**发出去的包确实能用。**

### 测量纪律（这轮踩到两次，都花过代价）

- **分母必须与语种路由一致**：清扫脚本曾遍历全部 21 站而不走 `filter_sites_by_lang`，
  把不参与该语种的站算进分母 → 数字全错（详见第二节的修正说明）。
- **单跑 vs 并发必须隔离 profile**：`run()` 在「只传 1 个站」时会把 workers 夹到 1 并
  走串行路径，此前它给 `_safe` 传 `None` → 所有子进程都去开**主 profile**，并发即
  `TargetClosedError`，表现为整批假失败。已加 `run(..., profile=...)` 参数：
  显式指定 profile 时**强制串行**并跳过 worker 播种。`sweep_par.py` 给每个并发槽
  一份 `chrome-profile-sweep<N>`。
- **子进程崩溃不许记成 TIMEOUT**：`sweep_par.py` 现在区分「卡住被杀」（`TIMEOUT_<n>s`）
  与「自己崩了」（`CRASH_rc<N>: <stderr 末行>`）—— 曾把 `ImportError` 藏成 21 个
  TIMEOUT，白查一轮。
- **测试脚手架也会说谎**（2026-10-20 一次踩两处）：`_FakeDetailPage` 的 `content()`
  读 `self._search_html`，而 `__init__` 从没设过这个属性 → 一运行就 AttributeError，
  看起来像实现有 bug；`test_mid_word_cut` 把 `enderlilies[:10]` 的期望值写成
  9 字符的 `enderlili`（正确是 `enderlilie`），与同文件锁定的 `clamp_query` 契约
  自相矛盾。**先核对测试自身的期望值能不能由规则推出来，再怀疑实现。**
- **离线全绿 ≠ 真站能用**（2026-10-20，galgamex 连踩三次）：测试里写死的选择器
  `a.download-provider` 在真站**根本不存在**（纯 `<button>`，静态 HTML 里该串出现 0 次）；
  固定 400ms 等待在真机上漏掉最后一个供应商按钮；`.z01` 分卷被判 unknown。
  三个问题**没有一个能被离线测试发现**，全靠 Playwright 直连真站逐元素量出来。
  → 凡是涉及第三方站点 DOM/时序的改动，**必须有一次真机验证**才能标 ✅；
  且真机脚本要**写 JSON/TXT 再用 read 看**（GBK 控制台会把 CJK 打成乱码，
  直接看 stdout 会误判按钮文字）。
- **「能构建」≠「能运行」**（2026-10-21，打包）：PyInstaller 退出码 0、产物目录
  看着齐全，但打包版仍可能在启动时才暴露问题（`ROOT` 指向临时目录、
  Playwright driver 缺文件、`uvicorn.run` 字符串形式失效）。
  → 打包后的验收必须是：**在新路径解压 → `--check` → 起服务 → 真跑一次搜索**。
  本轮就是这么发现 `config.yaml` 没被复制到 exe 旁边、`node.exe` 是否带全的。
- **测试要锁住「真机量出来的值」**（2026-10-21）：`test_galgamex_selector_is_the_measured_one`
  把真机测出的选择器写进断言，`test_popup_redirect_sites_have_both_selectors`
  在配置层锁死「有 download_flow 就必须两个 selector 都在」——
  否则缺 selector 只会静默返回空列表，看起来像「站点没资源」。
- **测「代理回退」必须固定探活结果**：`fake_pw` fixture 里把 `probe_alive` 固定成 True，
  否则整批浏览器用例的结果会随「本机代理开没开」飘（本轮真的踩到过一次）。
- **前端功能也要真机验一次**（2026-10-21，引擎兜底）：离线测试只能锁「容器在 `<main>` 之前、
  默认隐藏、搜索时清空、链接过 `safeUrl()`」这些**结构**，锁不住「真浏览器里它到底显示没有」。
  `tools/probe_engines_ui.py` 起真服务 + 真 Chrome，读 `getComputedStyle(...).display`、
  每个按钮的 `href`、以及 `compareDocumentPosition` 判 DOM 顺序 —— 实测「终焉之莉莉」
  2/14 出链 → 兜底块 `display:block`、4 个链接 CJK 编码正确、`engines_before_results: true`。
- **源码真机绿 ≠ 打包版真机绿**：静态资源在打包后来自 `_internal/`，
  spec 的 datas 若漏收改动，界面上就是旧的。`tools/probe_packaged_engines.py`
  跑**解压后的 exe** 做同一套断言，本轮实测同样 2/14 → `display:block`。
  打包验收 = 「新路径解压 → `--check` → 起服务 → 真跑一次搜索 → 看 UI 元素」。


### 已完成的基础设施

- **Store 缓存接线**：缓存键 = `(归一化截断后查询词, site_id)`，成功 12h / 失败 30min，
  `refresh=true` 绕过。实测重复搜索 53.9s → **0.5s**。
- **并发化**：`config.yaml` 的 `search.workers`（默认 3），每 worker 一份独立
  `chrome-profile-w<N>`，从主 profile 播种登录态（0.02s）。实测 93.1s → **44.1s（2.1x）**。
