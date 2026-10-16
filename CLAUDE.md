# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

弈 · PlayGo：本地围棋对弈程序。Python FastAPI 后端 + TypeScript/Canvas 前端（无框架），通过子进程调用官方 KataGo analysis 引擎提供 AI 行棋/推荐/形势判断/复盘。UI 中英双语（`frontend/src/locales/`，跟随浏览器，顶栏可切换），代码注释语言为中文。

## 常用命令

后端（在 `backend/` 下，uv 管理）：

```bash
uv sync                          # 安装依赖（开发工具加 --group dev：pytest/ruff/ty）
uv run uvicorn playgo.main:app --port 8900 --reload   # 开发模式
uv run pytest                    # 全部测试（rules/ko/数子/计时判负）
uv run pytest tests/test_rules.py -k superko          # 单个测试
uv run ruff check .              # lint（select=ALL + pyproject 定制忽略表）
uv run python scripts/smoke_engine.py                 # 引擎冒烟（需已下载引擎）
```

前端（在 `frontend/` 下）：

```bash
npm run dev        # Vite 开发服 :5173，/api 与 /ws 代理到 8900
npm run build      # tsc --noEmit + vite build → frontend/dist/
npx tsc --noEmit   # 仅类型检查
```

一键启动 / 打包（Windows）：`start.bat`（构建前端→起服务→开浏览器，:8900）；`package.bat`（含引擎的离线发行版 → `dist-app/`）。后端同时静态托管 `frontend/dist/`，单跑后端前需先构建前端。

## 架构要点

- **单实例状态**：`main.py` 模块级 `AppState` 持有全局唯一的 `GameSession`（一次只存在一盘棋）、`EngineManager`、`DownloadManager` 与 WS 客户端集合。命令走 REST `/api/...`，状态经 `/ws` 广播（`state`/`clocks`/`engine`/`download`/`saved`/`review_*`/`error`）。
- **一个引擎进程服务所有需求**：`EngineManager` 优先 OpenCL(GPU)、失败回落 Eigen(CPU)，spawn `katago analysis` 子进程走 stdin/stdout JSON 行协议。AI 行棋、推荐、形势、复盘只是 visits 与采样参数不同，不另起进程。查询统一走 `EngineManager.analyze/pick_move` 自愈入口（超时=实例疑似卡死，自动重启重试一次）；启动时的预热查询（5 visits）提前触发调优并探测卡死实例，首次运行的 OpenCL 调优约 1 分钟，之后亚秒。
- **职责分层**：`rules.py` 纯规则（提子、positional superko、中国规则数子法，全单测）；`game.py` 权威状态机（回合、双方独立计时/读秒、悔棋语义、pass 与点目流程）；`sgf.py` SGF(FF4) 读写 + `records/` 棋谱库；`settings.py` 集中所有预置（难度表、用时、官方下载 URL）。
- **AI 行棋竞态防护**：`schedule_ai()` 的回复在落子前重新校验当前该谁走，悔棋/新对局期间到达的回复直接丢弃。
- **缓存键 = 完整着法序列**（非手数）：`_hint_cache`/`_terr_cache`，悔棋重下同手数也会失效。
- **前端**：`main.ts` 路由 → `screens/menu|play|review`；`board.ts` Canvas 渲染器（动画、悬停、推荐环、归属热力、死子标记）；`api.ts` REST 封装 + WS 事件总线（自动重连）；`types.ts` 与后端 DTO 一一对应，改协议需两侧同步。

## 关键约定（易错点）

- **子进程行上限陷阱**：KataGo 单行 JSON 响应可达 135KB+（visits 越大越长），`create_subprocess_exec` 必须传 `limit=2**22`——asyncio `StreamReader` 默认 64KB 行上限会让 `readline()` 抛错**静默杀死读取任务**，表象是随机"分析超时"且引擎永久失聪（简单/中等档响应小不触发，困难档必中）。查询超时按 visits/后端用 `auto_timeout` 估算，勿回退固定 60s。
- **坐标三套体系**：内部 `point = y*19+x`（左上原点、y 向下）；KataGo `Q16`（字母跳 I、从底部数行）；SGF `pd`（a–s 不跳）。转换只在 `katago.py` / `sgf.py` 进出。`ownership` 向量下标即内部坐标（行优先、y 从上）。
- **一律黑方视角（引擎侧已钉死，勿再翻转）**：官方 cfg（v1.13+）含 `reportAnalysisWinratesAs=BLACK`，引擎输出的 winrate/scoreLead/ownership（含 moveInfos）**本身就是黑方视角，与轮谁走无关**；`start()` overrides 已显式钉死该值防未来 cfg 变更。`_normalize` 只做字段映射，**绝不按 to_move 翻转**——曾误当"行棋方视角"翻转过，症状是复盘胜率曲线在 50% 上下锯齿、轮白时形势/死活判断黑白颠倒（`rootInfo.currentPlayer` 可核对行棋方，但视角不依赖它）。冒烟/校验视角要取"棋子本点"归属：2-2 点等常因预期点三三入侵被网络判给对方，符号不定，不能当断言点。复盘缓存 `*.analysis.json` 带 `"perspective":"black"` 标记，缺标记的旧文件在 `record_detail` 一律视为未分析。
- **错误协议**：后端不产出任何用户可见文案——异常（`errors.py` 的 `PlayGoError` 系）携带稳定 `code` + `params`，REST detail 与 WS error 事件下发 `{"code","args"}`，前端 `i18n.errText` 查词典组词。新增错误必须两侧同步（`errors.py` ↔ `ERR_KEY` 表 ↔ 两份词典）。
- **i18n**：`frontend/src/i18n.ts` + `locales/zh.ts`（键权威）+ `locales/en.ts`（`Record<keyof typeof zh, string>`，tsc 强制键齐全）。`t()` 只能渲染期调用；语言切换时 `main.ts` 重建三屏并 `reapplyPlay()/reapplyReview()` 重放状态。
- **难度实现**：`settings.DIFFICULTY_PRESETS` —— visits 上限 + `prior^p` 采样（easy/medium 走 top-k 采样制造"人味"失误，hard 取最优）；CPU 下 visits 自动降为 `cpu_visits`。难度显示文案在前端词典（`diff.*`），预设表只存参数。
- **死活判定**复用 analysis 的 `ownership` 向量（对方地盘上的己方棋子超阈值判死），玩家可点击改判。胜负结果只传 `reason/winner/margin` 枚举数值，文案前端组合。
- **引擎不入库**：`backend/engines/` 下的 exe/模型/git 忽略，运行时从官方源按需下载；打包发行时必须随附许可文本（`docs/licenses/`）。

## 代码风格

- 后端 ruff `select=["ALL"]` + pyproject 中按项豁免；行长 100，target py311。全角标点合法（RUF001-3 已忽略），注释/文案用中文。
- 提交信息：中文 conventional commits（`fix:`/`feat:`/`docs:`/`chore:`/`ui:` 等）。
