# 弈 · PlayGo

[English](README.md) · [中文](README.zh-CN.md)

本地运行的围棋对弈程序：**KataGo 驱动的三档 AI**、实时 AI 推荐
与形势判断、读秒计时、悔棋、自动保存 SGF 棋谱与 AI 深度复盘——全部在你的
机器上运行，无需账号，配置完成后不依赖网络。

## ✨ 功能

- **双人对弈**：同屏轮流落子，黑先白后，中国规则数子法
- **人机对弈**：官方 KataGo `b18c384nbt` 网络，三档棋力：

  | 难度 | 约相当于 | 实现方式 |
  |---|---|---|
  | 简单 | 15k ~ 5k | 极小搜索量 + 宽先验采样，走出"人味"失误 |
  | 中等 | 业余 1~4 段 | 中等搜索量 + 窄采样 |
  | 困难 | 超职业 | 800 visits（GPU）全力搜索取最优 |

- **计时读秒**：默认主时 30:00，耗尽后 60 秒 ×3 日本式读秒——每次轮到
  重新满额计时，仅回合内超时才扣一次机会（同回合可连扣），用尽判负
  （可选 5:00 快棋 / 60:00 / 不限时）
- **悔棋**：人人模式退 1 手；人机模式退回到你上一手之前（Ctrl+Z）
- **AI 推荐**：当前局面 Top-3 候选点 + 胜率，始终由可用最强引擎计算，可开关
- **形势判断**：逐点归属热力图 + 胜率 / 目差
- **自动存谱**：对局结束自动写入 `records/`（标准 SGF 格式）
- **AI 深度复盘**：胜率曲线（可点击跳转）、逐手评价（神之一手 → 败着）、
  AI 建议着法、形势回看
- **终局点目**：双停一手、或对弈中随时点「点目」主动终局——引擎按所选贴目
  自动判定死活并点清黑白目数，评定胜负后询问是否接受；确认即终局存谱，
  也可选择继续对弈（不撤手数）

## 📄 License

- **PlayGo 自身代码**（本仓库中除下载产物外的全部内容）：**MIT**，见
  [LICENSE](LICENSE)
- **KataGo 引擎**与**神经网络**是 David J Wu（"lightvector"）及
  katagotraining.org 社区的第三方作品，均为 MIT 式许可证。它们**不进入本
  仓库**：应用按需从官方源下载到 `backend/engines/`（`package.bat` 打包
  离线发行版时会一并收集，并已按要求附带其许可文本）
- 完整清单见 [docs/licenses/THIRD-PARTY-NOTICES.md](docs/licenses/THIRD-PARTY-NOTICES.md)

## 🏗️ 项目架构

```
┌─────────────────────────── 浏览器 ────────────────────────────┐
│  TypeScript + Canvas 2D（无框架，产物约 40 KB gzip）           │
│  main.ts（路由） board.ts（棋盘渲染） audio.ts（WebAudio 音效）│
│  screens/menu · play · review（三屏）                          │
└───────▲───────────────────────────────────────▲───────────────┘
        │ REST  /api/...                         │ WebSocket /ws
        │（命令与查询）                            │（状态/计时/下载进度…）
┌───────┴───────────────────────────────────────┴───────────────┐
│  Python 3.11+ · FastAPI + uvicorn          playgo.main        │
│                                                                │
│  ┌────────────┐  ┌──────────────┐  ┌────────────────────┐    │
│  │ GameSession │  │ EngineManager│  │ DownloadManager    │    │
│  │ (game.py)   │  │ (katago.py)  │  │ (downloader.py)    │    │
│  │ rules.py:   │  │  ↕ stdin/    │  │  GitHub Releases + │    │
│  │ 落子/提子/   │  │    stdout    │  │  katagotraining.org│    │
│  │ 超级劫/数子, │  │  JSON 行协议 │  │  引擎+模型下载解压  │    │
│  │ 计时读秒,    │  └──────┬───────┘  │  带进度回调         │    │
│  │ 悔棋        │         │          └────────────────────┘    │
│  └────────────┘  katago.exe analysis（独立子进程）            │
│                  双引擎包：CPU 轻量（默认）/ GPU 最强（可选）  │
│                  选中包启动失败自动回落另一已装包               │
│                                                                │
│  sgf.py（SGF 读写）  settings.py（预设与直链）                  │
│  records/（棋谱+分析缓存）  ticker 任务（计时 → WS 广播）       │
└────────────────────────────────────────────────────────────────┘
```

### 目录结构

