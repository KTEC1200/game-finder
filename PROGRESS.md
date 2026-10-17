# Game Finder — 实现进度与真实状态

> 更新：2026-10-17（Task 12 收尾，实测于 commit `6d25615`）
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

**P0–P4 的核心实现已完成并通过测试，但真实抓取成功率很低。** 两件事分开看：

| 维度 | 结论 |
|---|---|
| 代码 / 测试 | ✅ 132 个离线测试全绿（`132 passed in 1.25s`） |
| 语种路由 | ✅ 真浏览器验证：中文→17 站，英文→18 站；日文→12 站 |
| UI | ✅ SSE 流式卡片；中文查询渲染 17 张卡、英文 18 张 |
| **单站端到端成功率（中文查询）** | ❌ **12 站实测 ok=1/12**（只有机地） |
| **单站端到端成功率（英文查询）** | ❌ **2 站实测 0 个真成功**（gamer520 报 ok 但抓到的是**别的游戏**，见 §五） |
| 健康巡检 | ⚠️ 状态机完成；**无定时器、无快照、无 UI 面板** |
| 5 个 form 模式站 | ❌ 未适配（选择器未固化，5 站全部 `FORM_FAILED`） |

「诚实报错」是本版的重要目标：宁可显示「没找到」，也不给用户一张错误的卡片。
本版确实做到了不伪造，但**没有做到让 22 站可用**，也不声称做到。

---

## 三、测试与验收证据（原样粘贴命令输出）

### 3.1 全量离线测试

```powershell
cd C:\Users\27025\Desktop\game-finder
python -m pytest tests/ -q
```

```
........................................................................ [ 54%]
............................................................             [100%]
132 passed in 1.25s
```

### 3.2 中文真站冒烟

```powershell
$env:PYTHONPATH="C:\Users\27025\Desktop\game-finder"
python tools/smoke_live.py 终焉之莉莉 --sites jidiyouxi
```

```
lang=zh participating=17 smoke_sites=1 skipped=5 form_only_skipped=0 chrome=155.0.8059.80 query_len=5
ok            jidiyouxi      hits=4 dl=2 body=54788 match=strong gates=0 18138ms 
SUMMARY ok=1/1 with_downloads=1 out=smoke_result.json
```

抓到的是对的游戏（`终焉之莉莉：骑士寂夜`），2 条真网盘链接：

```
title  终焉之莉莉：骑士寂夜中文版学习版免费下载 攻略秘籍剧情游戏讨论分享存档
cover  https://img2.52jidi.com/topic/cover/id/931503/sz/420
size   2GB      version 0.25      updated 2026-04-22
dl-1   https://pan.baidu.com/s/1h2qNncvC7HwLggJUQjccbw?pwd=jrf8
dl-2   https://pan.xunlei.com/s/VOqmxuqrby-F4G5a2DL7qlPBA1?pwd=vv5m#
```

### 3.3 英文真站冒烟

```powershell
$env:PYTHONPATH="C:\Users\27025\Desktop\game-finder"
python tools/smoke_live.py enderlilies --sites gamer520 nyaa
```

```
lang=en participating=18 smoke_sites=2 skipped=4 form_only_skipped=0 chrome=155.0.8059.80 query_len=11
ok            gamer520       hits=12 dl=3 body=40947 match=weak gates=0 11491ms 
error         nyaa           hits=3 dl=0 body=22856 match=None gates=0 9395ms NO_RESULTS: no results
SUMMARY ok=1/2 with_downloads=1 out=smoke_result.json
```

⚠️ **这次 `ok` 是假阳性**，详见 §五「已知缺陷 1」。抓到的页面是
`Switch 23.0.0 固件 + 1.12.0 整合包`，不是 Ender Lilies。`match=weak` 已经是提示，
但管线不按 match 拦截，所以仍然显示成成功卡片。

### 3.4 12 站中文混跑（本版最关键的实测）

