"""FastAPI 入口：对局 API + WebSocket 实时通道 + 前端静态托管。

用法：uv run uvicorn playgo.main:app --port 8900
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from playgo import settings
from playgo.downloader import DownloadError, DownloadManager, installed
from playgo.errors import err_detail, payload_of
from playgo.game import STATUS_ENDED, STATUS_PLAYING, STATUS_SCORING, GameConfig, GameSession
from playgo.katago import Analysis, EngineError, EngineManager
from playgo.rules import BLACK, EMPTY, WHITE, IllegalMove
from playgo.sgf import list_records, parse_sgf, save_record

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("playgo.main")

app = FastAPI(title="弈 · PlayGo")


class AppState:
    def __init__(self) -> None:
        self.game: GameSession | None = None
        self.engine = EngineManager()
        self.downloads = DownloadManager()
        self.clients: set[WebSocket] = set()
        self.ticker: asyncio.Task | None = None
        self._ai_task: asyncio.Task | None = None
        # 缓存键为完整着法序列（悔棋重下同手数也会失效），值为分析结果
        self._hint_cache: tuple[tuple[tuple[int, int | None], ...], Analysis] | None = None
        self._terr_cache: tuple[tuple[tuple[int, int | None], ...], Analysis] | None = None
        self.review_jobs: dict[str, dict] = {}  # file -> {progress, done, ...}

    async def broadcast(self, event: dict) -> None:
        dead = []
        for ws in self.clients:
            try:
                await ws.send_json(event)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def emit_state(self, *, clocks_only: bool = False) -> None:
        """构造并广播状态事件（fire-and-forget 任务）。"""
        if not self.game:
            return
        snap = self.game.snapshot()
        event = {
            "type": "clocks",
            "clocks": self.game.clock_view(),
            "to_play": snap["to_play"],
            "status": snap["status"],
        }
        if clocks_only:
            asyncio.ensure_future(self.broadcast(event))
            return
        snap["clocks"] = self.game.clock_view()
        asyncio.ensure_future(self.broadcast({"type": "state", "game": snap}))

    # ── AI 行棋编排 ─────────────────────────────────────

    def schedule_ai(self) -> None:
        if self._ai_task and not self._ai_task.done():
            self._ai_task.cancel()
        if not self._ai_needs_move():
            return
        self._ai_task = asyncio.create_task(self._ai_move())

    def _ai_needs_move(self) -> bool:
        g = self.game
        return bool(
            g
            and g.cfg.mode == "ai"
            and g.status == STATUS_PLAYING
            and g.to_play == g.cfg.ai_color()
        )

    async def _ai_move(self) -> None:
        g = self.game
        if not g:
            return
        g.ai_thinking = True
        self.emit_state()
        try:
            moves = [(m.color, m.point) for m in g.moves]
            point, _ana = await self.engine.pick_move(moves, g.to_play, g.cfg.difficulty)
            if not self._ai_needs_move():  # 期间被悔棋/新对局
                return
            if point is None:
                g.pass_move(g.to_play)
            else:
                g.play(g.to_play, point)
        except (EngineError, IllegalMove) as e:
            log.exception("AI 行棋失败: %s", e)
            asyncio.ensure_future(self.broadcast({"type": "error", "error": payload_of(e)}))
        finally:
            if g:
                g.ai_thinking = False
            self.emit_state()
        # 若点目阶段到来（双停一手），触发自动死活判定
        if g and g.status == STATUS_SCORING:
            await self.auto_scoring()

    # ── 终局自动点目 ─────────────────────────────────────

    async def auto_scoring(self) -> None:
        g = self.game
        if not g or g.status != STATUS_SCORING:
            return
        try:
            await self.engine.ensure_started()
            ana = await self.analyze_current(visits=None, territory=True)
            assert ana is not None
            dead: set[int] = set()
            for p, occ in enumerate(g.board.grid):
                if occ == EMPTY:
                    continue
                own = ana.ownership[p]
                if (occ == BLACK and own < -0.25) or (occ == WHITE and own > 0.25):
                    dead.add(p)
            g.enter_scoring(dead)
        except EngineError as e:
            log.exception("自动点目失败: %s", e)
            g.enter_scoring(set())  # 无引擎时手动点目
        self.emit_state()

    async def analyze_current(
        self, *, visits: int | None = None, territory: bool = False
    ) -> Analysis | None:
        """分析当前局面（按完整着法序列缓存）。visits=None 时按用途取默认。"""
        g = self.game
        if not g:
            return None
        engine = await self.engine.ensure_started()
        gpu = engine.is_gpu
        sig = tuple((m.color, m.point) for m in g.moves)
        if territory:
            v = visits or (settings.TERRITORY_VISITS if gpu else settings.TERRITORY_VISITS_CPU)
            cache = self._terr_cache
        else:
            v = visits or (settings.HINT_VISITS if gpu else settings.HINT_VISITS_CPU)
            cache = self._hint_cache
        if cache and cache[0] == sig:
            return cache[1]
        moves = list(sig)
        ana = await self.engine.analyze(moves, to_move=g.to_play, max_visits=v)
        if territory:
            self._terr_cache = (sig, ana)
        else:
            self._hint_cache = (sig, ana)
        return ana


state = AppState()


# ── 请求模型 ─────────────────────────────────────────────


class NewGameReq(BaseModel):
    mode: str = "pvp"  # pvp | ai
    difficulty: str = "medium"
    human_color: int = BLACK
    time_preset: str = "standard"  # standard | blitz | long | free
    komi: float = settings.KOMI
    black_name: str = "Black"
    white_name: str = "White"


class MoveReq(BaseModel):
    point: int


class ResignReq(BaseModel):
    color: int


class DeadStonesReq(BaseModel):
    points: list[int]


class DownloadReq(BaseModel):
    ids: list[str]


class ReviewReq(BaseModel):
    file: str


# ── REST API ─────────────────────────────────────────────


@app.get("/api/state")
async def get_state() -> dict:
    return {
        "game": state.game.snapshot() | {"clocks": state.game.clock_view()} if state.game else None,
        "engine": state.engine.status(),
        "downloading": state.downloads.busy,
    }


@app.post("/api/game/new")
async def new_game(req: NewGameReq) -> dict:
    if state._ai_task and not state._ai_task.done():
        state._ai_task.cancel()
    ts = settings.TimeSettings.presets().get(req.time_preset, settings.TimeSettings())
    ai_color = BLACK + WHITE - req.human_color if req.mode == "ai" else None
    cfg = GameConfig(
        mode=req.mode,
        difficulty=req.difficulty if req.mode == "ai" else "medium",
        human_color=req.human_color,
        komi=req.komi,
        time=ts,
        black_name="KataGo" if ai_color == BLACK else req.black_name,
        white_name="KataGo" if ai_color == WHITE else req.white_name,
    )
    state.game = GameSession(cfg)
    state._hint_cache = None
    state._terr_cache = None
    state.emit_state()
    state.schedule_ai()  # AI 执黑先走
    return state.game.snapshot()


def _game() -> GameSession:
    if not state.game:
        raise HTTPException(400, err_detail("game.not_started"))
    return state.game


@app.post("/api/game/move")
async def play_move(req: MoveReq) -> dict:
    g = _game()
    try:
        g.play(g.to_play, req.point)
    except IllegalMove as e:
        raise HTTPException(400, err_detail(e.code, e.params)) from e
    state.emit_state()
    state.schedule_ai()
    return {"ok": True}


@app.post("/api/game/pass")
async def pass_move() -> dict:
    g = _game()
    try:
        g.pass_move(g.to_play)
    except IllegalMove as e:
        raise HTTPException(400, err_detail(e.code, e.params)) from e
    state.emit_state()
    if g.status == STATUS_SCORING:
        await state.auto_scoring()
    else:
        state.schedule_ai()
    return {"ok": True}


@app.post("/api/game/resign")
async def resign(req: ResignReq) -> dict:
    g = _game()
    if state._ai_task and not state._ai_task.done():
        state._ai_task.cancel()
    g.resign(req.color)
    await finalize_game()
    state.emit_state()
    return {"ok": True, "result": g.result}


@app.post("/api/game/undo")
async def undo() -> dict:
    g = _game()
    if state._ai_task and not state._ai_task.done():
        state._ai_task.cancel()
        g.ai_thinking = False
    n = g.undo()
    state._hint_cache = None
    state._terr_cache = None
    state.emit_state()
    return {"ok": bool(n), "undid": n}


@app.post("/api/game/dead-stones")
async def set_dead_stones(req: DeadStonesReq) -> dict:
    g = _game()
    try:
        g.set_dead_stones(set(req.points))
    except IllegalMove as e:
        raise HTTPException(400, err_detail(e.code, e.params)) from e
    state.emit_state()
    return {"ok": True, "score_preview": g.score_preview}


@app.post("/api/game/confirm-score")
async def confirm_score() -> dict:
    g = _game()
    try:
        g.confirm_score()
    except IllegalMove as e:
        raise HTTPException(400, err_detail(e.code, e.params)) from e
    await finalize_game()
    state.emit_state()
    return {"ok": True, "result": g.result}


async def finalize_game() -> None:
    """终局：保存 SGF 并广播。"""
    g = state.game
    if not g or g.status != STATUS_ENDED:
        return
    path = save_record(g.to_sgf(), settings.RECORDS_DIR)
    asyncio.ensure_future(
        state.broadcast({"type": "saved", "path": str(path.relative_to(settings.PROJECT_DIR))})
    )
    log.info("棋谱已保存: %s", path)


@app.get("/api/game/hint")
async def hint() -> dict:
    g = _game()
    try:
        ana = await state.analyze_current(territory=False)
    except EngineError as e:
        raise HTTPException(503, err_detail(e.code, e.params)) from e
    assert ana is not None
    top = ana.best_moves[:3]
    return {
        "to_play": g.to_play,
        "move_count": len(g.moves),
        "winrate_black": ana.winrate_black,
        "score_lead_black": ana.score_lead_black,
        "moves": [
            {
                "point": m["point"],
                "winrate_black": m["winrate_black"],
                "score_lead_black": m["score_lead_black"],
                "order": m["order"],
            }
            for m in top
        ],
    }


@app.get("/api/game/territory")
async def territory() -> dict:
    g = _game()
    try:
        ana = await state.analyze_current(territory=True)
    except EngineError as e:
        raise HTTPException(503, err_detail(e.code, e.params)) from e
    assert ana is not None
    return {
        "move_count": len(g.moves),
        "winrate_black": ana.winrate_black,
        "score_lead_black": ana.score_lead_black,
        "ownership": ana.ownership,
    }


# ── 棋谱库与复盘 ─────────────────────────────────────────


@app.get("/api/records")
async def records() -> list[dict]:
    return list_records(settings.RECORDS_DIR)


@app.get("/api/records/{file_path:path}")
async def record_detail(file_path: str) -> dict:
    f = settings.RECORDS_DIR / file_path
    if not f.exists() or f.suffix != ".sgf":
        raise HTTPException(404, err_detail("record.not_found"))
    g = parse_sgf(f.read_text(encoding="utf-8"))
    analysis_file = f.with_suffix(".analysis.json")
    analysis = None
    if analysis_file.exists():
        analysis = json.loads(analysis_file.read_text(encoding="utf-8"))
    return {
        "file": file_path,
        "size": g.size,
        "komi": g.komi,
        "black": g.black_name,
        "white": g.white_name,
        "result": g.result,
        "date": g.date,
        "moves": [{"color": c, "point": p} for c, p in g.moves],
        "analysis": analysis,
    }


@app.post("/api/review/analyze")
async def review_analyze(req: ReviewReq) -> dict:
    f = settings.RECORDS_DIR / req.file
    if not f.exists():
        raise HTTPException(404, err_detail("record.not_found"))
    job_key = req.file
    job = state.review_jobs.get(job_key)
    if job and not job.get("done") and job.get("task") and not job["task"].done():
        return {"ok": True, "already_running": True, "progress": job["progress"]}

    sgf = parse_sgf(f.read_text(encoding="utf-8"))

    async def _run() -> None:
        out_positions = []
        try:
            moves = sgf.moves
            total = len(moves) + 1
            hist: list[tuple[int, int | None]] = []
            to_move = BLACK
            for i in range(total):
                ana = await state.engine.analyze(
                    hist, to_move=to_move, max_visits=settings.REVIEW_VISITS
                )
                out_positions.append(
                    {
                        "n": i,
                        "winrate_black": ana.winrate_black,
                        "score_lead_black": ana.score_lead_black,
                        "best": (
                            {
                                "point": ana.best_moves[0]["point"],
                                "winrate_black": ana.best_moves[0]["winrate_black"],
                            }
                            if ana.best_moves
                            else None
                        ),
                        "ownership": [round(v, 3) for v in ana.ownership],
                    }
                )
                if i < len(moves):
                    c, p = moves[i]
                    hist.append((c, p))
                    to_move = BLACK + WHITE - c
                await state.broadcast(
                    {"type": "review_progress", "file": job_key, "done": i + 1, "total": total}
                )
            data = {
                "file": job_key,
                "visits": settings.REVIEW_VISITS,
                "positions": out_positions,
            }
            f.with_suffix(".analysis.json").write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            state.review_jobs[job_key]["done"] = True
            await state.broadcast({"type": "review_done", "file": job_key, "total": total})
        except Exception as e:
            log.exception("复盘分析失败: %s", e)
            state.review_jobs[job_key]["error"] = str(e)
            await state.broadcast({"type": "review_error", "file": job_key, "error": payload_of(e)})

    task = asyncio.create_task(_run())
    state.review_jobs[job_key] = {"task": task, "progress": 0, "done": False}
    return {"ok": True}


# ── 引擎管理 ─────────────────────────────────────────────


@app.get("/api/engines/status")
async def engine_status() -> dict:
    st = state.engine.status()
    st["downloading"] = state.downloads.busy
    st["installed"] = {i: installed(i) for i in ("strong-model", "opencl-exe", "eigen-exe")}
    return st


@app.post("/api/engines/download")
async def engine_download(req: DownloadReq) -> dict:
    if state.downloads.busy:
        raise HTTPException(409, err_detail("download.busy"))

    def on_progress(ev: dict) -> None:
        asyncio.ensure_future(state.broadcast({"type": "download", **ev}))

    try:
        state.downloads.start(req.ids, on_progress)
    except DownloadError as e:
        raise HTTPException(409, err_detail(e.code, e.params)) from e

    # 下载完成后自动切换到更强引擎
    async def _after() -> None:
        with contextlib.suppress(Exception):
            await state.downloads.task
        with contextlib.suppress(Exception):
            await state.engine.restart()
        await state.broadcast({"type": "engine_restarted", "engine": state.engine.status()})

    asyncio.create_task(_after())
    return {"ok": True}


# ── WebSocket ────────────────────────────────────────────


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    state.clients.add(ws)
    try:
        if state.game:
            snap = state.game.snapshot()
            snap["clocks"] = state.game.clock_view()
            await ws.send_json({"type": "state", "game": snap})
        await ws.send_json({"type": "engine", "engine": state.engine.status()})
        while True:
            msg = await ws.receive_json()
            match msg.get("type"):
                case "ping":
                    await ws.send_json({"type": "pong", "t": time.time()})
    except WebSocketDisconnect:
        pass
    finally:
        state.clients.discard(ws)


# ── 生命周期 ─────────────────────────────────────────────


async def _ticker() -> None:
    """每 0.5s 驱动计时；状态变化或每秒广播时钟。"""
    last_bcast = 0.0
    while True:
        await asyncio.sleep(0.5)
        g = state.game
        if not g:
            continue
        changed = g.tick()
        now = time.monotonic()
        if changed:
            if g.status == STATUS_ENDED:
                await finalize_game()
            state.emit_state()
        elif now - last_bcast >= 1.0 and g.status == STATUS_PLAYING:
            last_bcast = now
            state.emit_state(clocks_only=True)


@app.on_event("startup")
async def startup() -> None:
    state.ticker = asyncio.create_task(_ticker())

    async def _warm_engine() -> None:
        try:
            await state.engine.ensure_started()
            # 预热查询：触发模型加载/OpenCL 调优，并探测引擎实例是否卡死
            # （卡死会被 EngineManager 自动重启重试，避免对局中才暴露）
            await state.engine.analyze([], to_move=BLACK, max_visits=5, timeout=300)
            await state.broadcast({"type": "engine", "engine": state.engine.status()})
        except EngineError as e:
            log.warning("引擎不可用: %s", e)
            await state.broadcast({"type": "engine", "engine": state.engine.status()})

    asyncio.create_task(_warm_engine())


@app.on_event("shutdown")
async def shutdown() -> None:
    if state.ticker:
        state.ticker.cancel()
    if state._ai_task and not state._ai_task.done():
        state._ai_task.cancel()
    await state.engine.shutdown()


# ── 前端静态托管 ─────────────────────────────────────────


if settings.FRONTEND_DIST.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=settings.FRONTEND_DIST / "assets"),
        name="assets",
    )

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(settings.FRONTEND_DIST / "index.html")


@app.exception_handler(HTTPException)
async def http_exc_handler(_req, exc: HTTPException) -> JSONResponse:
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
