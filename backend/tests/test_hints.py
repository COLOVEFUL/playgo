"""渐进推荐的预算、超时、取消、缓存和局面隔离回归。"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from playgo import settings
from playgo.hints import HintService
from playgo.katago import Analysis, EngineError, EngineManager, KataGoEngine
from playgo.rules import BLACK, WHITE


def analysis(visits, point=40):
    return Analysis(
        WHITE,
        0.7,
        2.0,
        [0.0] * 81,
        [{"point": point, "winrate_black": 0.7, "score_lead_black": 2.0, "order": 0}],
        visits=visits,
    )


class FakeEngine:
    def __init__(self, *, gpu=False):
        self.is_gpu = gpu
        self.calls = []
        self.cancelled = False
        self.behavior = "normal"

    async def analyze(self, moves, **kwargs):
        self.calls.append((moves, kwargs))
        if len(self.calls) % 2 == 1:
            return analysis(80)
        try:
            kwargs["on_update"](analysis(40, 41))  # 深度回退不得覆盖第一阶段
            await asyncio.sleep(0.001)
            kwargs["on_update"](analysis(400, 42))
            await asyncio.sleep(0.001)
            if self.behavior == "error":
                raise EngineError(code="engine.exited")
            if self.behavior == "hang":
                await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return analysis(kwargs["max_visits"], 43)


def manager(engine):
    return SimpleNamespace(engine=engine, ensure_started=AsyncMock(return_value=engine))


def stream(service, mgr, *, current=lambda: True, source=("test",), moves=None, komi=6.5):
    return service.stream(
        mgr,
        moves or [(BLACK, 1)],
        to_move=WHITE,
        size=9,
        komi=komi,
        source=source,
        is_current=current,
    )


async def collect(iterator):
    return [json.loads(line) async for line in iterator]


@pytest.mark.parametrize("gpu", [True, False])
def test_progressive_budgets_and_final_cache(gpu):
    async def scenario():
        engine = FakeEngine(gpu=gpu)
        mgr, service = manager(engine), HintService()
        result = await collect(stream(service, mgr))
        assert result[0]["visits"] == 80
        assert result[0]["thinking"]
        assert result[-1]["stop_reason"] == "visits"
        assert not result[-1]["thinking"]
        assert result[-1]["visits"] >= result[-1]["ai_visits"] * 10
        assert [r["visits"] for r in result] == sorted(r["visits"] for r in result)
        for moves, kwargs in engine.calls:
            assert moves == [(BLACK, 1)]
            assert kwargs["size"] == 9
            assert kwargs["komi"] == 6.5
            assert kwargs["max_visits"] <= settings.ENGINE_MAX_VISITS
            assert "human_profile" not in kwargs
        cached = await collect(stream(service, mgr))
        assert cached == [result[-1]]
        assert len(engine.calls) == 2
        await collect(stream(service, mgr, komi=0.5))
        await collect(stream(service, mgr, moves=[(BLACK, 2)]))
        assert len(engine.calls) == 6
        # 同预算下切换引擎实例，也不能复用旧缓存。
        replacement = FakeEngine(gpu=gpu)
        await collect(stream(service, manager(replacement)))
        assert len(replacement.calls) == 2

    asyncio.run(scenario())


@pytest.mark.parametrize(("behavior", "reason"), [("hang", "time"), ("error", "error")])
def test_deadline_or_engine_error_preserves_latest(monkeypatch, behavior, reason):
    monkeypatch.setattr(settings, "HINT_TOTAL_SECONDS", 0.04)

    async def scenario():
        engine = FakeEngine()
        engine.behavior = behavior
        service = HintService()
        result = await collect(stream(service, manager(engine)))
        assert result[-1]["visits"] == 400
        assert not result[-1]["thinking"]
        assert result[-1]["stop_reason"] == reason
        assert not service.cache
        if behavior == "hang":
            assert engine.cancelled

    asyncio.run(scenario())


def test_stream_close_cancels_search():
    async def scenario():
        engine = FakeEngine()
        engine.behavior = "hang"
        service = HintService()
        iterator = stream(service, manager(engine))
        await anext(iterator)
        await iterator.aclose()
        assert engine.cancelled
        assert not service.cache

    asyncio.run(scenario())


def test_position_change_cancels_search(monkeypatch):
    monkeypatch.setattr(settings, "HINT_REPORT_SECONDS", 0.002)

    async def scenario():
        engine = FakeEngine()
        engine.behavior = "hang"
        current = True
        iterator = stream(HintService(), manager(engine), current=lambda: current)
        await anext(iterator)
        current = False
        assert await collect(iterator) == []
        assert engine.cancelled

    asyncio.run(scenario())


def test_startup_is_bounded(monkeypatch):
    monkeypatch.setattr(settings, "HINT_TOTAL_SECONDS", 0.01)

    async def scenario():
        async def start():
            await asyncio.Event().wait()

        mgr = SimpleNamespace(ensure_started=start)
        result = await collect(stream(HintService(), mgr))
        assert result[0]["error"]["code"] == "engine.analyze_timeout"

    asyncio.run(scenario())


@pytest.mark.parametrize("cancel", [True, False])
def test_engine_query_progress_cap_and_terminate(cancel):
    async def scenario():
        engine = KataGoEngine(Path("x"), Path("y"), "eigen")
        engine.ready = True
        writes, reports = [], []

        class Stdin:
            def write(self, data):
                writes.append(json.loads(data))

            async def drain(self):
                query = writes[0]
                response = {
                    "id": query["id"],
                    "isDuringSearch": True,
                    "rootInfo": {"visits": 4},
                }
                engine._handle_stdout_line(json.dumps(response))

        engine.proc = SimpleNamespace(stdin=Stdin(), returncode=None)
        task = asyncio.create_task(
            engine.analyze(
                [],
                to_move=BLACK,
                max_visits=settings.ENGINE_MAX_VISITS * 2,
                max_time=2,
                timeout=0.01,
                on_update=reports.append,
            )
        )
        await asyncio.sleep(0)
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else EngineError):
            await task
        assert reports[0].visits == 4
        assert writes[0]["maxVisits"] == settings.ENGINE_MAX_VISITS - engine.num_threads
        assert writes[0]["overrideSettings"]["maxTime"] == 2
        assert writes[-1]["action"] == "terminate"
        assert writes[-1]["terminateId"] == writes[0]["id"]
        assert not engine._pending
        assert not engine._progress

    asyncio.run(scenario())


def test_cancelled_start_waiter_does_not_orphan_engine(monkeypatch):
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        async def start(engine):
            started.set()
            await release.wait()
            engine.ready = True

        monkeypatch.setattr(KataGoEngine, "start", start)
        monkeypatch.setattr("playgo.katago._pkg_installed", lambda _pkg: True)
        mgr = EngineManager()
        first = asyncio.create_task(mgr.ensure_started())
        await started.wait()
        startup = mgr._starting
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert mgr._starting is startup
        assert not startup.cancelled()
        second = asyncio.create_task(mgr.ensure_started())
        release.set()
        engine = await second
        assert engine.ready
        assert mgr.engine is engine
        assert mgr._starting is None

    asyncio.run(scenario())