```powershell
$env:PYTHONPATH="C:\Users\27025\Desktop\game-finder"
python tools/smoke_live.py 终焉之莉莉 --sites jidiyouxi gamer520 flysheep nysoure iacg inarigal lzacg acggw nekogal galgamex kungal galgame.dev --out tools/_smoke12_final.json
```

```
lang=zh participating=17 smoke_sites=12 skipped=5 form_only_skipped=0 chrome=155.0.8059.80 query_len=5
ok            jidiyouxi      hits=4 dl=2 body=54655 match=strong gates=0 20606ms 
no_downloads  gamer520       hits=10 dl=0 body=39882 match=weak gates=1 9235ms NO_DOWNLOADS
error         flysheep       hits=2 dl=0 body=78210 match=None gates=0 5574ms NO_RESULTS: nothing found
no_downloads  nysoure        hits=5 dl=0 body=93981 match=none gates=0 10495ms NO_DOWNLOADS
error         iacg           hits=4 dl=0 body=219071 match=None gates=0 6009ms NO_RESULTS: \u672a\u627e\u5230\u76f8\u5173
error         inarigal       hits=4 dl=0 body=11376 match=None gates=0 5499ms NO_RESULTS: \u672a\u627e\u5230\u76f8\u5173
error         lzacg          hits=3 dl=0 body=135152 match=none gates=0 5085ms NO_RESULTS: \u672a\u627e\u5230\u76f8\u5173
error         acggw          hits=17 dl=0 body=25532 match=None gates=0 6353ms NO_RESULTS: pick_best returned None
error         nekogal        hits=2 dl=0 body=255034 match=None gates=0 14838ms NO_RESULTS: pick_best returned None
error         galgamex       hits=8 dl=0 body=98000 match=None gates=0 14545ms NO_RESULTS: pick_best returned None
no_downloads  kungal         hits=16 dl=0 body=115494 match=strong gates=0 11424ms NO_DOWNLOADS
error         galgame.dev    hits=6 dl=0 body=30427 match=None gates=0 6495ms NO_RESULTS: pick_best returned None
SUMMARY ok=1/12 with_downloads=1 out=_smoke12_final.json
```

（`\u672a\u627e\u5230\u76f8\u5173` 就是「未找到相关」的 ASCII 转义——冒烟脚本为了 GBK 控制台把非 ASCII 转义了，不是乱码。）

### 3.5 UI 端到端（真启动服务 + 真浏览器点按钮）

```
server started=True url=http://127.0.0.1:8791/
loaded title=Game Finder has_input=True
case=zh start=识别语种：中文 · 参与 17 站 · 跳过 5 站（不支持该语种）
  done=识别语种：中文 · 参与 17 站 · 跳过 5 站（不支持该语种） · 完成（成功 1/17） cards=17 errs=16 dl=2 pan=2 magnet=0 direct=0 206.5s
case=en start=识别语种：英文 · 参与 18 站 · 跳过 4 站（不支持该语种）
  done=识别语种：英文 · 参与 18 站 · 跳过 4 站（不支持该语种） · 完成（成功 1/18） cards=18 errs=17 dl=3 pan=3 magnet=0 direct=0 466.3s
server stopped=True
RESULT: PASS
```

读法：UI 工作正常（有卡片、有流式、有语种提示），但**「成功 1/18」里的那 1 个是错的卡片**
（gamer520 固件包），所以英文实际有效成功是 **0**。

---

## 四、22 站真实成功率（逐站实测）

判定口径：`ok` = 拿到**对的游戏**且至少有 1 条真网盘/直链/磁力；
`no_downloads` = 详情页对了但抽不出链接；`NO_RESULTS` = 诚实报没找到。

### 4.1 中文查询「终焉之莉莉」— 12 站实测

