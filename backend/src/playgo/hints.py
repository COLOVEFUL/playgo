"""限时、可取消的两阶段推荐流；仅缓存完整结束的搜索。"""

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
    updates: asyncio.Queue[dict] = field(default_factory=lambda: asyncio.Queue(maxsize=1))
    best: Analysis | None = None

    @property
    def budget(self) -> int:
        return min(
            settings.HINT_DEEP_VISITS if self.engine.is_gpu else settings.HINT_DEEP_VISITS_CPU,
            settings.ENGINE_MAX_VISITS,
        )

    def publish(self, ana: Analysis, *, done: bool = False) -> None:
        # 第二次搜索重建树，追上已有深度后才更新；最终也不以更浅结果覆盖。
        if self.best and ana.visits < self.best.visits:
            if not done:
                return
            ana = self.best
        self.best = ana
        ai_visits = max(
            p["visits"] if self.engine.is_gpu else p["cpu_visits"]
            for p in settings.DIFFICULTY_PRESETS.values()
        )
        data = {
            "to_play": self.to_move,
            "move_count": len(self.moves),
            "winrate_black": ana.winrate_black,
            "score_lead_black": ana.score_lead_black,
            "moves": ana.best_moves[:3],
            "recommend_pass": ana.top_is_pass,
            "visits": ana.visits,
            "budget_visits": self.budget,
            "ai_visits": ai_visits,
            "thinking": not done,
            "stop_reason": ("visits" if ana.visits >= self.budget else "time") if done else None,
        }
        if self.updates.full():
            self.updates.get_nowait()
        self.updates.put_nowait(data)

    async def run(self) -> None:
        quick = settings.HINT_VISITS if self.engine.is_gpu else settings.HINT_VISITS_CPU
        stages = (
            (quick, settings.HINT_QUICK_SECONDS),
            (self.budget, settings.HINT_DEEP_SECONDS),
        )
        for stage, (visits, seconds) in enumerate(stages):
            ana = await self.engine.analyze(
                self.moves,
                to_move=self.to_move,
                size=self.size,
                komi=self.komi,
                max_visits=min(visits, settings.ENGINE_MAX_VISITS),
                max_time=seconds,
                timeout=seconds + 1,
                on_update=self.publish,
            )
            self.publish(ana, done=stage == 1)

    def finished(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            if self.updates.full():
                self.updates.get_nowait()
            self.updates.put_nowait({"failure": error})


def _failure(latest: dict | None, exc: TimeoutError | EngineError) -> dict:
    if latest:
        return {
            **latest,
            "thinking": False,
            "stop_reason": "time" if isinstance(exc, TimeoutError) else "error",
        }
    error = (
        exc
        if isinstance(exc, EngineError)
        else EngineError(
            "推荐达到等待上限",
            code="engine.analyze_timeout",
            params={"timeout": settings.HINT_TOTAL_SECONDS},
        )
    )
    return {"error": payload_of(error)}


class HintService:
    def __init__(self) -> None:
        self.cache: OrderedDict[tuple, dict] = OrderedDict()

    def remember(self, key: tuple, data: dict) -> None:
        self.cache[key] = data
        if len(self.cache) > 64:
            self.cache.popitem(last=False)

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
        task: asyncio.Task | None = None
        try:
            async with asyncio.timeout(settings.HINT_TOTAL_SECONDS):
                engine = await manager.ensure_started()
                # 实例身份隔离切换/回落；完整前缀、尺寸、贴目隔离局面。
                key = (engine, source, tuple(moves), to_move, size, komi)
                if key in self.cache:
                    self.cache.move_to_end(key)
                    yield json.dumps(self.cache[key]) + "\n"
                    return
                search = _HintSearch(engine, moves, to_move, size, komi)
                task = asyncio.create_task(search.run())
                task.add_done_callback(search.finished)
                while is_current() and manager.engine is engine:
                    try:
                        update = await asyncio.wait_for(
                            search.updates.get(), settings.HINT_REPORT_SECONDS
                        )
                    except TimeoutError:
                        if task.done():
                            await task
                            return
                        continue
                    # 等待期间可能已落子/新开局，旧结果不再推送。
                    if not is_current() or manager.engine is not engine:
                        return
                    if "failure" in update:
                        raise update["failure"]
                    latest = update
                    yield json.dumps(latest) + "\n"
                    if not latest["thinking"]:
                        self.remember(key, latest)
                        return
        except (TimeoutError, EngineError) as exc:
            yield json.dumps(_failure(latest, exc)) + "\n"
        finally:
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, EngineError):
                    await task
