# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

弈 · PlayGo：本地围棋对弈程序。Python FastAPI 后端 + TypeScript/Canvas 前端（无框架），通过子进程调用官方 KataGo analysis 引擎提供 AI 行棋/推荐/形势判断/复盘。UI 与代码注释语言为中文。

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
- **一个引擎进程服务所有需求**：`EngineManager` 优先 OpenCL(GPU)、失败回落 Eigen(CPU)，spawn `katago analysis` 子进程走 stdin/stdout JSON 行协议。AI 行棋、推荐、形势、复盘只是 visits 与采样参数不同，不另起进程。首次 GPU 查询会触发 OpenCL 调优（约 1 分钟，之后亚秒）。
- **职责分层**：`rules.py` 纯规则（提子、positional superko、中国规则数子法，全单测）；`game.py` 权威状态机（回合、双方独立计时/读秒、悔棋语义、pass 与点目流程）；`sgf.py` SGF(FF4) 读写 + `records/` 棋谱库；`settings.py` 集中所有预置（难度表、用时、官方下载 URL）。
- **AI 行棋竞态防护**：`schedule_ai()` 的回复在落子前重新校验当前该谁走，悔棋/新对局期间到达的回复直接丢弃。
- **缓存键 = 完整着法序列**（非手数）：`_hint_cache`/`_terr_cache`，悔棋重下同手数也会失效。
- **前端**：`main.ts` 路由 → `screens/menu|play|review`；`board.ts` Canvas 渲染器（动画、悬停、推荐环、归属热力、死子标记）；`api.ts` REST 封装 + WS 事件总线（自动重连）；`types.ts` 与后端 DTO 一一对应，改协议需两侧同步。

## 关键约定（易错点）

- **坐标三套体系**：内部 `point = y*19+x`（左上原点、y 向下）；KataGo `Q16`（字母跳 I、从底部数行）；SGF `pd`（a–s 不跳）。转换只在 `katago.py` / `sgf.py` 进出。
- **一律黑方视角**：KataGo 报的是"行棋方"视角，`Analysis` 归一化为黑方（胜率 `1−w`、目差/归属 `−v`）。胜率 >0 即黑优。
- **难度实现**：`settings.DIFFICULTY_PRESETS` —— visits 上限 + `prior^p` 采样（easy/medium 走 top-k 采样制造"人味"失误，hard 取最优）；CPU 下 visits 自动降为 `cpu_visits`。
- **死活判定**复用 analysis 的 `ownership` 向量（对方地盘上的己方棋子超阈值判死），玩家可点击改判。
- **引擎不入库**：`backend/engines/` 下的 exe/模型/git 忽略，运行时从官方源按需下载；打包发行时必须随附许可文本（`docs/licenses/`）。

## 代码风格

- 后端 ruff `select=["ALL"]` + pyproject 中按项豁免；行长 100，target py311。全角标点合法（RUF001-3 已忽略），注释/文案用中文。
- 提交信息：中文 conventional commits（`fix:`/`feat:`/`docs:`/`chore:`/`ui:` 等）。