| 类别 | 站点 | 实测结果 |
|---|---|---|
| ✅ 端到端可用 | **jidiyouxi（机地）** | ok，标题/封面/版本/大小/2 条网盘链（baidu + xunlei） |
| ⚪ 站点活着、确实没收录 | **flysheep**、**iacg**、**inarigal**、**lzacg** | 诚实报 `NO_RESULTS`（flysheep 是 WordPress "Nothing found"；三个中文站是「未找到相关」）。站点本身可访问，不是故障 |
| ⚠️ 找到页但抽不出链接 | **kungal** | 详情页是**对的游戏**（`终焉之莉莉：骑士寂夜`，match=strong），但 HTML 里 0 网盘、0 磁力、0 跳板；下载区在 JS/会员态后面 |
| ⚠️ 找到页、且**选错了游戏** | **nysoure** | 落到 `/resources/656`，页面是 `終わる世界とバースデイ`（另一个 galgame）；搜索页链接的标题被解析成 `cover`（图片 alt），选站逻辑不可信 |
| ⚠️ 只有跳板、没有直链 | **gamer520** | 本次选中的 `18985.html` 是对的（《终结的百合花 豪华中文》），但该文章只暴露 `/go?post_id=18985` 跳板（gates=1），报 `NO_DOWNLOADS` |
| ❌ 搜索页没有详情链接 | **acggw**、**nekogal**、**galgamex** | 修复后诚实报 `NO_RESULTS: pick_best returned None`。修复前会抓 `/game`、`/forums?index=3`、`/donations` 当成游戏 |
| ❌ 需要登录 | **galgame.dev** | 搜索被重定向到 `/login`，报 `NO_RESULTS`。以前会从 `/categories` 抓出一条**假的 ok**，现已修正 |

### 4.2 英文查询「enderlilies」

| 站点 | 实测 |
|---|---|
| **gamer520** | 报 `ok` + 3 条链接，但**是错的游戏**（Switch 固件包）。确认为假阳性，见 §五 |
| **nyaa** | `NO_RESULTS: no results`（sukebei 站内确实没有） |
| 其余 16 站 | 未实测 |

### 4.3 form 模式 5 站（只能站内搜索）— 全部未适配

用 `tools/verify_health_live.py` 实测，5 站全部 `FORM_FAILED`（`degraded`）：

```
gamebounty     status=degraded  latency=13119ms reason=FORM_FAILED: TimeoutError: Locator.fill: Timeout 10000ms exceeded.
sayafx         status=degraded  latency=12917ms reason=FORM_FAILED: TimeoutError: Locator.fill: Timeout 10000ms exceeded.
touchgal       status=degraded  latency=12732ms reason=FORM_FAILED: TimeoutError: Locator.fill: Timeout 10000ms exceeded.
zi0            status=degraded  latency=12298ms reason=FORM_FAILED: TimeoutError: Locator.fill: Timeout 10000ms exceeded.
anime-sharing  status=degraded  latency=43493ms reason=FORM_FAILED: TimeoutError: Locator.fill: Timeout 10000ms exceeded.
```

根因（实测首页控件清单）：

| 站点 | 首页搜索控件 | 结论 |
|---|---|---|
| sayafx | `input#search-input`（placeholder「输入关键词快速查找」） | ✅ 有可用选择器，可直接固化 |
| anime-sharing | `input[name=keywords]`（XenForo） | ✅ 有可用选择器，可直接固化 |
| touchgal | **0 个 `<input>`**，只有按钮 | ❌ 搜索在弹窗/路由后面，需要先点开 |
| gamebounty | **0 个 `<input>`**，只有按钮 | ❌ 同上 |
| zi0 | 只有隐藏的 swal2 弹窗输入 | ❌ 需要先触发弹窗 |

→ 回退选择器 `input[type=search], input[name*=s], input[type=text]` 对 5 站全都不命中。
**5 站目前一律报 FORM_FAILED，不会给出错误结果，但也完全没有结果。**

