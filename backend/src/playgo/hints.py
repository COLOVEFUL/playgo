"""可取消的连续推荐流：持续搜索到 visits 上限，按实际搜索进展监测超时。"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from playgo import settings
from playgo.errors import payload_of
from playgo.katago import Analysis, EngineError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from playgo.katago import EngineManager, KataGoEngine


@dataclass
class _HintSearch:
    engine: KataGoEngine
    moves: list[tuple[int, int | None]]
    to_move: int
    size: int
    komi: float
    deadline: float
    listeners: set[asyncio.Queue[dict]] = field(default_factory=set)
    latest: dict | None = None
    task: asyncio.Task | None = None
    best: Analysis | None = None

    def publish(self, ana: Analysis, *, done: bool = False) -> None:
        if not done and ana.visits <= 0:
            return
        # 重复报告相同 visits 不算进展，不能让卡住的查询永久刷新超时。
        if ana.visits > (self.best.visits if self.best else 0):
            self.deadline = asyncio.get_running_loop().time() + settings.HINT_IDLE_SECONDS
        if self.best and ana.visits < self.best.visits:
            return
        self.best = ana
        ai_visits = max(
            p["visits"] if self.engine.is_gpu else p["cpu_visits"]
            for p in settings.DIFFICULTY_PRESETS.values()
        )
        self.enqueue(
            {
                "to_play": self.to_move,
                "move_count": len(self.moves),
                "winrate_black": ana.winrate_black,
                "score_lead_black": ana.score_lead_black,
                "moves": ana.best_moves[: settings.HINT_MOVE_COUNT],
                "recommend_pass": ana.top_is_pass,
                "visits": ana.visits,
                "budget_visits": settings.ENGINE_MAX_VISITS,
                "ai_visits": ai_visits,
                "thinking": not done,
                "stop_reason": "visits" if done else None,
            }
        )

    def enqueue(self, data: dict) -> None:
        self.latest = data
        for updates in self.listeners:
            if updates.full():
                updates.get_nowait()
            updates.put_nowait(data)

    def subscribe(self, updates: asyncio.Queue[dict]) -> None:
        self.listeners.add(updates)
        if self.latest is not None:
            updates.put_nowait(self.latest)

    async def run(self) -> None:
        ana = await self.engine.analyze(
            self.moves,
            to_move=self.to_move,
            size=self.size,
            komi=self.komi,
            max_visits=settings.ENGINE_MAX_VISITS,
            # 使用 KataGo 默认的无实际时长约束值，避免用户自定义 cfg 的 maxTime 截断。
            # 上层按 visits 进展监测超时；这里只保留 visits 硬上限。
            max_time=1e20,
            timeout=None,
            on_update=self.publish,
        )
        self.publish(ana, done=True)

    def finished(self, task: asyncio.Task) -> None:
        if task.cancelled():
            self.enqueue({"cancelled": True})
            return
        error = task.exception()
        if error is not None:
            self.enqueue({"failure": error})

    async def next_update(self, updates: asyncio.Queue[dict]) -> dict:
        remaining = self.deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError
        # 定期唤醒校验当前局面，同时严格按最近一次 visits 增长计算截止时间。
        return await asyncio.wait_for(updates.get(), min(remaining, settings.HINT_REPORT_SECONDS))


def _failure(latest: dict | None, exc: TimeoutError | EngineError) -> dict:
    if latest:
        return {
            **latest,
            "thinking": False,
            "stop_reason": "idle" if isinstance(exc, TimeoutError) else "error",
        }
    error = (
        exc
        if isinstance(exc, EngineError)
        else EngineError(
            "推荐等待超时",
            code="engine.analyze_timeout",
            params={"timeout": settings.HINT_FIRST_RESULT_SECONDS},
        )
    )
    return {"error": payload_of(error)}


class HintService:
    def __init__(self) -> None:
        self.cache: OrderedDict[tuple, dict] = OrderedDict()
        self._active: dict[asyncio.Task, Callable[[], bool]] = {}
        self._running: dict[tuple, _HintSearch] = {}

    def remember(self, key: tuple, data: dict) -> None:
        self.cache[key] = data
        if len(self.cache) > 64:
            self.cache.popitem(last=False)

    async def cancel_stale(self) -> None:
        tasks = [task for task, current in self._active.items() if not current()]
        await self._cancel(tasks)

    async def cancel_all(self) -> None:
        await self._cancel(list(self._active))

    @staticmethod
    async def _cancel(tasks: list[asyncio.Task]) -> None:
        for task in tasks:
            task.cancel()
        # 只等 Python 查询清理并写出 terminate，不等待引擎返回终止确认。
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _updates(
        self, search: _HintSearch, updates: asyncio.Queue[dict], is_current: Callable[[], bool]
    ) -> AsyncIterator[dict]:
        while is_current():
            try:
                data = await search.next_update(updates)
            except TimeoutError:
                if asyncio.get_running_loop().time() >= search.deadline:
                    raise
                continue
            if not is_current() or data.get("cancelled"):
                return
            if "failure" in data:
                raise data["failure"]
            yield data
            if not data["thinking"]:
                return

    async def stream(
        self,
        manager: EngineManager,
        moves: list[tuple[int, int | None]],
        *,
        to_move: int,
        size: int,
        komi: float,
        source: tuple,
        is_current: Callable[[], bool],
    ) -> AsyncIterator[str]:
        latest: dict | None = None
        search: _HintSearch | None = None
        updates: asyncio.Queue[dict] = asyncio.Queue(maxsize=1)
        deadline = asyncio.get_running_loop().time() + settings.HINT_FIRST_RESULT_SECONDS
        try:
            engine = await asyncio.wait_for(
                manager.ensure_started(), settings.HINT_FIRST_RESULT_SECONDS
            )

            def current() -> bool:
                return is_current() and manager.engine is engine

            if not current():
                return
            key = (engine, source, tuple(moves), to_move, size, komi)
            if key in self.cache:
                self.cache.move_to_end(key)
                yield json.dumps(self.cache[key]) + "\n"
                return
            search = self._running.get(key)
            if search is None:
                search = _HintSearch(engine, moves, to_move, size, komi, deadline)
                search.task = asyncio.create_task(search.run())
                search.task.add_done_callback(search.finished)
                self._active[search.task] = current
                self._running[key] = search
            search.subscribe(updates)
            async for latest in self._updates(search, updates, current):
                yield json.dumps(latest) + "\n"
                if not latest["thinking"]:
                    self.remember(key, latest)
        except (TimeoutError, EngineError) as exc:
            yield json.dumps(_failure(latest, exc)) + "\n"
        finally:
            if search:
                search.listeners.discard(updates)
                if not search.listeners:
                    self._running.pop(key, None)
                    await self._stop(search)

    async def _stop(self, search: _HintSearch) -> None:
        assert search.task is not None
        self._active.pop(search.task, None)
        search.task.cancel()
        with contextlib.suppress(asyncio.CancelledError, EngineError):
            await search.task
