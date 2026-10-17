# AGENTS.md

This file provides guidance to AI coding agents (Claude Code, Codex, Gemini CLI, … — any tool that reads AGENTS.md) when working with code in this repository.

弈 · PlayGo：本地围棋对弈程序。Python FastAPI 后端 + TypeScript/Canvas 前端（无框架），通过子进程调用官方 KataGo analysis 引擎提供 AI 行棋/推荐/形势判断/复盘。UI 中英双语（`frontend/src/locales/`，跟随浏览器，顶栏可切换），代码注释语言为中文。

## 文档同步（强制）

每完成一项完整任务（修复一个 bug、新增一个需求、行为变更等），**必须同步更新 `AGENTS.md` 与两份 README（`README.md` / `README.zh-CN.md`），随本任务的改动一并交付**：架构/接口/协议/命令/易错点的变化写进 `AGENTS.md`，用户可见的功能与用法变化写进两份 README；文档与代码不一致视作任务未完成。本仓库只维护 `AGENTS.md`，不设 `CLAUDE.md`（Claude Code 2.1.277+ 直接读取 `AGENTS.md`，勿再创建）。

## 常用命令

后端（在 `backend/` 下，uv 管理）：

```bash
uv sync                          # 安装依赖（开发工具加 --group dev：pytest/ruff/ty）
uv run uvicorn playgo.main:app --port 8900   # 开发模式（勿加 --reload，见下方易错约定）
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

一键启动 / 打包（Windows）：`start.bat`（构建前端→起服务→开浏览器，:8900，**有 dist 就不重建**）；`dev.bat`（调试入口：杀 8900 旧实例→强制重建前端→起服务，可反复执行即重启，**不带** `--reload`）；`package.bat`（含引擎的离线发行版 → `dist-app/`）。后端同时静态托管 `frontend/dist/`，单跑后端前需先构建前端。

## 架构要点

- **单实例状态**：`main.py` 模块级 `AppState` 持有全局唯一的 `GameSession`（一次只存在一盘棋）、`EngineManager`、`DownloadManager` 与 WS 客户端集合。命令走 REST `/api/...`，状态经 `/ws` 广播（`state`/`clocks`/`engine`/`download`/`saved`/`review_*`/`error`）。
- **一个引擎进程服务所有需求（双引擎包）**：`settings.PACKAGES` 注册两个可选包——`cpu`（Eigen + 轻量网 lionffen_b6c64，下载约 8MB，**默认**）与 `gpu`（OpenCL + kata1-b18c384nbt，约 100MB，按需下载）。选择持久化于 `backend/engines/choice.json`（**仅显式切换时写入**；缺省按磁盘推导：GPU 包已装全→gpu 否则 cpu，即"全新装机下完 GPU 包"自动切换、显式选择永远保留）。启动顺序 = 选择优先 + 另一已装包兜底（选中 GPU 启动失败回落 CPU 但**不回写**选择，状态里 `selected != active` 供前端提示）。切换走 `POST /api/engines/select`；`restart()`/`select()` 由 `_restart_lock` 串行，且绝不 cancel 在途 `_starting`（会孤儿化半启动子进程）。重启会杀死在途查询（挂起 future 收 `engine.exited`），`_retry_on_wedge` 对 `engine.exited`/`analyze_timeout` 重试一次自愈，select/下载完成钩子另补 `schedule_ai()` 防 AI 回合卡死。其余不变：spawn `katago analysis` 子进程走 stdin/stdout JSON 行协议，AI 行棋、推荐、形势、复盘只是 visits 与采样参数不同，不另起进程；启动时的预热查询（5 visits）提前触发调优并探测卡死实例，首次运行的 OpenCL 调优约 1 分钟，之后亚秒。
- **职责分层**：`rules.py` 纯规则（提子、positional superko、中国规则数子法，全单测）；`game.py` 权威状态机（回合、双方独立计时/读秒、悔棋语义、点目流程；读秒为日本式：每次轮到重新满额计时，落子即作废当前周期，仅回合内超时才扣机会，同回合可连扣；`seed_moves()` 以棋谱前缀开局供复盘接管，`cfg.takeover` 标记试下对局——终局**不存谱**）；`sgf.py` SGF(FF4) 读写 + `records/` 棋谱库；`settings.py` 集中所有预置（难度表、用时、官方下载 URL）。
- **AI 行棋竞态防护**：`schedule_ai()` 的回复在落子前重新校验当前该谁走，悔棋/新对局期间到达的回复直接丢弃。
- **缓存键 = 完整着法序列**（非手数）：`_hint_cache`/`_terr_cache`，悔棋重下同手数也会失效。例外：`_review_hint_cache` 键为 `(file, 手数)`——棋谱不可变，复盘推荐结果永久有效，无需失效。
- **前端**：`main.ts` 路由 → `screens/menu|play|review`；`board.ts` Canvas 渲染器（动画、悬停、推荐环——play 与 review 模式均画、归属热力、死子标记）；`api.ts` REST 封装 + WS 事件总线（自动重连）；`types.ts` 与后端 DTO 一一对应，改协议需两侧同步。

## 关键约定（易错点）

- **子进程行上限陷阱**：KataGo 单行 JSON 响应可达 135KB+（visits 越大越长），`create_subprocess_exec` 必须传 `limit=2**22`——asyncio `StreamReader` 默认 64KB 行上限会让 `readline()` 抛错**静默杀死读取任务**，表象是随机"分析超时"且引擎永久失聪（简单/中等档响应小不触发，困难档必中）。查询超时按 visits/后端用 `auto_timeout` 估算，勿回退固定 60s。
- **Windows 下 uvicorn 禁用 `--reload`/`--workers`**：uvicorn 的 `Config.use_subprocess = reload or workers>1`，一旦成立，Windows 强制 `SelectorEventLoop`——asyncio 子进程直接 `NotImplementedError`，KataGo 永远起不来（表象：预热即抛 Task exception was never retrieved）。开发/调试一律单进程无 reload（`dev.bat` 同理），改后端代码就重启。
- **坐标三套体系**：内部 `point = y*19+x`（左上原点、y 向下）；KataGo `Q16`（字母跳 I、从底部数行）；SGF `pd`（a–s 不跳）。转换只在 `katago.py` / `sgf.py` 进出。`ownership` 向量下标即内部坐标（行优先、y 从上）。
- **一律黑方视角（引擎侧已钉死，勿再翻转）**：官方 cfg（v1.13+）含 `reportAnalysisWinratesAs=BLACK`，引擎输出的 winrate/scoreLead/ownership（含 moveInfos）**本身就是黑方视角，与轮谁走无关**；`start()` overrides 已显式钉死该值防未来 cfg 变更。`_normalize` 只做字段映射，**绝不按 to_move 翻转**——曾误当"行棋方视角"翻转过，症状是复盘胜率曲线在 50% 上下锯齿、轮白时形势/死活判断黑白颠倒（`rootInfo.currentPlayer` 可核对行棋方，但视角不依赖它）。冒烟/校验视角要取"棋子本点"归属：2-2 点等常因预期点三三入侵被网络判给对方，符号不定，不能当断言点。复盘缓存 `*.analysis.json` 带 `"perspective":"black"` 标记，缺标记的旧文件在 `record_detail` 一律视为未分析。**翻转只发生在前端展示层一处**：对局页 AI 推荐的胜率（棋盘徽标 `board.drawHints` 用 `toPlay`、侧栏文案 `fetchHint` 用响应 `to_play`）按"点推荐的玩家棋色"（= 推荐局面的行棋方）换算——推荐只在轮到该玩家时显示，故执白看到的是白方胜率；后端 DTO 与其余展示（胜率条/曲线/复盘）仍一律黑方视角。
- **错误协议**：后端不产出任何用户可见文案——异常（`errors.py` 的 `PlayGoError` 系）携带稳定 `code` + `params`，REST detail 与 WS error 事件下发 `{"code","args"}`，前端 `i18n.errText` 查词典组词。新增错误必须两侧同步（`errors.py` ↔ `ERR_KEY` 表 ↔ 两份词典）。
- **i18n**：`frontend/src/i18n.ts` + `locales/zh.ts`（键权威）+ `locales/en.ts`（`Record<keyof typeof zh, string>`，tsc 强制键齐全）。`t()` 只能渲染期调用；语言切换时 `main.ts` 重建三屏并 `reapplyPlay()/reapplyReview()` 重放状态。
- **难度实现**：`settings.DIFFICULTY_PRESETS` —— visits 上限 + `prior^p` 采样（easy/medium 走 top-k 采样制造"人味"失误，hard 取最优）；CPU 下 visits 自动降为 `cpu_visits`。难度显示文案在前端词典（`diff.*`），预设表只存参数。
- **死活判定**复用 analysis 的 `ownership` 向量（对方地盘上的己方棋子超阈值判死），玩家可点击改判。胜负结果只传 `reason/winner/margin` 枚举数值，文案前端组合。
- **点目两条入口，一个出口**：双停一手（`/api/game/pass`）与对弈中主动点目（`/api/game/score`）都进入 `scoring` 状态并共用 `auto_scoring()` 引擎判定；弹层里"确认结果"走 `/api/game/confirm-score` 终局，"继续对弈"走 `/api/game/resume`（**不撤手数**、时钟重新起算——点目审查时间不计入行棋方；悔棋只在 `playing` 有效，点目阶段先 resume）。易错点：`auto_scoring` 的引擎分析是异步的，判定返回时**必须复查 `status` 仍是 `scoring`**——玩家可能已在等待窗口里点了"继续对弈"，直接 `enter_scoring` 会把已恢复的对局拉回点目。
- **复盘推荐/接管（review 系端点）**：`GET /api/review/hint?file&moves` 对棋谱第 N 手后的局面实时分析（响应同 `/api/game/hint`，`to_play` = 该局面行棋方）；`POST /api/review/takeover {file, moves}` 以棋谱前缀 `seed_moves()` 开一盘 **pvp + 不限时 + 原谱贴目/尺寸/对局者名** 的试下对局（`cfg.takeover=True`，终局 `finalize_game` 跳过存谱）。接管是**新对局**：单实例下会覆盖当前对局（同 `/api/game/new`），前端直接把 POST 响应喂 `onGameEvent` 渲染对局页，不等 WS。前端复盘页推荐开关按 `move_count === curIdx` 丢弃过期响应。所有 `engine.analyze/pick_move` 调用**必须显式传 `size` 与 `komi`**（对局来自 `g.board.size`/`g.cfg.komi`，棋谱来自 `sgf.size`/`sgf.komi`）——默认值是 19 路 + 7.5 贴目，接管小棋盘或非标准贴目时漏传会分析错局面（ownership 长度还会越界）。
- **引擎不入库**：`backend/engines/` 下的 exe/模型/choice.json 均 git 忽略，运行时从官方源按需下载；打包发行时必须随附许可文本（`docs/licenses/`），且 `package.bat` 会剔除打包机的 `choice.json`（发行版按用户自己已装的包推导缺省）。

## 代码风格

- 后端 ruff `select=["ALL"]` + pyproject 中按项豁免；行长 100，target py311。全角标点合法（RUF001-3 已忽略），注释/文案用中文。
- 提交信息：中文 conventional commits（`fix:`/`feat:`/`docs:`/`chore:`/`ui:` 等）。