### 4.4 完全未实测的站点

`playzip`、`byrutgame`、`ankergames`、`ggbases`、`catcat`（已确认不是搜索站）以及上面所有英文查询下的 16 站。
**未实测 = 不知道，不要当成可用。**

---

## 五、已知缺陷（本次收尾实测发现，未修）

### 缺陷 1：gamer520 英文查询会给「别的游戏」的网盘链接（严重）

复现：`python tools/smoke_live.py enderlilies --sites gamer520`

搜索页 12 条候选里，**对的游戏** `18974.html`（终结的百合花 官方中文）在，
但 `pick_best` 选了 `122908.html`（`Switch 23.0.0固件+1.12.0整合包`）。

直接抓该页核对正文：`ender` / `lilies` / `终焉` / `百合花` / `莉莉` 出现次数**全部为 0**——确认为无关文章。

根因：`pick_best` 的「逐字命中率」项对**中文站 + 拉丁查询**基本是噪声
（中文标题里几乎没有拉丁字母，得分差异来自 `switch` 里的 s/i 之类巧合字符），
所以固件包以 0.37 分压过正确页面的 0.28 分。`match=weak`(0.27) 已经算出来了，
但**没有任何硬门槛**（这是 Task 7 的既定决策，背景是中文站常用不同译名，硬卡会误杀）。

代价：UI 会显示一张 `ok` 卡片、带 3 条真实网盘链接，**但那是另一个游戏的**。
这是本版最需要先修的问题。

### 缺陷 2：nysoure 搜索会选中不相关的资源页

见 §4.1：查询「终焉之莉莉」落到了 `終わる世界とバースデイ`。
同时它的结果链接标题被解析成 `cover`（`<img alt="cover">`），说明标题抽取对这类
「图片在前的卡片」标记失效。报 `NO_DOWNLOADS` 是诚实的，但选页本身是错的。

### 缺陷 3：`NO_RESULTS` 与 `NEEDS_LOGIN` 在管线里没区分

galgame.dev 实际状态是「需要登录」，管线报的是 `NO_RESULTS`。
健康状态机（`classify`）能分出 `needs_login`，但 `pipeline.search_one` 只回 `NO_RESULTS`。

### 已修复的缺陷（记录教训，别再犯）

1. **相对 URL 被丢弃** —— 线上 jidiyouxi 返回 `/topic/detail/NNN`，旧解析器要求 `http` 开头 → 线上命中 0（夹具显示 41）。已 `urljoin` 修复。
2. **标题取错** —— 旧逻辑取 href 附近 300 字符窗口，真实页面上拿到的是导航菜单文本。已改为解析 `<a>` 本身。
3. **子串误匹配** —— 查询 `AI` 匹配到 `Chained`。已改用拉丁词边界。
4. **静态资源被当结果** —— gamer520 搜索页 39 个「结果」大半是 CSS，且会选 `/pcplay`。已加 `ASSET_RE`。
5. **导航页/捐赠页被当游戏** —— acggw→`/game`、nekogal→`/forums`、galgamex→`/donations`。已修 `pick_best`：无详情形状候选返回 `None`。
6. **`/game/` 尾斜杠漏洞** —— `TERMINAL_NAV_RE` 匹配不到 `/game/`。已修（`6d25615`）。
7. **二维码图片被当下载链** —— `api.qrserver.com/...&data=<pan url>` 被列为下载。已排除并解码其中的真链接。
8. **`chrome.exe --version` 在 Windows 上无效** —— 它只激活已有窗口并输出 GBK 文本。改用 Win32 版本资源读 `155.0.8059.80`。
9. **图片被当直链下载** —— `files.seeusercontent.com/....jpg` 曾被分类为 `direct`。已加扩展名拒绝。

---

## 六、语种路由覆盖（22 站）

