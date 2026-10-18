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
- **渐进推荐**：`hints.py` 的 `HintService` 服务 `GET /api/game/hint/stream` 与 `/api/review/hint/stream?file&moves`，响应为 `application/x-ndjson`（每行完整推荐，非WS）；旧 `/hint` JSON端点保留GPU200/CPU80快速单次兼容行为。推荐流仅发一次搜索，CPU/GPU均以`ENGINE_MAX_VISITS=100000`为上限，通过`reportDuringSearchEvery=0.25`逐步报告，沿同一棵树持续深化，不重复快搜/深搜。`timeout=None`禁用Python查询总时限，`maxTime=1e20`避免cfg时间限制截断；上层严格监测进展：首批最多30秒（含启动/排队），之后每次visits增长续期15秒，相同/倒退/零visits报告不得续期，正常搜索可持续超过30秒。不走自愈重试；无进展/错误保留最后结果，无结果则流内`{error:{code,args}}`。DTO字段`visits/budget_visits/ai_visits/thinking/stop_reason:visits|idle|error|null/recommend_pass`；黑方视角保持不变，展示按行棋方换算，pass首选不得显示次选落点。超过最强档预算依据实际visits，不承诺逐手更优。

## 关键约定（易错点）

- **推荐数量与首选视觉**：`settings.HINT_MOVE_COUNT=5`统一对局/复盘的JSON和NDJSON推荐上限（不足不凑数），与`frontend/src/hint-style.ts`的`MAX_HINTS=5`同步。五个棋盘选点同尺寸、浅字`#f3fff7`，胜率直接居中；不显示字母、序号、外置徽标。`hintBackground()`按行棋方胜率相对当前候选最高值的绝对差映射绿色透明度：胜率越低越浅、越透明，差≤3pp用不透明松绿`#14553f`，差≥25pp用同色25%不透明度，中间alpha线性插值；木纹/网格可透出，文字加松绿2px细描边保持可读；不对微小差距做全范围归一化，颜色不表示搜索深度。`isPreferredHint()`仅以引擎`order===0`识别综合首选（不是最高胜率或数组第一项），加`#efd48b`金色双环；首选不必是最浅的点，双环在圆内且不闪烁，随报告更新。停一手首选沿用`recommend_pass`优先逻辑，侧栏显示「首选：停一手」，不画候选或误标剩余落点。对局/复盘侧栏明确标注首选和黑/白方胜率；悬停提示区分「引擎首选/其他推荐」并显示完整百分比，使用双语词典，按行棋方翻转胜率。Canvas用`textAlign=center/textBaseline=middle`，首选字体缩放时避开内环；cell<28时简写整数，悬停幽灵子不得遮盖数值或覆盖首选金环。`ctx.save/restore`隔离样式。回归覆盖三个API最多5个、不足不补齐；浏览器检查低胜率更浅且alpha更低、文字描边、小差距同色、执白色阶反向、综合首选与最高胜率不同、首选移动、对局/复盘、停一手、窄窗口及中英文悬停。

- **推荐开启反馈与在途共享**：对局按钮用`aria-pressed`反映开关，开启后同步显示计算中或等待玩家回合；`hint-sec`的`aria-busy`跟随请求/搜索状态，错误、空候选和语言重建不得停留在“开启下方按钮后显示”。同一完整推荐缓存键的HTTP请求共享`_running`中的一项`_HintSearch`，新订阅者立即取得已有进度，每个订阅者独立容量1队列接收广播，避免单GPU长搜索重复排队。仅最后一个订阅者断开才停止共享查询；棋局变化/引擎切换仍主动取消整项搜索。测试覆盖共享结果、断开隔离和全局取消；浏览器验证延迟首批、失败、语言切换与连续开关。