```
├── start.bat               一键启动（必要时构建 → 起服务 → 开浏览器）
├── dev.bat                 调试入口（杀旧实例 → 强制重建前端 → 起服务）
├── package.bat             打包发行版：前端+后端+引擎 → dist-app/（离线可玩）
├── backend/                Python 包（uv 管理）
│   ├── src/playgo/
│   │   ├── rules.py        围棋规则：合法落子、提子、位置超级劫、
│   │   │                   中国规则数子法——纯逻辑，完整单元测试
│   │   ├── game.py         权威对局状态机：轮转、双方时钟、读秒次数、
│   │   │                   悔棋语义、点目流程（双停一手或主动点目，
│   │   │                   拒绝结果可无损返回对弈）
│   │   ├── katago.py       KataGo analysis 引擎封装：子进程生命周期、
│   │   │                   JSON 行协议、视角钉死为黑方
│   │   │                   （reportAnalysisWinratesAs=BLACK，胜率/目差/
│   │   │                   归属天然黑方视角，无需翻转）、
│   │   │                   难度 = 搜索量 + 先验幂次采样
│   │   ├── main.py         FastAPI 入口：REST + /ws、AI 行棋编排、
│   │   │                   自动死活判定、复盘批量分析
│   │   ├── downloader.py   引擎/模型按需下载（进度回调 → WS）
│   │   ├── sgf.py          SGF（FF4）写入/解析 + 棋谱库
│   │   └── settings.py     用时预设、难度表、引擎包注册表、官方下载直链
│   ├── tests/              51 项测试：规则/劫/点目/读秒判负/引擎黑方视角
│   │                       归一化/引擎分包选择与推导
│   └── engines/            引擎与模型的运行时目录（git 忽略）
│       ├── bundled/eigen/    CPU 引擎（cpu 轻量包组件）
│       ├── downloaded/       GPU 引擎 + 强/轻量网络
│       └── choice.json       用户引擎包选择（仅显式切换时写入）
├── frontend/               TypeScript + Vite（无运行时框架）
│   └── src/
│       ├── board.ts        Canvas 渲染：纯色木底、渐变质感棋子、
│       │                   落子/提子动画、悬停幽灵子、推荐标记圈、
│       │                   形势热力图、死子标记、复盘导航
│       ├── audio.ts        落子声（WebAudio 合成，零音频资源）
│       ├── api.ts          REST 封装 + WebSocket 事件总线（自动重连）
│       ├── types.ts        与后端对应的 DTO
│       ├── style.css       设计系统（深色主题 token）
│       └── screens/        menu.ts · play.ts · review.ts
├── records/                棋谱：YYYY-MM-DD/NNN-结果.sgf（+ .analysis.json）
└── docs/licenses/          KataGo 引擎与网络许可文本、第三方清单
```

### 一手棋的完整路径

1. 点击交叉点 → `POST /api/game/move {point}`
2. `GameSession.play` 经 `rules.py` 校验轮次与合法性（提子/自杀/超级劫），
   结算行棋方时钟，记录本手
3. 新状态经 `/ws` 广播；前端播放落子/提子动画与音效
4. 人机模式下 `schedule_ai()` 按当前难度的搜索量向引擎请求选点；返回后
   再次校验轮次（悔棋/新对局的竞态不会污染棋局），随后正常落子
5. 推荐/形势为 GET 查询，缓存以**完整着法序列**为键——悔棋重下自动失效

### 坐标系（真实踩坑点，见 katago.py / sgf.py）

| 表示 | 原点 | 说明 |
|---|---|---|
| 内部 `point = y*19+x` | 左上，y 向下 | PlayGo 全局使用 |
| KataGo `"Q16"` | 左下，字母跳过 **I** | 出入双向转换 |
| SGF `pd` | 左上，字母 a–s 连续 | 出入双向转换 |
| 视角 | — | 引擎以 `reportAnalysisWinratesAs=BLACK` 钉死（与官方 cfg 一致）：胜率/目差/归属**一律黑方视角**，与轮谁走无关，全链路直接透传 |

### API 一览

REST：`GET /api/state` · `POST /api/game/new|move|pass|resign|undo|dead-stones|confirm-score` ·
`GET /api/game/hint|territory` · `GET /api/records[/{file}]` · `POST /api/review/analyze` ·
`GET /api/engines/status` · `POST /api/engines/download`

WS `/ws` 事件：`state`、`clocks`、`engine`、`download`、`saved`、
`review_progress|done|error`、`error`。

## 🛠️ 技术说明

| 层 | 选型 | 理由 |
|---|---|---|
| 后端 | **Python 3.11+ / FastAPI / uvicorn** | 子进程与管道的异步管理；类型化请求模型；原生 WebSocket |
| 后端工具 | **uv**（依赖+虚拟环境）、**ruff**（lint/format）、**pytest**（36 项测试） | 现代、快速、单一配置；`uv_build` 打包后 `uv run uvicorn playgo.main:app` 开箱即用 |
| 前端 | **TypeScript + Canvas 2D + Vite** | 棋盘是一整块自绘表面：无框架负担（产物约 40 KB gzip），渲染与 DPR 处理完全可控 |
| 图表 | 手绘 Canvas 折线，配色经 CVD 校验 | 胜率曲线是单一分叉序列，引图表库得不偿失 |
| 音效 | WebAudio 实时合成 | 无音频资源需要许可或分发 |
| 持久化 | 标准 **SGF** 文件 + JSON 分析缓存 | 开放格式，任何围棋软件可读 |

### KataGo 及其他开源软件的使用方式

