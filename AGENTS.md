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

一键启动 / 打包（Windows）：`start.bat`（构建前端→起服务→开浏览器，:8900，**有 dist 就不重建**）；`dev.bat`（调试入口：杀 8900 旧实例→强制重建前端→起服务，可反复执行即重启，**不带** `--reload`）；`package.bat`（仅含CPU轻量包的默认发行版 → `dist-app/`；GPU/Human SL由用户按需下载）。后端同时静态托管 `frontend/dist/`，单跑后端前需先构建前端。

## 架构要点

- **单实例状态**：`main.py` 模块级 `AppState` 持有全局唯一的 `GameSession`（一次只存在一盘棋）、`EngineManager`、`DownloadManager` 与 WS 客户端集合。命令走 REST `/api/...`，状态经 `/ws` 广播（`state`/`clocks`/`engine`/`download`/`saved`/`review_*`/`error`）。
- **一个引擎进程服务所有需求（双引擎包）**：`settings.PACKAGES` 注册两个可选包——`cpu`（Eigen + 轻量网 lionffen_b6c64，下载约 8MB，**默认**）与 `gpu`（OpenCL + kata1-b18c384nbt，约 100MB，按需下载）。选择持久化于 `backend/engines/choice.json`（**仅显式切换时写入**；缺省按磁盘推导：GPU 包已装全→gpu 否则 cpu，即"全新装机下完 GPU 包"自动切换、显式选择永远保留）。启动顺序 = 选择优先 + 另一已装包兜底（选中 GPU 启动失败回落 CPU 但**不回写**选择，状态里 `selected != active` 供前端提示）。切换走 `POST /api/engines/select`；`restart()`/`select()` 由 `_restart_lock` 串行，且绝不 cancel 在途 `_starting`（会孤儿化半启动子进程）。重启会杀死在途查询（挂起 future 收 `engine.exited`），`_retry_on_wedge` 对 `engine.exited`/`analyze_timeout` 重试一次自愈，select/下载完成钩子另补 `schedule_ai()` 防 AI 回合卡死。其余不变：spawn `katago analysis` 子进程走 stdin/stdout JSON 行协议，AI 行棋、推荐、形势、复盘只是 visits 与采样参数不同，不另起进程；启动时的预热查询（5 visits）提前触发调优并探测卡死实例，首次运行的 OpenCL 调优约 1 分钟，之后亚秒。
- **职责分层**：`rules.py` 纯规则（提子、positional superko、中国规则数子法，全单测）；`game.py` 权威状态机（回合、双方独立计时/读秒、悔棋语义、点目流程；读秒为日本式：每次轮到重新满额计时，落子即作废当前周期，仅回合内超时才扣机会，同回合可连扣；`seed_moves()` 以棋谱前缀开局供复盘接管，`cfg.takeover` 标记试下对局——终局**不存谱**）；`sgf.py` SGF(FF4) 读写 + `records/` 棋谱库；`settings.py` 集中所有预置（难度表、用时、官方下载 URL）。
- **AI 行棋竞态防护**：`schedule_ai()` 的回复在落子前重新校验当前该谁走，悔棋/新对局期间到达的回复直接丢弃。
- **缓存键 = 完整着法序列**（非手数）：`_hint_cache`/`_terr_cache`，悔棋重下同手数也会失效。例外：`_review_hint_cache` 键为 `(file, 手数)`——棋谱不可变，复盘推荐结果永久有效，无需失效。
- **前端**：`main.ts` 路由 → `screens/menu|play|review`；`board.ts` Canvas 渲染器（动画、悬停、推荐环——play 与 review 模式均画、归属热力、死子标记）；`api.ts` REST 封装 + WS 事件总线（自动重连）；`types.ts` 与后端 DTO 一一对应，改协议需两侧同步。
- **渐进推荐**：`hints.py` 的 `HintService` 服务 `GET /api/game/hint/stream` 与 `/api/review/hint/stream?file&moves`，响应为 `application/x-ndjson`（每行一份完整推荐，非WS）；旧 `/hint` JSON端点保留快速单次兼容行为。快搜预算GPU200/CPU80、`maxTime=2`秒，随后深搜GPU8000/CPU1600、`maxTime=25`秒（同引擎最强档10倍预算），通过KataGo `reportDuringSearchEvery=0.25`推送中间结果；深搜重新建树，搜索量未追上已显示结果时不得覆盖。总超时30秒含启动/排队，不调用自愈重试，避免将限时搜索扩成长时间重启等待；超时/错误保留最后结果，无结果则流内`{error:{code,args}}`。新增字段`visits/budget_visits/ai_visits/thinking/stop_reason:visits|time|error|null/recommend_pass`；DTO仍黑方视角，展示层按行棋方换算，pass首选不能误显示次选落点。显示超过最强档预算只依据实际visits，不承诺逐手一定更优。

