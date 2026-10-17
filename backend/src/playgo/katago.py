"""KataGo Analysis Engine 子进程封装。

一个引擎进程服务所有需求：AI 行棋（按难度控制 visits 与采样）、
AI 推荐（top-N 候选）、形势判断（ownership 热力）、复盘批量分析。
坐标转换：内部 x 从左、y 从上；KataGo 用字母（跳 I）+ 从底部数的行号。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeVar

from playgo import settings
from playgo.downloader import installed, item_size
from playgo.errors import PlayGoError
from playgo.rules import BLACK

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

log = logging.getLogger("playgo.katago")

KATA_LETTERS = "ABCDEFGHJKLMNOPQRST"  # 跳过 I

T = TypeVar("T")


def to_kata_coords(point: int, size: int = 19) -> str:
    x, y = point % size, point // size
    return f"{KATA_LETTERS[x]}{size - y}"


def from_kata_coords(s: str, size: int = 19) -> int:
    x = KATA_LETTERS.index(s[0].upper())
    y = size - int(s[1:])
    return y * size + x


@dataclass
class Analysis:
    """一次局面分析的归一化结果（一律“黑方视角”：胜率>0 为黑优）。

    引擎输出本身即黑方视角（启动时已钉死 reportAnalysisWinratesAs=BLACK），
    这里不做任何翻转；to_move 仅记录该局面轮谁走，供上层参考。
    """

    to_move: int  # 分析局面下该谁走（不参与胜率换算）
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
                    # 官方 cfg（v1.13+）默认 reportAnalysisWinratesAs=BLACK：winrate/scoreLead/
                    # ownership 一律黑方视角。显式钉死，防止未来 cfg 变更悄悄改变视角语义。
                    "reportAnalysisWinratesAs=BLACK",
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
                    # KataGo 的单行 JSON 响应可达数百 KB（visits 大/PV 长时），
                    # 默认 64KB 行上限会让 readline 抛错杀死读取任务 → 引擎"失聪"
                    limit=2**22,
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
        try:
            while True:
                line = await self.proc.stdout.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    self._handle_stdout_line(text)
        except Exception:
            # 读取任务死亡 = 引擎从此"失聪"，必须显式记录而非静默退出
            log.exception("引擎 stdout 读取任务异常")
        finally:
            # 进程结束或读取异常：唤醒所有等待者
            for fut in self._pending.values():
                if not fut.done():
                    msg = "引擎进程已退出"
                    fut.set_exception(EngineError(msg, code="engine.exited"))

    def _handle_stdout_line(self, text: str) -> None:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return  # 表头等非 JSON 行
        self._any_response_seen = True
        fut = self._pending.get(data.get("id"))
        if not fut or fut.done():
            return
        if data.get("isDuringSearch"):
            return  # 只要最终结果
        if "warning" in data and "rootInfo" not in data:
            log.warning("引擎告警: %s", data)
            return  # 告警行可能带查询 id，不能当结果
        fut.set_result(data)

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

    def auto_timeout(self, max_visits: int) -> float:
        """按 visits 与后端估算单次查询超时：GPU 快，CPU(Eigen) 慢。"""
        per_visit = 0.12 if self.is_gpu else 2.5
        return max(60.0, 30.0 + max_visits * per_visit)

    async def analyze(
        self,
        moves: list[tuple[int, int | None]],
        *,
        to_move: int,
        max_visits: int,
        size: int = 19,
        komi: float = settings.KOMI,
        timeout: float = 0.0,
    ) -> Analysis:
        """分析当前局面。moves 为已落子的历史（不含即将走的一手）。

        timeout<=0 时按 visits/后端自动估算（困难档 800 visits 在 GPU 上
        也可能超过固定 60s）。
        """
        if not self.ready:
            msg = "引擎未就绪"
            raise EngineError(msg, code="engine.not_ready")
        if timeout <= 0:
            timeout = self.auto_timeout(max_visits)
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
            tail = "\n".join(self._stderr_tail[-5:])
            log.warning("分析超时(%ss) stderr尾: %s", timeout, tail)
            msg = f"分析超时({timeout}s)"
            raise EngineError(
                msg, code="engine.analyze_timeout", params={"timeout": timeout}
            ) from None
        finally:
            self._pending.pop(rid, None)

        return self._normalize(data, to_move, size)

    def _normalize(self, data: dict, to_move: int, size: int) -> Analysis:
        """归一化引擎输出。启动已钉死 reportAnalysisWinratesAs=BLACK，
        winrate/scoreLead/ownership 本身即黑方视角（+黑 −白），直接透传。

        历史 bug：曾以为输出是“行棋方视角”而按 to_move 翻转，导致所有轮白走
        的局面胜率/归属被反向（复盘曲线在 50% 上下锯齿、白回合形势判断黑白颠倒）。
        可用 rootInfo.currentPlayer 核对行棋方，但视角本身不再依赖 to_move。
        """
        root = data.get("rootInfo", {})
        ownership = list(data.get("ownership") or [0.0] * (size * size))
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
                    "winrate_black": m["winrate"],
                    "score_lead_black": m["scoreLead"],
                    "pv": m.get("pvVisits", None) or [],
                }
            )
        return Analysis(
            to_move=to_move,
            winrate_black=root.get("winrate", 0.5),
            score_lead_black=root.get("scoreLead", 0.0),
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


# ── 引擎包选择持久化（backend/engines/choice.json）──────────────────
# 只在用户显式切换时写入；缺省选择按磁盘已装包推导（GPU 装全→gpu，否则 cpu），
# 于是"全新装机下载完 GPU 包"时推导默认自然翻转为 gpu，即下载后自动切换。


def _choice_path() -> Path:
    return settings.ENGINES_DIR / "choice.json"


def read_choice() -> str | None:
    """读取用户显式选择的引擎包 id；无文件/损坏/非法值 → None（不回写）。"""
    try:
        data = json.loads(_choice_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = data.get("engine")
    return value if value in settings.PACKAGES else None


def write_choice(pkg_id: str) -> None:
    """原子写入用户选择（tmp + replace；Windows 下 rename 不覆盖已存在目标）。"""
    path = _choice_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"engine": pkg_id}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _pkg_installed(pkg: settings.EnginePackage) -> bool:
    """包是否装全（exe 与配套网络都在；文件即事实，与下载器幂等判定一致）。"""
    return pkg.exe.exists() and pkg.model.exists()


def _default_choice() -> str:
    """缺省选择：老环境（GPU 包已装全）保持 GPU 体验不变，全新装机默认 CPU 轻量包。"""
    return "gpu" if _pkg_installed(settings.PACKAGES["gpu"]) else "cpu"


class EngineManager:
    """持有当前引擎包对应的引擎进程；启动顺序 = 用户选择优先，另一已装包兜底。"""

    def __init__(self) -> None:
        self.engine: KataGoEngine | None = None
        self._starting: asyncio.Task | None = None
        self.selected_id: str = read_choice() or _default_choice()
        self._restart_lock = asyncio.Lock()

    def _ordered_packages(self) -> list[settings.EnginePackage]:
        """启动候选包：选中包优先，另一包仅在装全时兜底（如无 OpenCL 设备回落 CPU）。"""
        selected = settings.PACKAGES[self.selected_id]
        other = settings.PACKAGES["cpu" if selected.id == "gpu" else "gpu"]
        cands = [selected]
        if other.id != selected.id and _pkg_installed(other):
            cands.append(other)
        return cands

    def _package_view(self, pkg: settings.EnginePackage) -> dict:
        """单包状态视图（缺失项 + 汇总量，供前端渲染包卡片）。"""
        missing = [
            {"id": i, "size_mb": item_size(i)} for i in pkg.items if not installed(i)
        ]
        return {
            "id": pkg.id,
            "backend": pkg.backend,
            "gpu": pkg.backend == "opencl",
            "model": pkg.model.name,
            "installed": _pkg_installed(pkg),
            "active": bool(self.engine and self.engine.backend == pkg.backend),
            "missing": missing,
            "size_mb": sum(m["size_mb"] for m in missing),
        }

    def status(self) -> dict:
        return {
            "available": self.engine.ready if self.engine else False,
            "engine": self.engine.describe() if self.engine else None,
            "selected": self.selected_id,
            "packages": [self._package_view(p) for p in settings.PACKAGES.values()],
        }

    async def ensure_started(self) -> KataGoEngine:
        """启动选中（或兜底）引擎（幂等）。无任何可用引擎时抛 EngineError。"""
        if self.engine and self.engine.ready:
            return self.engine
        if self._starting:
            return await asyncio.shield(self._starting)
        cands = [
            KataGoEngine(p.exe, p.model, p.backend)
            for p in self._ordered_packages()
            if _pkg_installed(p)
        ]
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
                except EngineError as e:  # 选中包失败则回退另一包
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
        """重建引擎（下载补齐文件/实例疑似卡死时）。select/_after/自愈重试共用，串行执行。"""
        async with self._restart_lock:
            if self._starting:
                # 等在途启动收尾，绝不 cancel——cancel 会孤儿化半启动的子进程
                with contextlib.suppress(BaseException):
                    await asyncio.shield(self._starting)
            if self.engine:
                await self.engine.stop()
                self.engine = None
            return await self.ensure_started()

    async def select(self, pkg_id: str) -> KataGoEngine:
        """切换引擎包：持久化选择 → 停旧 → 启新（选中包启动失败回落另一已装包，
        选择不回写撤销——保留用户意图，状态里 selected != active 供前端提示）。"""
        write_choice(pkg_id)
        self.selected_id = pkg_id
        return await self.restart()

    # ── 带自愈的查询入口：超时/进程退出=实例疑似卡死或被切换重启，重启后重试一次 ──

    async def _retry_on_wedge(self, query: Callable[[KataGoEngine], Awaitable[T]]) -> T:
        for attempt in (1, 2):
            engine = await self.ensure_started()
            try:
                return await query(engine)
            except EngineError as e:
                if e.code not in ("engine.analyze_timeout", "engine.exited") or attempt == 2:
                    raise
                log.warning("引擎无响应/已退出，重启后重试: %s", e)
                await self.restart()
        raise EngineError(msg="unreachable", code="engine.not_ready")

    async def analyze(
        self,
        moves: list[tuple[int, int | None]],
        *,
        to_move: int,
        max_visits: int,
        size: int = 19,
        komi: float = settings.KOMI,
        timeout: float = 0.0,
    ) -> Analysis:
        return await self._retry_on_wedge(
            lambda engine: engine.analyze(
                moves, to_move=to_move, max_visits=max_visits,
                size=size, komi=komi, timeout=timeout,
            )
        )

    async def pick_move(
        self,
        moves: list[tuple[int, int | None]],
        to_move: int,
        difficulty: str,
        *,
        size: int = 19,
    ) -> tuple[int | None, Analysis]:
        return await self._retry_on_wedge(
            lambda engine: engine.pick_move(moves, to_move, difficulty, size=size)
        )

    async def shutdown(self) -> None:
        if self.engine:
            await self.engine.stop()
