# Game Finder

本地 galgame / 视觉小说资源检索器。输入游戏名，并发去 19 个资源站搜索，
把**能直接下载的链接**排在最前面，其余按「有网盘」「站点有游戏但没链接」
「没找到」分档。全程在本机跑，只有一个网页界面，没有账号、没有云端。

- **开箱即用**：不装代理也能用（实测 19 站里 18 站直连可访问）。
- **诚实优先**：宁可报「没找到」，也不给一个别的游戏的链接。每个候选标题都要
  通过「查询词证据」校验，通不过就丢掉并说明原因。
- **找不够就换引擎**：有下载链接的站点少于 3 个时，结果区上方会给出一排
  必应 / 百度 / 谷歌 / Yandex 的**跳转链接**，点一下带着你的查询词去搜。
- **便携版**：解压双击 `game-finder.exe` 就能跑，配置和数据都在 exe 旁边。

## 快速开始

### 便携版（推荐）

1. 下载 `game-finder-<版本>-win64.zip`，解压到任意目录（**不要在压缩包里直接双击**）。
2. 确保本机装了 [Google Chrome](https://www.google.com/chrome/)。
3. 双击 `game-finder.exe`。浏览器会自动打开 `http://127.0.0.1:8734/`。

首次运行会在 exe 旁边生成 `config.yaml`、`sites.yaml`、`data/`、`logs/`。
**这些是你的文件**：升级时把新的 `_internal/` 和 `game-finder.exe` 覆盖进来即可，
配置不会被覆盖。

### 从源码运行

```bash
pip install -r requirements.txt
python -m playwright install chromium   # 仅测试用；程序本身只用系统 Chrome
python app.py
```

`python app.py --check` 只打印环境诊断（路径、Chrome 版本、代理决策）然后退出。

## 环境要求

| 项目 | 要求 |
|---|---|
| 系统 | Windows 10/11 64 位 |
| 浏览器 | **系统安装的 Google Chrome**（必须，未安装会给出提示） |
| 网络 | 能直连目标站点；本地代理可选 |

**为什么不打包浏览器**：Playwright 自带 Chromium 过不了部分站点的 Cloudflare
挑战（实测 touchgal 直接 403 `Just a moment...`，系统 Chrome 正常）。打包浏览器
只会让体积增加 150 MB 还换来更差的结果，所以只依赖系统 Chrome。

## 代理

`config.yaml` 里的 `proxy` 段：

```yaml
proxy:
  enabled: true
  server: "http://127.0.0.1:6234"
  auto_detect: true      # 启动时探测端口，不通就自动直连
```

- `auto_detect: true`（默认）：启动时探测 `server` 的 TCP 端口，活着就用代理，
  死了就**自动直连**并在日志里说明原因 —— 不会再出现「代理没开 → 所有站点失败」。
- `auto_detect: false`：无条件使用代理（旧行为）。
- `enabled: false`：永不用代理。

实测（2026-10-21）：19 站里 **18 站直连可用**，只有 nyaa 直连超时。
需要 nyaa 时才需要代理。

## 结果怎么读

每张卡片带一个分档标签：

| 分档 | 含义 |
|---|---|
| **直链** | 有 `direct` 类型的下载（网盘直链、HTTP 文件） |
| **网盘** | 找到了下载，但都是网盘/磁力/filehost，需要自己转存 |
| **无链接** | 站点确实有这款游戏，但抽不到下载（可能要登录/评论/过验证） |
| **未找到** | 站点没有这款游戏，或搜索没执行成功 |

`NEEDS_LOGIN` / `NEEDS_GATE` / `NEEDS_COMMENT` 都是**诚实的产物**，不是 bug：
站点设了门槛，程序不绕过，只在界面上告诉你缺什么。

## 搜索引擎兜底

如果**有下载链接的站点少于 3 个**，结果区上方会出现一块
「资源站没找够，去搜索引擎再找」，里面是必应 / 百度 / 谷歌 / Yandex 四个按钮。

- 按钮只是**跳转链接**，程序不会去抓这些引擎的结果页，也不会把引擎结果混进卡片。
- 查询词**原样**带过去（不追加 `galgame` / `下载`），到引擎页面后你可以自己改词。
- 「找到游戏但没链接」「未找到」的站点不算数 —— 计数只算**真的给出链接的站点**。

## 配置文件

`config.yaml`（exe 旁边，可直接编辑，改完重启程序）：

| 键 | 默认 | 说明 |
|---|---|---|
| `server.port` | 8734 | 端口被占会自动往后找 10 个 |
| `browser.chrome_path` | 空 | 留空则自动查找系统 Chrome |
| `browser.headless` | true | 无头运行；某些站点需要 `false` |
| `search.timeout_ms` | 45000 | 单站搜索超时 |
| `search.workers` | 3 | 并发数，每个 worker 一份独立 Chrome profile |
| `cache.ttl_hours` | 12 | 成功结果缓存时长（失败只缓存 30 分钟） |

`sites.yaml` 是站点定义（19 个站），一般不用改。

## 自己构建

```bash
pip install -r requirements.txt pyinstaller
python tools/build_portable.py
```

产物：

- `dist/game-finder/` —— 可直接双击的文件夹
- `dist/game-finder-<版本>-win64.zip` —— 发布用的压缩包

构建脚本会自动剔除 `data/`、`logs/`、`chrome-profile-*` 等本地运行态文件。

## 开发

```bash
python -m pytest -q          # 517 个离线测试，约 6 秒
```

设计细节、踩过的坑、站点适配状态都在 [`PROGRESS.md`](PROGRESS.md)。
