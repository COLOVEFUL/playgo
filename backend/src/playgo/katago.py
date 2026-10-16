"""KataGo Analysis Engine 子进程封装。

一个引擎进程服务所有需求：AI 行棋（按难度控制 visits 与采样）、
AI 推荐（top-N 候选）、形势判断（ownership 热力）、复盘批量分析。
坐标转换：内部 x 从左、y 从上；KataGo 用字母（跳 I）+ 从底部数的行号。
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from playgo import settings
from playgo.errors import PlayGoError
from playgo.rules import BLACK

if TYPE_CHECKING:
    from pathlib import Path

log = logging.getLogger("playgo.katago")

KATA_LETTERS = "ABCDEFGHJKLMNOPQRST"  # 跳过 I


def to_kata_coords(point: int, size: int = 19) -> str:
    x, y = point % size, point // size
    return f"{KATA_LETTERS[x]}{size - y}"


def from_kata_coords(s: str, size: int = 19) -> int:
    x = KATA_LETTERS.index(s[0].upper())
    y = size - int(s[1:])
    return y * size + x


@dataclass
class Analysis:
    """一次局面分析的归一化结果（一律“黑方视角”：胜率>0 为黑优）。"""

    to_move: int  # 分析局面下该谁走
    winrate_black: float  # 0..1
    score_lead_black: float  # 目差（黑领先为正）
    ownership: list[float]  # +黑 -白，len=size*size
    best_moves: list[dict] = field(default_factory=list)
    # 每项: {point, order, prior, winrate_black, score_lead_black, pv:[(color,point)]}
    visits: int = 0


class EngineError(PlayGoError):
    """引擎错误。code 供前端本地化文案。"""


class KataGoEngine:
    """单进程 analysis 引擎。所有方法线程安全（内部 asyncio 锁）。"""

    def __init__(self, exe: Path, model: Path, backend: str) -> None:
        self.exe = exe
        self.model = model
        self.backend = backend  # "eigen" | "opencl"
        self.proc: asyncio.subprocess.Process | None = None
        self._pending: dict[str, asyncio.Future[dict]] = {}
        self._reader: asyncio.Task | None = None
        self._watcher: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self.ready = False
        self.failed_reason: str | None = None
        self._any_response_seen = False
        self._ready_line_seen = False
        self._stderr_tail: list[str] = []
        # Eigen CPU 减线程，OpenCL 按 GPU 线程
        self.num_threads = 2 if backend == "eigen" else 12

    @property
    def is_gpu(self) -> bool:
        return self.backend == "opencl"

    def describe(self) -> dict:
        return {
            "exe": str(self.exe),
            "model": self.model.name,
            "backend": self.backend,
            "gpu": self.is_gpu,
        }

    async def start(self) -> None:
        """启动并等待就绪。失败抛 EngineError。"""
        async with self._lock:
            if self.ready:
                return
            cfg = self.exe.parent / "analysis_example.cfg"
            overrides = ",".join(
                [
                    f"logDir={settings.LOGS_DIR.as_posix()}",
                    "logToStderr=true",
                    "logToStdout=false",
                    "logAllGTPCommunication=false",
                    "allowResignation=false",
                    f"numAnalysisThreads={1 if self.is_gpu else 2}",
                    f"numSearchThreadsPerAnalysisThread={self.num_threads}",
                    "maxVisits=100000",
                ]
            )
            cmd = [
                str(self.exe),
                "analysis",
                "-config",
                str(cfg),
                "-model",
                str(self.model),
                "-override-config",
                overrides,
            ]
            log.info("启动引擎: %s", " ".join(cmd))
            try:
                self.proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
            except OSError as e:
                msg = f"引擎启动失败: {e}"
                self.failed_reason = msg
                raise EngineError(msg, code="engine.start_failed", params={"detail": str(e)}) from e

            self._reader = asyncio.create_task(self._read_stdout())
            self._watcher = asyncio.create_task(self._read_stderr())

            try:
                await asyncio.wait_for(self._wait_ready(), timeout=120)
            except TimeoutError:
                await self.stop()
                msg = "引擎就绪超时（120s）"
                self.failed_reason = msg
                raise EngineError(
                    msg, code="engine.ready_timeout", params={"seconds": 120}
                ) from None
            self.ready = True
            log.info("引擎就绪: %s", self.describe())

    async def _wait_ready(self) -> None:
        """等待就绪：stderr 出现就绪标记，或 stdout 收到任何 JSON。"""
        while self.proc and self.proc.returncode is None:
            if self._ready_line_seen or self._any_response_seen:
                return
            await asyncio.sleep(0.1)
        if self.proc and self.proc.returncode is not None:
            tail = "\n".join(self._stderr_tail)
            msg = f"引擎进程退出(code={self.proc.returncode}): {tail[-800:]}"
            self.failed_reason = msg
            raise EngineError(
                msg,
                code="engine.exited",
                params={"code": self.proc.returncode, "tail": tail[-800:]},
            )

    _any_response_seen = False
    _ready_line_seen = False

    async def _read_stdout(self) -> None:
        assert self.proc
        assert self.proc.stdout
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue  # 表头等非 JSON 行
            self._any_response_seen = True
            rid = data.get("id")
            fut = self._pending.get(rid)
            if fut and not fut.done():
                if data.get("isDuringSearch"):
                    continue  # 只要最终结果
                if "warning" in data and "rootInfo" not in data:
                    log.warning("引擎告警: %s", data)
                    continue  # 告警行可能带查询 id，不能当结果
                fut.set_result(data)
        # 进程结束：唤醒所有等待者
        for fut in self._pending.values():
            if not fut.done():
                msg = "引擎进程已退出"
                fut.set_exception(EngineError(msg, code="engine.exited"))

    async def _read_stderr(self) -> None:
        assert self.proc
        assert self.proc.stderr
        while True:
            line = await self.proc.stderr.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if text:
                self._stderr_tail.append(text)
                del self._stderr_tail[:-30]  # 只留末尾 30 行供排错
                if "Started, ready to begin handling requests" in text:
                    self._ready_line_seen = True
                log.debug("[katago] %s", text)

    async def stop(self) -> None:
        self.ready = False
        for t in (self._reader, self._watcher):
            if t:
                t.cancel()
        if self.proc and self.proc.returncode is None:
            self.proc.kill()
            await self.proc.wait()
        self.proc = None

    async def analyze(
        self,
        moves: list[tuple[int, int | None]],
        *,
        to_move: int,
        max_visits: int,
        size: int = 19,
        komi: float = settings.KOMI,
        timeout: float = 60.0,
    ) -> Analysis:
        """分析当前局面。moves 为已落子的历史（不含即将走的一手）。"""
        if not self.ready:
            msg = "引擎未就绪"
            raise EngineError(msg, code="engine.not_ready")
        rid = uuid.uuid4().hex[:12]
        payload = {
            "id": rid,
            # 停一手必须以 "pass" 传给引擎：丢掉会破坏黑白轮转，分析出错误局面
            "moves": [
                ["B" if c == BLACK else "W", to_kata_coords(p, size) if p is not None else "pass"]
                for c, p in moves
            ],
            "analyzeTurns": [len(moves)],
            "maxVisits": max_visits,
            "includeOwnership": True,
            "boardXSize": size,
            "boardYSize": size,
            "rules": "chinese",
            "komi": komi,
        }
        fut: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        try:
            assert self.proc
            assert self.proc.stdin
            self.proc.stdin.write((json.dumps(payload) + "\n").encode())
            await self.proc.stdin.drain()
            data = await asyncio.wait_for(fut, timeout)
        except TimeoutError:
            msg = f"分析超时({timeout}s)"
            raise EngineError(
                msg, code="engine.analyze_timeout", params={"timeout": timeout}
            ) from None
        finally:
            self._pending.pop(rid, None)

        return self._normalize(data, to_move, size)

    def _normalize(self, data: dict, to_move: int, size: int) -> Analysis:
        """KataGo 输出以"当前行棋方"为视角；统一转换为黑方视角。

        winrate 是 [0,1] 概率，翻转用 1-w；scoreLead/ownership 是对称量，翻转取负。
        """
        root = data.get("rootInfo", {})

        def wr_black(w: float) -> float:
            return w if to_move == BLACK else 1.0 - w

        def lead_black(v: float) -> float:
            return v if to_move == BLACK else -v

        ownership = [lead_black(v) for v in data.get("ownership", [0.0] * (size * size))]
        best: list[dict] = []
        for m in sorted(data.get("moveInfos", []), key=lambda m: m.get("order", 99)):
            mv = m.get("move", "")
            if not mv or mv.lower() == "pass":
                continue
            try:
                point = from_kata_coords(mv, size)
            except (ValueError, IndexError):
                continue
            best.append(
                {
                    "point": point,
                    "order": m.get("order", 99),
                    "prior": m.get("prior", 0.0),
                    "winrate_black": wr_black(m["winrate"]),
                    "score_lead_black": lead_black(m["scoreLead"]),
                    "pv": m.get("pvVisits", None) or [],
                }
            )
        return Analysis(
            to_move=to_move,
            winrate_black=wr_black(root.get("winrate", 0.5)),
            score_lead_black=lead_black(root.get("scoreLead", 0.0)),
            ownership=ownership,
            best_moves=best,
            visits=root.get("visits", 0),
        )

    # ── AI 行棋（按难度） ────────────────────────────────

    async def pick_move(
        self,
        moves: list[tuple[int, int | None]],
        to_move: int,
        difficulty: str,
        *,
        size: int = 19,
    ) -> tuple[int | None, Analysis]:
        """按难度选点。返回 (落点(None=停一手), 分析结果)。"""
        preset = settings.DIFFICULTY_PRESETS[difficulty]
        visits = preset["cpu_visits"] if not self.is_gpu else preset["visits"]
        ana = await self.analyze(
            moves, to_move=to_move, max_visits=visits, size=size
        )
        point = self._choose(ana, preset)
        return point, ana

    def _choose(self, ana: Analysis, preset: dict) -> int | None:
        if not ana.best_moves:
            return None  # 无棋可走 → 停一手
        pick_mode = preset.get("pick", "best")
        if pick_mode == "best":
            return ana.best_moves[0]["point"]
        # 采样：前 sample_top 候选，权重 prior^pow（平化先验，制造人类式失误）
        top = ana.best_moves[: preset.get("sample_top", 5)]
        pw = preset.get("prior_pow", 1.0)
        weights = [max(m["prior"], 1e-4) ** pw for m in top]
        chosen = random.choices(top, weights=weights, k=1)[0]
        return chosen["point"]


class EngineManager:
    """选择并持有当前最佳可用引擎；负责按需下载的启动探测。"""

    def __init__(self) -> None:
        self.engine: KataGoEngine | None = None
        self._starting: asyncio.Task | None = None

    def _candidates(self) -> list[KataGoEngine]:
        """按优先级列出可用引擎（文件存在即算）。"""
        cands: list[KataGoEngine] = []
        opencl = settings.DOWNLOADED_DIR / "opencl" / "katago.exe"
        model = settings.DOWNLOADED_DIR / settings.STRONG_MODEL_NAME
        if opencl.exists() and model.exists():
            cands.append(KataGoEngine(opencl, model, "opencl"))
        eigen = settings.BUNDLED_DIR / "eigen" / "katago.exe"
        if eigen.exists() and model.exists():
            cands.append(KataGoEngine(eigen, model, "eigen"))
        return cands

    def missing_for_download(self) -> list[dict]:
        """列出可下载补齐项（label 由前端按 id 本地化）。"""
        need = []
        model = settings.DOWNLOADED_DIR / settings.STRONG_MODEL_NAME
        opencl = settings.DOWNLOADED_DIR / "opencl" / "katago.exe"
        eigen = settings.BUNDLED_DIR / "eigen" / "katago.exe"
        if not model.exists():
            need.append({"id": "strong-model", "size_mb": 94})
        if not opencl.exists():
            need.append({"id": "opencl-exe", "size_mb": 6})
        if not eigen.exists():
            need.append({"id": "eigen-exe", "size_mb": 6})
        return need

    def status(self) -> dict:
        return {
            "available": self.engine.ready if self.engine else False,
            "engine": self.engine.describe() if self.engine else None,
            "missing": self.missing_for_download(),
        }

    async def ensure_started(self) -> KataGoEngine:
        """取当前最佳引擎并启动（幂等）。无任何引擎时抛 EngineError。"""
        if self.engine and self.engine.ready:
            return self.engine
        if self._starting:
            return await asyncio.shield(self._starting)
        cands = self._candidates()
        if not cands:
            msg = "未找到可用引擎，请先下载"
            raise EngineError(msg, code="engine.not_installed")

        async def _start() -> KataGoEngine:
            last_err: Exception | None = None
            for cand in cands:
                try:
                    await cand.start()
                    self.engine = cand
                    return cand
                except EngineError as e:  # OpenCL 失败则回退 Eigen
                    last_err = e
                    log.warning("引擎 %s 启动失败: %s", cand.backend, e)
            msg = f"所有引擎启动失败: {last_err}"
            raise EngineError(msg, code="engine.all_failed", params={"detail": str(last_err)})

        self._starting = asyncio.create_task(_start())
        try:
            return await self._starting
        finally:
            self._starting = None

    async def restart(self) -> KataGoEngine:
        """下载完成后重建引擎。"""
        if self.engine:
            await self.engine.stop()
            self.engine = None
        return await self.ensure_started()

    async def shutdown(self) -> None:
        if self.engine:
            await self.engine.stop()
