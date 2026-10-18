"""渐进推荐的预算、超时、取消、缓存和局面隔离回归。"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from playgo import main, settings
from playgo.game import GameConfig, GameSession
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
        try:
            if self.behavior == "silent":
                await asyncio.Event().wait()
            kwargs["on_update"](analysis(80))
            await asyncio.sleep(0.001)
            kwargs["on_update"](analysis(40, 41))  # 旧/异常倒退报告不得覆盖
            kwargs["on_update"](analysis(400, 42))
            await asyncio.sleep(0.001)
            if self.behavior == "error":
                raise EngineError(code="engine.exited")
            if self.behavior == "hang":
                await asyncio.Event().wait()
            if self.behavior == "heartbeat":
                while True:
                    kwargs["on_update"](analysis(400, 42))
                    await asyncio.sleep(0.001)
            if self.behavior == "healthy":
                for visits in range(500, 508):
                    await asyncio.sleep(0.03)
                    kwargs["on_update"](analysis(visits, 42))
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


@pytest.mark.parametrize("count", [2, 7])
def test_stream_and_live_hint_offer_five_candidates_without_padding(monkeypatch, count):
    async def scenario():
        ana = analysis(settings.ENGINE_MAX_VISITS)
        ana.best_moves = [
            {"point": 40 + i, "winrate_black": 0.7, "score_lead_black": 2.0, "order": i}
            for i in range(count)
        ]
        engine = FakeEngine()
        engine.analyze = AsyncMock(return_value=ana)
        mgr = manager(engine)
        service = HintService()
        result = (await collect(stream(service, mgr)))[-1]
        app_state = main.AppState()
        app_state.game = GameSession(GameConfig(size=9, komi=6.5))
        app_state.engine = mgr
        mgr.analyze = AsyncMock(return_value=ana)
        monkeypatch.setattr(main, "state", app_state)
        live = await main.hint()
        expected = list(range(40, 40 + min(count, 5)))
        assert [move["point"] for move in result["moves"]] == expected
        assert [move["point"] for move in live["moves"]] == expected

    asyncio.run(scenario())


@pytest.mark.parametrize("gpu", [True, False])
def test_single_continuous_search_and_final_cache(gpu):
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
            assert kwargs["max_visits"] == settings.ENGINE_MAX_VISITS
            assert kwargs["timeout"] is None
            assert kwargs["max_time"] == 1e20
            assert "human_profile" not in kwargs
        cached = await collect(stream(service, mgr))
        assert cached == [result[-1]]
        assert len(engine.calls) == 1
        await collect(stream(service, mgr, komi=0.5))
        await collect(stream(service, mgr, moves=[(BLACK, 2)]))
        assert len(engine.calls) == 3
        # 同预算下切换引擎实例，也不能复用旧缓存。
        replacement = FakeEngine(gpu=gpu)
        await collect(stream(service, manager(replacement)))
        assert len(replacement.calls) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("behavior", "reason"), [("hang", "idle"), ("heartbeat", "idle"), ("error", "error")]
)
def test_stalled_visits_or_engine_error_preserves_latest(monkeypatch, behavior, reason):
    monkeypatch.setattr(settings, "HINT_IDLE_SECONDS", 0.04)

    async def scenario():
        engine = FakeEngine()
        engine.behavior = behavior
        service = HintService()
        result = await collect(stream(service, manager(engine)))
        assert result[-1]["visits"] == 400
        assert not result[-1]["thinking"]
        assert result[-1]["stop_reason"] == reason
        assert not service.cache
        if behavior != "error":
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
    monkeypatch.setattr(settings, "HINT_FIRST_RESULT_SECONDS", 0.01)

    async def scenario():
        async def start():
            await asyncio.Event().wait()

        mgr = SimpleNamespace(ensure_started=start)
        result = await collect(stream(HintService(), mgr))
        assert result[0]["error"]["code"] == "engine.analyze_timeout"

    asyncio.run(scenario())


def test_healthy_progress_outlives_first_result_deadline(monkeypatch):
    monkeypatch.setattr(settings, "HINT_FIRST_RESULT_SECONDS", 0.03)
    monkeypatch.setattr(settings, "HINT_IDLE_SECONDS", 0.12)

    async def scenario():
        engine = FakeEngine()
        engine.behavior = "healthy"
        started = asyncio.get_running_loop().time()
        result = await collect(stream(HintService(), manager(engine)))
        assert asyncio.get_running_loop().time() - started > settings.HINT_FIRST_RESULT_SECONDS
        assert result[-1]["stop_reason"] == "visits"
        assert not result[-1]["thinking"]
        assert not engine.cancelled
        assert len(engine.calls) == 1

    asyncio.run(scenario())


def test_no_first_result_is_bounded(monkeypatch):
    monkeypatch.setattr(settings, "HINT_FIRST_RESULT_SECONDS", 0.01)

    async def scenario():
        engine = FakeEngine()
        engine.behavior = "silent"
        result = await collect(stream(HintService(), manager(engine)))
        assert result[-1]["error"]["code"] == "engine.analyze_timeout"
        assert engine.cancelled

    asyncio.run(scenario())


def test_backend_cancel_stale_works_without_client_disconnecting():
    async def scenario():
        engine = FakeEngine()
        engine.behavior = "hang"
        service = HintService()
        current = True
        iterator = stream(service, manager(engine), current=lambda: current)
        await anext(iterator)
        current = False
        # 客户端没有再读取/关闭流，后端依然主动取消引擎任务。
        await service.cancel_stale()
        assert engine.cancelled
        assert await collect(iterator) == []
        assert not service._active
        assert not service.cache

    asyncio.run(scenario())


def test_backend_cancel_preserves_valid_search():
    async def scenario():
        engine = FakeEngine()
        engine.behavior = "hang"
        service = HintService()
        iterator = stream(service, manager(engine))
        await anext(iterator)
        await service.cancel_stale()
        assert not engine.cancelled
        await service.cancel_all()
        assert engine.cancelled
        assert await collect(iterator) == []

    asyncio.run(scenario())


def test_duplicate_requests_share_one_search_until_last_disconnect():
    async def scenario():
        engine = FakeEngine()
        engine.behavior = "hang"
        service, mgr = HintService(), manager(engine)
        first = stream(service, mgr)
        initial = json.loads(await anext(first))
        second = stream(service, mgr)
        joined = json.loads(await anext(second))
        assert joined["visits"] >= initial["visits"]
        assert len(engine.calls) == 1
        assert len(service._active) == 1
        await first.aclose()
        assert not engine.cancelled
        await second.aclose()
        assert engine.cancelled
        assert not service._active
        assert not service._running

    asyncio.run(scenario())


def test_shared_search_fans_out_final_result_to_all_clients():
    async def scenario():
        engine = FakeEngine()
        service, mgr = HintService(), manager(engine)
        first, second = await asyncio.gather(
            collect(stream(service, mgr)),
            collect(stream(service, mgr)),
        )
        assert first[-1] == second[-1]
        assert first[-1]["stop_reason"] == "visits"
        assert len(engine.calls) == 1
        assert await collect(stream(service, mgr)) == [first[-1]]
        assert len(engine.calls) == 1
        assert not service._active
        assert not service._running

    asyncio.run(scenario())


def test_position_change_cancels_shared_search_for_every_subscriber():
    async def scenario():
        engine = FakeEngine()
        engine.behavior = "hang"
        service, mgr = HintService(), manager(engine)
        current = True
        first = stream(service, mgr, current=lambda: current)
        second = stream(service, mgr, current=lambda: current)
        await anext(first)
        await anext(second)
        current = False
        await service.cancel_stale()
        assert engine.cancelled
        assert await collect(first) == []
        assert await collect(second) == []
        assert not service._active
        assert not service._running

    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["move", "pass", "undo", "new", "score", "resign", "ai"])
def test_game_mutation_terminates_hint_before_handler_returns(monkeypatch, action):
    async def scenario():
        engine = FakeEngine()
        engine.behavior = "hang"
        app_state = main.AppState()
        game = GameSession(
            GameConfig(
                mode="ai" if action == "ai" else "pvp",
                takeover=True,
                time=settings.TimeSettings.presets()["free"],
            )
        )
        game.play(BLACK, 60)
        app_state.game = game
        app_state.emit_state = Mock()
        app_state.schedule_ai = Mock()
        app_state.auto_scoring = AsyncMock()
        app_state.engine = manager(engine)
        app_state.engine.pick_move = AsyncMock(return_value=(61, analysis(160)))
        monkeypatch.setattr(main, "state", app_state)
        moves = [(move.color, move.point) for move in game.moves]
        iterator = app_state.hints.stream(
            app_state.engine,
            moves,
            to_move=game.to_play,
            size=19,
            komi=7.5,
            source=(game.id,),
            is_current=lambda: (
                app_state.game is game
                and game.status == "playing"
                and moves == [(move.color, move.point) for move in game.moves]
            ),
        )
        await anext(iterator)
        match action:
            case "move":
                await main.play_move(main.MoveReq(point=61))
            case "pass":
                await main.pass_move()
            case "undo":
                await main.undo()
            case "new":
                await main.new_game(main.NewGameReq(mode="pvp", time_preset="free"))
            case "score":
                await main.request_score()
            case "resign":
                await main.resign(main.ResignReq(color=WHITE))
            case "ai":
                await app_state._ai_move()
        assert engine.cancelled
        assert await collect(iterator) == []
        assert not app_state.hints._active
        assert not app_state.hints.cache

    asyncio.run(scenario())


def test_rejected_move_does_not_cancel_valid_hint(monkeypatch):
    async def scenario():
        engine = FakeEngine()
        engine.behavior = "hang"
        app_state = main.AppState()
        game = GameSession(GameConfig())
        game.play(BLACK, 60)
        app_state.game = game
        app_state.engine = manager(engine)
        monkeypatch.setattr(main, "state", app_state)
        iterator = app_state.hints.stream(
            app_state.engine,
            [(BLACK, 60)],
            to_move=WHITE,
            size=19,
            komi=7.5,
            source=(game.id,),
            is_current=lambda: len(game.moves) == 1,
        )
        await anext(iterator)
        with pytest.raises(HTTPException):
            await main.play_move(main.MoveReq(point=60))
        assert not engine.cancelled
        await iterator.aclose()

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