| 语种 | 参与 | 跳过 | 验证方式 |
|---|---|---|---|
| 中文 zh | **17** | 5 | 真浏览器点按钮，SSE `start` 帧与 UI 文案双重确认 |
| 英文 en | **18** | 4 | 同上 |
| 日文 ja | **12** | 10 | 函数级验证（`filter_sites_by_lang`）；**今天未在浏览器里跑日文查询** |

---

## 七、未实现（spec 里写了，本版没做）

| 项 | 状态 | 证据 |
|---|---|---|
| **UI 健康面板** | ❌ 未做 | spec §4/§6 要求「右侧/底部站点健康面板（状态/耗时/原因/上次检查/立即检查）」。`index.html` 里搜不到 `health` / `健康`。只有搜索卡片 |
| **`health.json` 快照** | ❌ 未做 | 无任何代码写这个文件 |
| **`adapter_status` 回写** | ❌ 未做 | `finder/sites.py` 只**读** `adapter_status`（默认 `untested`），全项目没有写回 |
| **定时巡检调度器** | ❌ 未做 | `config.yaml` 的 `health.interval_hours: 6` / `start_delay_s: 60` 没有任何代码读取；无 APScheduler/定时器 |
| **健康数据落库** | ⚠️ 半成品 | `Store.record_health()` 存在，但**全项目无调用者**；`/api/health` 因 `data/finder.db` 不存在恒返回 `{}` |
| **`PROFILE_IN_USE` 检测** | ❌ 未做 | 并发跑两个冒烟会争用同一 profile，报 `TargetClosedError`（不是可读错误） |
| **结果缓存接线** | ❌ 未做 | `Store.get_cached/put_cached` 无调用者，pipeline 每次都真抓 |
| 5 个 form 站选择器 | ❌ 未做 | 见 §4.3 |

---

## 八、延后条目（来自 SDD ledger，含当时的裁定）

按模块归类，均为 **Task 1–11 期间明确记录、有裁定、尚未处理** 的项：

**lang（Task 2）**
- `KANA_RE` 不含半角片假名（U+FF66–FF9D）与片假名音标扩展（U+31F0–31FF），粘贴半角输入会误判成 zh/en。
- `detect_lang(None)` 抛 `AttributeError`，调用方必须传 str（server 已做空串兜底，不会被触发）。

**browser（Task 4）**
- `PROFILE_IN_USE` 未实现：同一 profile 并发会以 `TargetClosedError` 失败，错误不可读。
- 代理不可用时的行为（`NEEDS_PROXY` vs 静默超时）未验证。

**detail（Task 5）**
- `COVER_ID_RE` 硬编码 `52jidi.com` 与 `/sz/420` 尺寸段；站点换尺寸段时封面 404（id 仍对）。
- `URL_RE` 不识别协议相对链接 `//host/...`。
- `VERSION_RE` 可能匹配到 JS 库版本号之类的无关小数。

**search（Task 6 / fix wave）**
- 启发式只在 2 个夹具上调过；其余 15 个 url 站未验证。
- `NAV_RE` 排除路径段 `search`，若站点把详情页挂在 `/search/` 下会被误杀。
- `DETAILISH_RE` 对标题无感知：任何带数字段的 URL 都得 1.0 分（galgame.dev 的 `/categories` 就是这样混过去的；现在只靠站点自己的「没找到」文案兜住）。
- `TERMINAL_NAV_RE` 只认 `game|games|list|index.php` 出现在路径末尾，别的站点若用 `tag`/`genre` 之类做列表入口仍可能漏。

**pipeline（Task 7）**
- gamer520 的 `/go?post_id=` 跳板未适配：实测跳转会落到不同文章的落地页（post_id=18985 → 别的游戏），自动跟进有挂错链接的风险。目前只记录 `extra.gate_links`，不跟进。
- flysheep 的「Nothing Found」页仍能抽出 2 条页脚链接（0.5 分），靠 `detail_hits` 才判成 `ok_no_hits`。
- `match` 只是诊断，无硬门槛 → 直接导致本次 §五 缺陷 1。
- `tools/smoke_result.json` 是上一次冒烟留下的脏文件；夹具 `gamer520/go_landing_sample.html` 已与线上漂移（线上用 `wpkqcg_qrcode` class，二维码解码返回 0），需重新采集。