- PlayGo **不链接、不修改 KataGo 代码**：以**官方发行 exe** 为独立子进程，
  运行其 **analysis 模式**（`katago analysis -config … -model …`），通过
  stdin/stdout 的 JSON 行协议通信，退出时终止进程。一个常驻进程服务全部
  需求（AI 行棋/推荐/形势/复盘），不同用途仅搜索量与采样策略不同
- **难度实现**基于查询参数：`maxVisits` 限制搜索量；困难档直接取最优，
  简单/中等档在 top-k 候选中按 `prior^p` 权重采样——单强网络低成本复现
  人类式的失误
- **黑方视角契约**：子进程启动即加 `reportAnalysisWinratesAs=BLACK`（与
  官方 cfg 一致），AI 行棋/推荐/形势/复盘的所有胜率、目差、归属天然都是
  黑方视角（与轮谁走无关），全链路直接透传不翻转；复盘缓存带
  `perspective` 标记，视角修复前的旧缓存自动视为未分析
- **死活判定**复用分析的 `ownership` 向量：位于对方控制区的棋子（超阈值）
  自动标为死子，玩家可点击覆盖
- 引擎分包（v1.18.1）与网络**仅从官方源下载**（GitHub Releases ·
  katagotraining.org）：**CPU 轻量包为默认**（Eigen + lionffen_b6c64 轻量网，
  约 8MB，无显卡也流畅），**GPU 最强包可选**（OpenCL + `kata1-b18c384nbt`
  强网络，约 100MB），应用内点击下载、随时切换。选中 GPU 启动失败自动回落
  CPU 包。服务启动即预热引擎，首日运行的 OpenCL 调优（约一分钟）在预热中
  完成并缓存；查询超时按难度自适应，引擎异常时自动重启重试
- 其他开源组件及许可证清单：
  [docs/licenses/THIRD-PARTY-NOTICES.md](docs/licenses/THIRD-PARTY-NOTICES.md)

## 🚀 启动步骤

### 环境要求

- **Python 3.11+** 与 [uv](https://docs.astral.sh/uv/)
- **Node.js 18+**（仅首次构建前端需要）
- 可选：NVIDIA/AMD 显卡（OpenCL 加速分析）；纯 CPU 也可运行，
  搜索量自动下调

### Windows 一键启动

```
双击  start.bat
```

按需构建前端 → 同步后端依赖 → 在 `http://127.0.0.1:8900` 起服务并打开浏览器。

### 手动分步

```bash
# 1. 前端：安装工具链并构建静态产物
cd frontend
npm install
npm run build            # 产出 frontend/dist/

# 2. 后端：安装依赖（uv 创建 .venv）
cd ../backend
uv sync                  # 开发工具加 --group dev

# 3. 启动服务（同时托管 frontend/dist）
uv run uvicorn playgo.main:app --host 127.0.0.1 --port 8900

# 4. 浏览器打开 http://127.0.0.1:8900
```

### 首次运行：引擎下载

无引擎时主菜单的引擎面板会展示两张**引擎包卡片**，按需下载并切换：

- **CPU 轻量版（默认）**：Eigen 引擎 + lionffen_b6c64 轻量网络，约 8 MB。
  无显卡电脑的推荐选择，下载小、行棋快。
- **GPU 最强版（可选）**：OpenCL 引擎 + b18c384nbt 强网络，约 100 MB。
  需要独立显卡，棋力最强；下载完成后自动启用。

下载保存在 `backend/engines/`，一次下载永久有效；已装全的包随时在卡片上
一键切换（切换即重启引擎进程，对局中也可安全切换）。跳过下载时，首次使用
AI 功能会提示。

打包完全离线的发行版：先完成下载，再运行 `package.bat` →
`dist-app/PlayGo`（已包含引擎与许可文本）。

### 开发模式

一键调试入口（重启服务 + 部署最新代码：杀掉 8900 端口旧实例、强制重建
前端、起服务，可反复执行）：

```
双击  dev.bat
```

或手动开两个终端：

```bash
# 终端 1 —— 后端（勿加 --reload：reload 模式在 Windows 上会禁用
# asyncio 子进程，KataGo 引擎起不来；改代码后重启即可）
cd backend && uv run uvicorn playgo.main:app --port 8900

# 终端 2 —— Vite 开发服务器（/api 与 /ws 代理到 8900）
cd frontend && npm run dev    # http://localhost:5173

# 测试与检查
cd backend && uv run pytest && uv run ruff check .
cd frontend && npx tsc --noEmit
```

## 📊 项目状态

核心流程均有自动化测试（规则/劫/点目/计时）覆盖，并在真实浏览器 + 真实
引擎上完成端到端验证：对局 → AI 应答 → 推荐 → 形势 → 悔棋 → 点目 →
存谱 → 复盘分析。已知简化：服务端单对局会话；固定 19 路。

**界面语言**：中英双语——首次访问跟随浏览器语言，顶栏可随时切换（本地记忆）。

## 🤝 致谢

- [KataGo](https://github.com/lightvector/KataGo)——David J Wu（"lightvector"）
  及贡献者的引擎与训练基础设施
- 网络由 [KataGo 分布式训练](https://katagotraining.org/)社区训练
- PlayGo 为独立项目，与 KataGo 无隶属关系