- **推荐取消/预算/缓存**：前端`api.streamHint`使用AbortController，首批32秒网络兜底，之后仅在visits增长时续期17秒，无固定总时限；对局请求按完整局面键去重，复盘按请求序号隔离。关闭/导航/离屏取消旧HTTP流。`HintService`登记在途搜索和局面校验函数；后端在成功落子（含AI）、停一手、悔棋、新对局、接管、点目、认输、超时等变更之后`await cancel_stale()`，先取消旧任务并写出KataGo `terminate`再广播/调度，绝不依赖客户端断开；不等待引擎终止确认，迟到回复仍按会话与完整前缀隔离。切换/重启/退出先`cancel_all()`，流另每0.25秒校验局面和引擎实例。仅正常到达visits上限的结果进入LRU缓存（最多64个），键含引擎实例、对局UUID或棋谱mtime、完整着法、行棋方、尺寸、贴目；中断/无进展/错误不入缓存，与旧JSON缓存独立。`ENGINE_MAX_VISITS`统一启动与查询上限，查询扣除`num_threads`预留并行收尾；这是应用配置上限，不是模型固有参数。`ensure_started`对创建者也shield启动任务，仅在真正结束后清除`_starting`，防取消等待者孤儿化半启动进程。回归见`tests/test_hints.py`。参考本机Just Go日志中的连续`kata-analyze`，协议遵循[KataGo Analysis Engine](https://github.com/lightvector/KataGo/blob/v1.18.1/docs/Analysis_Engine.md)，未复制Just Go代码。

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

- **自动整谱复盘与实时推荐独立**：进入棋谱时前端自动 `POST /api/review/analyze {file,force:false}`，手动按钮传`force:true`可重算/重试。后端先登记同谱任务再异步启动引擎，重复请求返回`already_running/progress/analysis`恢复完整进展。`settings.review_visits(is_gpu=...)`直接读取最高难度预算（GPU800/CPU160），从空盘到终局逐个分析N+1个棋谱前缀；整轮绑定同一引擎实例，切换/退出则报错，不混用模型。`review_progress`新增`visits/position`，每局面完成先更新任务progress再广播，前端逐点补曲线并显示进度/预算；部分曲线横轴仍按整谱总手数固定，尚未分析的手数不可假冒最后一个已分析点。完成后原子替换`*.analysis.json`，`review_done`触发重载；失败保留旧完整文件，按钮解除禁用可重试。缓存除`perspective:black`外记录`model/backend/record_mtime_ns/visits`，只有同模型/后端/棋谱mtime、完整N+1点且预算足够才复用；旧64visits及缺元数据文件自动升级，低预算旧曲线可暂时展示。`review.ts:drawCurve()`横轴为`position.n`，纵轴固定黑方胜率（上100%/中50%/下0%），相邻点直线连接、不平滑、不按行棋方翻转。分析允许后台继续，完成/失败后释放任务内局面数据；当前局面的连续推荐不会回写整谱曲线。后端回归见`tests/test_review.py`（CPU/GPU预算、前缀/贴目/尺寸、增量进度、缓存升级/强制重算、同谱去重、切换/失败不覆盖）。

- **复盘曲线尺寸与点击坐标**：`#rv-curve`必须用CSS约束到侧栏实际宽度，不能让536px固有宽度被`.panel{overflow:hidden}`截掉右半段。`drawCurve()`按`getBoundingClientRect()`的CSS尺寸作图，像素缓冲按DPR放大并`setTransform`，点击换算同样使用CSS像素和8px边距；`ResizeObserver`在尺寸变化后重绘，语言重建前断开旧observer。曲线区不收缩，逐手分析区`min-height:0;overflow-y:auto`，横轴始终按整谱总手数，显示起点/当前/末手标签。棋谱库面板禁止flex收缩，短窗口通过外层滚动保留导入按钮。浏览器回归使用420手、1365/1024/900px窗口、DPR2，确认末端坐标及首尾点击。

- **本地SGF导入**：棋谱库与复盘页复用`record-import.ts`，`POST /api/records/import?filename=...`以原始文件字节提交（`application/x-go-sgf`，不使用multipart），返回`{file}`后触发`open-review`并自动分析。后端按`RECORD_IMPORT_MAX_BYTES=2MiB`逐块限流，校验`.sgf`后缀、完整树结构、2～19路尺寸/有限贴目和主变合法性，成功前不落盘；不修改当前对局、不主动调度AI。新文件保存在`records/imported/<UUID>.sgf`，用户文件名不参与路径，重复导入不覆盖。`sgf.py`按属性/转义/树结构解析第一盘第一主变，保留评论与其他分支，支持空串及`tt`停一手；拒绝`GM!=1`、主变`AB/AW/AE/PL`与非零`HA`，不能静默丢弃摆子。解码先读取真实根CA，缺省UTF-8-sig失败再GB18030，保存时只更新真实CA为UTF-8，不替换评论内文本。外部姓名/日期/结果在HTML模板中经`escapeHtml`，姓名字段优先`textContent`。错误码`record.bad_extension|too_large|invalid_sgf|unsupported_sgf`与`RecordError`、`ERR_KEY`及中英文词典同步。测试见`tests/test_record_import.py`，覆盖编码、BOM、注释伪着法、转义、分支、路径隔离、同名导入、非法文件零落盘及跨块超限。

## 代码风格

- 后端 ruff `select=["ALL"]` + pyproject 中按项豁免；行长 100，target py311。全角标点合法（RUF001-3 已忽略），注释/文案用中文。
- 提交信息：中文 conventional commits（`fix:`/`feat:`/`docs:`/`chore:`/`ui:` 等）。