## 关键约定（易错点）

- **推荐取消/预算/缓存**：前端`api.streamHint`使用AbortController、32秒网络兜底，对局请求按完整局面键去重，复盘按请求序号隔离；关闭/落子/悔棋/导航/离屏取消旧HTTP流，后端取消查询时发KataGo `terminate`（绝不能只移除future）。对局流另每0.25秒校验会话和完整前缀，切换引擎即停止旧流。`HintService`仅缓存正常结束的结果（含正常时间耗尽），LRU上限64；键含引擎实例、对局UUID或棋谱mtime、完整着法、行棋方、尺寸、贴目；超时兜底/错误/断开不入缓存，与旧JSON推荐缓存独立。`settings.ENGINE_MAX_VISITS=100000`统一启动配置和查询上限，查询钳制时扣除`num_threads`以预留并行收尾，普通阶段实际visits可略高于标称预算；这里是应用配置的引擎上限，不是神经网络固有的模型参数。限时等待不能cancel半启动进程：`EngineManager.ensure_started`对创建者也shield启动任务，仅在任务真正结束时清除`_starting`。回归见`tests/test_hints.py`。实现参考本机Just Go日志中的连续`kata-analyze`调用，协议遵循[KataGo Analysis Engine](https://github.com/lightvector/KataGo/blob/v1.18.1/docs/Analysis_Engine.md)，未复制Just Go程序代码。

- **对局弹层的路由约束**：`applyState()` 仍可在后台更新对局数据，但点目/终局弹层仅在 `screen-play.active` 时显示；否则接管结束后返回复盘、或在复盘切换语言时，会被后台对局弹层遮住。

- **复盘往返与异步隔离**：接管快照新增 `review_source: {file, moves} | null`（配置中存 `(file, moves)`），对局页与终局弹层的「返回原复盘」恢复该棋谱的接管手数；`open-review` 事件兼容文件名字符串与 `{file, moves}`。对局 ID 使用 UUID，避免同秒重复接管被当成同一盘。复盘加载用请求序号隔离，推荐同时校验请求序号、文件和手数；对局推荐/形势按对局 ID + 完整着法序列校验，后端响应手数/轮次在等待前捕获，旧查询完成不得写入新对局缓存。接管前先验证棋谱前缀，成功后再取消原 AI；AI/点目异步回复还需校验会话身份。复盘 `reapplyReview()` 必须先恢复棋盘尺寸再重放局面（包括语言切换）。回归测试见 `backend/tests/test_review.py`。

- **子进程行上限陷阱**：KataGo 单行 JSON 响应可达 135KB+（visits 越大越长），`create_subprocess_exec` 必须传 `limit=2**22`——asyncio `StreamReader` 默认 64KB 行上限会让 `readline()` 抛错**静默杀死读取任务**，表象是随机"分析超时"且引擎永久失聪（小预算不易触发，最强档大响应会触发）。查询超时按 visits/后端用 `auto_timeout` 估算，勿回退固定 60s。
- **Windows 下 uvicorn 禁用 `--reload`/`--workers`**：uvicorn 的 `Config.use_subprocess = reload or workers>1`，一旦成立，Windows 强制 `SelectorEventLoop`——asyncio 子进程直接 `NotImplementedError`，KataGo 永远起不来（表象：预热即抛 Task exception was never retrieved）。开发/调试一律单进程无 reload（`dev.bat` 同理），改后端代码就重启。
- **坐标三套体系**：内部 `point = y*19+x`（左上原点、y 向下）；KataGo `Q16`（字母跳 I、从底部数行）；SGF `pd`（a–s 不跳）。转换只在 `katago.py` / `sgf.py` 进出。`ownership` 向量下标即内部坐标（行优先、y 从上）。
- **一律黑方视角（引擎侧已钉死，勿再翻转）**：官方 cfg（v1.13+）含 `reportAnalysisWinratesAs=BLACK`，引擎输出的 winrate/scoreLead/ownership（含 moveInfos）**本身就是黑方视角，与轮谁走无关**；`start()` overrides 已显式钉死该值防未来 cfg 变更。`_normalize` 只做字段映射，**绝不按 to_move 翻转**——曾误当"行棋方视角"翻转过，症状是复盘胜率曲线在 50% 上下锯齿、轮白时形势/死活判断黑白颠倒（`rootInfo.currentPlayer` 可核对行棋方，但视角不依赖它）。冒烟/校验视角要取"棋子本点"归属：2-2 点等常因预期点三三入侵被网络判给对方，符号不定，不能当断言点。复盘缓存 `*.analysis.json` 带 `"perspective":"black"` 标记，缺标记的旧文件在 `record_detail` 一律视为未分析。**翻转只发生在前端展示层一处**：对局页 AI 推荐的胜率（棋盘徽标 `board.drawHints` 用 `toPlay`、侧栏文案 `fetchHint` 用响应 `to_play`）按"点推荐的玩家棋色"（= 推荐局面的行棋方）换算——推荐只在轮到该玩家时显示，故执白看到的是白方胜率；后端 DTO 与其余展示（胜率条/曲线/复盘）仍一律黑方视角。
- **错误协议**：后端不产出任何用户可见文案——异常（`errors.py` 的 `PlayGoError` 系）携带稳定 `code` + `params`，REST detail 与 WS error 事件下发 `{"code","args"}`，前端 `i18n.errText` 查词典组词。新增错误必须两侧同步（`errors.py` ↔ `ERR_KEY` 表 ↔ 两份词典）。
- **i18n**：`frontend/src/i18n.ts` + `locales/zh.ts`（键权威）+ `locales/en.ts`（`Record<keyof typeof zh, string>`，tsc 强制键齐全）。`t()` 只能渲染期调用；语言切换时 `main.ts` 重建三屏并 `reapplyPlay()/reapplyReview()` 重放状态。
- **段级位难度**：`settings.DIFFICULTY_PRESETS` 为20K/15K/10K/5K/1K/1D/3D/5D/7D/9D及 `max`（11档），默认快速练习 `10k`。遵循 [官方 Human SL Guide](https://github.com/lightvector/KataGo/blob/v1.18.1/docs/Analysis_Engine.md#human-sl-analysis-guide)，同一引擎进程在文件存在时附加 `-human-model b18c384nbt-humanv0.bin.gz`（可选下载项 `human-model`，约95MB，不影响CPU/GPU主包安装判定/缺省推导）。人类棋风（`ai_style=human`）请求单独传 `includePolicy=true` + `overrideSettings={humanSLProfile:rank_*, ignorePreRootHistory:false}`，用64 visits主网络辅助停一手，其余按完整 `humanPolicy` 原概率采样（包含所有合法落点，排除pass、负值、非有限值，并重放本地Board过滤超级劫等非法着）；禁止截搜索候选/改温度/缺模型时静默回落最优点。`Analysis.top_is_pass` 保留搜索第一候选的pass，`best_moves`仍为不含pass的推荐列表。`max` 取主网搜索最优着并尊重pass，GPU800/CPU160 visits。推荐/形势/复盘不传human profile，不受等级影响。快速练习（默认`ai_style=rank`）由`strength.py`适配KaTrain Calibrated Rank：完整主网`policy`、1 visit、按等级/合法点比例确定均匀无放回抽样数量后取策略最高者，带关键着与pass前五/收官保护；仅提供15K/10K/5K/1K/1D/3D和max，不外推20K或5D～9D，标为估计棋力且未经本项目实战校准。KaTrain许可附于`docs/licenses/KATRAIN-LICENSE.txt`。19路以外的人类等级明确拒绝。
- **等级标注与协议**：等级是官方人类棋风目标，未经本项目实战校准，尤其高段可能低于目标，不对应中国考段或任一棋站等级（9D不是职业九段）。CPU/GPU共用18块384通道人类网络，主网络分别为b6c64/b18c384nbt，规模与预算不等于固定段位；前端 `difficulty.ts` 统一标注，开局弹窗显示实际主模型/规模/预算，对局侧栏随引擎广播更新。`/api/engines/status`与引擎WS新增 `difficulties:[{id,strategy,visits,cpu_visits,quick}]`、`human_sl:{model,installed,loaded,size_mb}`，`engine`新增 `human_model`。旧 `easy/medium/hard` 仅兼容映射为 `15k/1d/max`（非棋力等价）；新对局请求/快照新增`ai_style:rank|human`，SGF AI名字记录模式；新对局先验证等级/模式组合、人类模式的模型再取消旧AI，失败保持原棋局。新增错误码 `game.bad_difficulty`、`engine.human_model_required|human_policy_missing|human_board_size`。另有`game.quick_rank_unavailable`、`engine.policy_missing`。回归见 `tests/test_difficulty.py`与`tests/test_strength.py`。
- **下载线程回调**：`DownloadManager`在`asyncio.to_thread`执行下载，进度回调必须通过捕获的主循环`loop.call_soon_threadsafe`创建WS广播任务，不能在工作线程直接`ensure_future`。下载完成后重启引擎拾取人类网络；刚落盘但完成钩子未重启的窗口，段级位查询会检查已加载模型并补重启。
- **死活判定**复用 analysis 的 `ownership` 向量（对方地盘上的己方棋子超阈值判死），玩家可点击改判。胜负结果只传 `reason/winner/margin` 枚举数值，文案前端组合。
- **点目两条入口，一个出口**：双停一手（`/api/game/pass`）与对弈中主动点目（`/api/game/score`）都进入 `scoring` 状态并共用 `auto_scoring()` 引擎判定；弹层里"确认结果"走 `/api/game/confirm-score` 终局，"继续对弈"走 `/api/game/resume`（**不撤手数**、时钟重新起算——点目审查时间不计入行棋方；悔棋只在 `playing` 有效，点目阶段先 resume）。易错点：`auto_scoring` 的引擎分析是异步的，判定返回时**必须复查 `status` 仍是 `scoring`**——玩家可能已在等待窗口里点了"继续对弈"，直接 `enter_scoring` 会把已恢复的对局拉回点目。
- **复盘推荐/接管（review 系端点）**：`GET /api/review/hint?file&moves` 对棋谱第 N 手后的局面实时分析（响应同 `/api/game/hint`，`to_play` = 该局面行棋方）；`POST /api/review/takeover {file, moves}` 以棋谱前缀 `seed_moves()` 开一盘 **pvp + 不限时 + 原谱贴目/尺寸/对局者名** 的试下对局（`cfg.takeover=True`，终局 `finalize_game` 跳过存谱）。接管是**新对局**：单实例下会覆盖当前对局（同 `/api/game/new`），前端直接把 POST 响应喂 `onGameEvent` 渲染对局页，不等 WS。前端复盘页推荐开关按 `move_count === curIdx` 丢弃过期响应。所有 `engine.analyze/pick_move` 调用**必须显式传 `size` 与 `komi`**（对局来自 `g.board.size`/`g.cfg.komi`，棋谱来自 `sgf.size`/`sgf.komi`）——默认值是 19 路 + 7.5 贴目，接管小棋盘或非标准贴目时漏传会分析错局面（ownership 长度还会越界）。
- **引擎不入库**：`backend/engines/` 下的 exe/模型/choice.json 均 git 忽略，运行时从官方源按需下载；打包发行时必须随附许可文本（`docs/licenses/`），`package.bat`仅白名单收集`bundled/eigen`和`lionffen_b6c64.txt.gz`，不复制GPU/Human SL模型、日志或打包机的`choice.json`；不因打包机已下载大模型而增大发行包。CPU包缺失时打包明确失败。OpenCL新增模型调优缓存`**/KataGoData/`忽略入库。

## 代码风格

- 后端 ruff `select=["ALL"]` + pyproject 中按项豁免；行长 100，target py311。全角标点合法（RUF001-3 已忽略），注释/文案用中文。
- 提交信息：中文 conventional commits（`fix:`/`feat:`/`docs:`/`chore:`/`ui:` 等）。
