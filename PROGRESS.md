# Game Finder — 实现进度与真实状态

> 更新：2026-10-17
> 项目根目录：`C:\Users\27025\Desktop\game-finder\`
> 设计文档：`docs\superpowers\specs\2026-10-16-game-finder-design.md`
> 实现计划：`docs\superpowers\plans\2026-10-17-game-finder-implementation.md`

---

## 一、怎么启动

```powershell
cd C:\Users\27025\Desktop\game-finder
python app.py
```

浏览器会自动打开 `http://127.0.0.1:8734/`。输入游戏名（中文/英文/日文均可），点搜索。

---

## 二、已完成并通过验证的部分

| 模块 | 文件 | 状态 |
|---|---|---|
| 语种判定 | `finder/lang.py` | ✅ zh/en/ja，边界已验证 |
| 数据模型 | `finder/models.py` | ✅ |
| 22 站注册表 | `sites.yaml` + `finder/sites.py` | ✅ url 17 站 / form 5 站 |
| 浏览器层 | `finder/browser.py` | ✅ 专用 profile + 真实 UA + 显式代理 6234 |
| 搜索层 | `finder/search.py` | ✅ url/form 双模式 + 导航页过滤 |
| 详情抽取 | `finder/detail.py` | ✅ 整页 HTML 抓网盘链 + 二维码解码 |
| 抓取管线 | `finder/pipeline.py` | ✅ |
| 存储 | `finder/store.py` | ✅ SQLite 缓存 + 健康历史 |
| 健康状态机 | `finder/health.py` | ✅ ok/ok_no_hits/degraded/cloudflare_block/needs_login/unreachable |
| Web 服务 | `finder/web/server.py` | ✅ FastAPI + SSE |
| 单页界面 | `finder/web/static/index.html` | ✅ 流式卡片 + 语种提示 |

**测试：132 passed**（`python -m pytest tests/ -q`）

**语言路由已在真实浏览器验证**：
- 输入「终焉之莉莉」→ 识别**中文** → 参与 **17 站**，跳过 5 站
- 输入「enderlilies」→ 识别**英文** → 参与 **18 站**，跳过 4 站
- 日文 → 12 站

---

## 三、真实抓取成功率（重要，不是全站可用）

**这是实测数据，不是估计。**

单站测试（无并发干扰，可信）：

| 站点 | 结果 |
|---|---|
| **机地 jidiyouxi** | ✅ **完整可用** — 标题/封面/大小/2 条网盘链 |
| **Gamer520** | ✅ **可用（英文查询）** — 3 条网盘链 |
| Nyaa | ❌ NO_RESULTS |
| flysheep | ❌ NO_RESULTS（该站确实无此游戏） |

12 站混跑（含并发干扰，部分站点因 profile 冲突误报）：

| 类别 | 站点 | 说明 |
|---|---|---|
| ✅ 完整可用 | 机地 | 主站可用 |
| ⚠️ 找到页但无链接 | gamer520、鲲 kungal、nysoure | 详情页 0 条网盘链、0 磁力、无登录墙 —— 链接在 JS 交互或会员态后面 |
| ❌ 真无收录 | flysheep、爱之列车、稻荷、量子ACG | 站内确实搜不到该游戏，诚实报 NO_RESULTS |
| ❌ 搜索页无详情链接 | acggw、nekogal、galgamex | 修复后诚实报 NO_RESULTS（修复前会错误抓取 `/donations` 捐赠页）|
| ❌ 需登录 | galgame.dev | 搜索重定向到 `/login` |
| ⚪ 未适配 | gamebounty、月谣、TouchGal、梓澪、Anime-Sharing | 5 个 form 模式的站，搜索框选择器尚未实测 |

**诚实结论：22 站中，端到端可用的目前是 1-2 个（机地、Gamer520 部分查询）。其余站点诚实报错，不会给出错误结果。**

---

## 四、未实现的部分

1. **UI 健康面板** —— spec §4 要求，但 `index.html` 只做了搜索卡片。`/api/health` 接口存在且有数据，但没有可视化面板。
2. **health.json 快照 + adapter_status 回写** —— 健康巡检的持久化部分。
3. **定时巡检调度器** —— `health.py` 有状态机但没有定时触发。
4. **gamer520 的 `/go?post_id=` 跳板适配** —— 它的详情页现在只暴露跳板链接。自动跟进有风险（实测会跳到别的游戏或触发下载），需要落地页标题一致性校验。
5. **5 个 form 模式站的选择器** —— 需要逐站实测。

---

## 五、已修复的真实缺陷（记录教训）

这些是开发和真站测试中发现并修复的，不是设计时就有的：

1. **相对 URL 被丢弃** —— 线上 jidiyouxi 返回 `/topic/detail/NNN`，旧解析器要求 `http` 开头 → 线上命中 0（夹具显示 41）。已用 `urljoin` 修复。
2. **标题取错** —— 旧逻辑取 href 附近 300 字符窗口，在真实页面上拿到的是导航菜单文本。已改为解析 `<a>` 本身。
3. **子串误匹配** —— 查询 `AI` 匹配到了 `Chained`。已改用拉丁词边界。
4. **静态资源被当结果** —— gamer520 搜索页 39 个「结果」大半是 CSS 文件，且会选中 `/pcplay` 分类页。已加 `ASSET_RE`。
5. **导航页/捐赠页被当游戏** —— acggw→`/game`、nekogal→`/forums`、galgamex→`/donations`。已修 `pick_best`：无详情形状候选时返回 `None`。
6. **`/game/` 尾斜杠漏洞** —— `TERMINAL_NAV_RE` 匹配不到带尾斜杠的 `/game/`。已修。
7. **二维码图片被当下载链** —— `api.qrserver.com/...&data=<pan url>` 的图片 URL 被列为下载。已排除，同时解码其中的真实链接。
8. **`chrome.exe --version` 在 Windows 上无效** —— 它只是激活已有窗口并输出 GBK 文本。改用 Win32 版本资源。

---

## 六、已知环境问题

**Chrome profile 冲突**：如果上次运行残留了 chrome 进程，下一次启动会报 `TargetClosedError`。清理方式：

```powershell
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" |
  Where-Object { $_.CommandLine -like "*game-finder\chrome-profile*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

**不要并发跑多个冒烟测试** —— 它们争用同一个 profile，会互相干扰导致误报。

---

## 七、下一步建议（按性价比排序）

1. **修 gamer520 跳板** —— 它是主力网盘站，实测有 3 条链接。加落地页标题一致性校验即可。
2. **实测 5 个 form 模式站的选择器** —— 这是剩下 5 站的唯一阻塞点。
3. **补 UI 健康面板** —— 让用户能看到哪些站可用。
4. **排查鲲 / nysoure / nekogal 的链接位置** —— 它们的详情页确实没链接，需要看是否要模拟点击或登录。