**store（Task 8）**
- 未接入 pipeline，无缓存。
- TTL 按插入时间算，不是最后访问时间；`health_history` 无限增长，无保留策略。
- `ttl_hours=0` 表示「永远过期」（任务书要求），不要当作「关闭缓存」的哨兵值。
- `sqlite3` 默认 `check_same_thread=True` 且未开 WAL → 一个 `Store` 不能跨线程共享。

**web / UI（Task 9 / 10）**
- `/api/search` 是同步跑完整个 pipeline 再一次性吐结果：`start` 帧和结果突发之间没有任何中间帧，不是逐站渐进。
- 没有客户端断开检测（关标签页后管线仍继续跑）。
- `CONFIG` 在 import 时读取（`reload=False`），改配置要重启。
- Task 11 新增的 `ok_no_hits` 状态在 UI 里没有映射（UI 根本没做健康面板，见 §七）。

**health（Task 11）**
- `classify()` 比任务书多一个 `detail_hits` 参数：不加的话 flysheep 的「Nothing Found + 2 条页脚链接」会被判成 `ok`。
- Cloudflare 标记改为只扫可见文本：真实 gamer520 fixture 的健康页面也注入 `/cdn-cgi/challenge-platform`，扫原始 HTML 会误报 `cloudflare_block`。
- 状态集合：`ok / ok_no_hits / degraded / cloudflare_block / needs_login / unreachable`；`models.HealthRecord` 的注释没更新（没列 `ok_no_hits`）。
- `no results` 裸标记偏宽，英文站正文别处出现会误判（有 `detail_hits==0` 兜底，方向偏保守）。

---

## 九、下一步建议（按性价比排序）

1. **修 §五 缺陷 1（gamer520 英文抓错游戏）** —— 这是唯一会给用户**错内容**的路径，优先级高于「多抓几个站」。可行方向：对拉丁查询要求标题 token 命中，或把 `match` 从诊断升级为「匹配不到就返回 `NO_RESULTS` 而不是 ok 卡片」。
2. **修 nysoure 的选页 + 标题抽取** —— 目前会选到别的游戏，且标题退化成 `cover`。
3. **把 `record_health` 接上 + 补 UI 健康面板** —— 数据层已经齐了（表、`/api/health`、状态机），缺的是调用方和一块界面。
4. **固化 sayafx / anime-sharing 的选择器** —— 这两站首页直接有 `input#search-input` 和 `input[name=keywords]`，是 5 个 form 站里最容易拿下的。另外 3 站（touchgal / gamebounty / zi0）得先点开弹窗。
5. **gamer520 跳板适配** —— 只有加上落地页标题一致性校验才安全，否则会挂错游戏的链接。
6. **pipeline 区分 `NEEDS_LOGIN`** —— galgame.dev 现在混在 `NO_RESULTS` 里，用户不知道要登录。

---

## 十、环境注意事项

**Chrome profile 冲突（实测踩到）**：残留的 chrome 进程会占住
`chrome-profile\lockfile`，下一次启动直接 `TargetClosedError: ... exitCode=21`，
且报错文本完全看不出是 profile 被占用。清理方式：

```powershell
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
  Where-Object { $_.CommandLine -like "*game-finder\chrome-profile*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

**不要并发跑多个冒烟测试** —— 它们争用同一个 profile，会互相干扰并产生假失败。

其它环境事实：Python 3.14.6（无 venv）、Chrome 155.0.8059.80、代理必须显式
`http://127.0.0.1:6234`、Windows 控制台是 GBK（脚本 stdout 只打 ASCII）。
