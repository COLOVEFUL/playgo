"""复盘接管、推荐及跨对局异步分析的回归测试（不启动真实引擎）。"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from playgo import main, settings
from playgo.game import GameConfig, GameSession
from playgo.katago import Analysis, EngineError
from playgo.rules import BLACK, WHITE
from playgo.sgf import SgfGame


@pytest.fixture
def review_env(tmp_path, monkeypatch):
    sgf = SgfGame(
        size=9,
        komi=6.5,
        black_name="黑方",
        white_name="白方",
        moves=[(BLACK, 1), (WHITE, 0), (BLACK, 9), (WHITE, None)],
    )
    (tmp_path / "sample.sgf").write_text(sgf.to_sgf(), encoding="utf-8")
    monkeypatch.setattr(settings, "RECORDS_DIR", tmp_path)
    app_state = main.AppState()
    app_state.emit_state = Mock()
    monkeypatch.setattr(main, "state", app_state)
    return app_state


@pytest.mark.parametrize("moves", [0, 1, 3, 4])
def test_takeover_any_position_and_return_source(review_env, moves):
    snap = asyncio.run(main.review_takeover(main.TakeoverReq(file="sample.sgf", moves=moves)))
    assert snap["mode"] == "pvp"
    assert snap["status"] == "playing"
    assert snap["ai_color"] is None
    assert snap["size"] == 9
    assert snap["komi"] == 6.5
    assert snap["names"] == {"black": "黑方", "white": "白方"}
    assert snap["review_source"] == {"file": "sample.sgf", "moves": moves}
    assert len(snap["moves"]) == moves
    assert snap["clocks"]["1"]["display"] == -1
    assert snap["clocks"]["2"]["display"] == -1
    if moves >= 3:
        assert snap["board"][0] == 0  # 前缀中的提子正确恢复
        assert snap["captures"]["black"] == 1
    game = review_env.game
    for point in (40, 41):  # 黑白双方均可手动行棋
        game.play(game.to_play, point)
    game.resign(game.to_play)
    with pytest.MonkeyPatch.context() as patch:
        save = Mock()
        patch.setattr(main, "save_record", save)
        asyncio.run(main.finalize_game())
        save.assert_not_called()


def test_invalid_takeover_keeps_current_game_and_ai(review_env, tmp_path):
    current = GameSession(GameConfig())
    review_env.game = current
    ai_task = Mock()
    ai_task.done.return_value = False
    review_env._ai_task = ai_task
    invalid = SgfGame(moves=[(BLACK, 0), (WHITE, 0)])
    (tmp_path / "invalid.sgf").write_text(invalid.to_sgf(), encoding="utf-8")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.review_takeover(main.TakeoverReq(file="invalid.sgf", moves=2)))
    assert exc.value.status_code == 400
    assert review_env.game is current
    ai_task.cancel.assert_not_called()


def test_review_hint_uses_prefix_size_komi_and_cache(review_env):
    ana = Analysis(
        WHITE,
        0.7,
        2.0,
        [0.0] * 81,
        [
            {"point": 40 + i, "winrate_black": 0.7, "score_lead_black": 2.0, "order": i}
            for i in range(7)
        ],
    )
    review_env.engine.ensure_started = AsyncMock(return_value=SimpleNamespace(is_gpu=False))
    review_env.engine.analyze = AsyncMock(return_value=ana)
    first = asyncio.run(main.review_hint("sample.sgf", 3))
    second = asyncio.run(main.review_hint("sample.sgf", 3))
    assert first == second
    assert first["to_play"] == WHITE
    assert first["move_count"] == 3
    assert first["moves"][0]["winrate_black"] == 0.7  # DTO 保持黑方视角
    assert [move["point"] for move in first["moves"]] == [40, 41, 42, 43, 44]
    review_env.engine.analyze.assert_awaited_once_with(
        [(BLACK, 1), (WHITE, 0), (BLACK, 9)],
        to_move=WHITE,
        max_visits=settings.HINT_VISITS_CPU,
        size=9,
        komi=6.5,
    )


@pytest.mark.parametrize("territory", [False, True])
@pytest.mark.parametrize("change", ["move", "takeover"])
def test_inflight_analysis_keeps_original_position_and_does_not_cache(
    review_env,
    territory,
    change,
):
    async def scenario():
        original = GameSession(GameConfig(size=9, komi=6.5))
        review_env.game = original
        started, release = asyncio.Event(), asyncio.Event()

        async def analyze(moves, **kwargs):
            assert moves == []
            assert kwargs["size"] == 9
            assert kwargs["komi"] == 6.5
            started.set()
            await release.wait()
            return Analysis(BLACK, 0.7, 2.0, [0.0] * 81)

        review_env.engine.ensure_started = AsyncMock(return_value=SimpleNamespace(is_gpu=False))
        review_env.engine.analyze = analyze
        endpoint = main.territory if territory else main.hint
        task = asyncio.create_task(endpoint())
        await started.wait()
        if change == "takeover":
            review_env.game = GameSession(GameConfig(size=13, komi=0.5))
        else:
            original.play(BLACK, 40)
        release.set()
        response = await task
        assert response["move_count"] == 0
        if not territory:
            assert response["to_play"] == BLACK
        assert review_env._hint_cache is None
        assert review_env._terr_cache is None

    asyncio.run(scenario())


def test_repeated_takeovers_have_different_game_ids():
    assert GameSession(GameConfig()).id != GameSession(GameConfig()).id


def setup_review_engine(app_state, *, gpu=False):
    calls = []

    async def analyze(moves, **kwargs):
        calls.append((list(moves), kwargs))
        return Analysis(kwargs["to_move"], 0.6 + len(moves) * 0.01, 2.0, [0.0] * 81)

    engine = SimpleNamespace(
        is_gpu=gpu,
        model=Path("gpu-model" if gpu else "cpu-model"),
        backend="opencl" if gpu else "eigen",
        analyze=analyze,
    )
    app_state.engine.engine = engine
    app_state.engine.ensure_started = AsyncMock(return_value=engine)
    app_state.broadcast = AsyncMock()
    return engine, calls


@pytest.mark.parametrize("gpu", [False, True])
def test_review_budget_prefixes_and_progressive_curve(review_env, tmp_path, gpu):
    async def scenario():
        _engine, calls = setup_review_engine(review_env, gpu=gpu)
        await main.review_analyze(main.ReviewReq(file="sample.sgf"))
        await review_env.review_jobs["sample.sgf"]["task"]
        budget = settings.DIFFICULTY_PRESETS["max"]["visits" if gpu else "cpu_visits"]
        assert len(calls) == 5
        for n, (hist, kwargs) in enumerate(calls):
            assert hist == [(BLACK, 1), (WHITE, 0), (BLACK, 9), (WHITE, None)][:n]
            assert kwargs == {
                "to_move": WHITE if n % 2 else BLACK,
                "max_visits": budget,
                "size": 9,
                "komi": 6.5,
            }
        events = [call.args[0] for call in review_env.broadcast.await_args_list]
        assert [event["position"]["n"] for event in events[:-1]] == list(range(5))
        assert [event["done"] for event in events[:-1]] == [1, 2, 3, 4, 5]
        assert all(event["visits"] == budget for event in events[:-1])
        assert events[-1]["type"] == "review_done"
        data = json.loads((tmp_path / "sample.analysis.json").read_text(encoding="utf-8"))
        assert data["visits"] == budget
        assert data["perspective"] == "black"
        assert data["positions"][1]["winrate_black"] == 0.61  # 轮白走也不翻转
        assert review_env.review_jobs["sample.sgf"]["progress"] == 5
        assert (await main.record_detail("sample.sgf"))["analysis"] == data

    asyncio.run(scenario())


@pytest.mark.parametrize("change", [None, "force", "budget", "model", "record", "legacy"])
def test_review_reuses_sufficient_cache_and_upgrades_old_results(review_env, tmp_path, change):
    async def run(force=False):
        await main.review_analyze(main.ReviewReq(file="sample.sgf", force=force))
        await review_env.review_jobs["sample.sgf"]["task"]

    async def scenario():
        _engine, calls = setup_review_engine(review_env)
        await run()
        path = tmp_path / "sample.analysis.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        if change == "budget":
            data["visits"] = 64
        elif change == "model":
            data["model"] = "old-model"
        elif change == "record":
            data["record_mtime_ns"] -= 1
        elif change == "legacy":
            del data["model"]
        path.write_text(json.dumps(data), encoding="utf-8")
        await run(force=change == "force")
        assert len(calls) == (5 if change is None else 10)

    asyncio.run(scenario())


def test_review_duplicate_request_restores_progress_without_duplicate_search(review_env):
    async def scenario():
        engine, calls = setup_review_engine(review_env)
        original = engine.analyze
        started, release = asyncio.Event(), asyncio.Event()

        async def analyze(moves, **kwargs):
            if moves:
                started.set()
                await release.wait()
            return await original(moves, **kwargs)

        engine.analyze = analyze
        await main.review_analyze(main.ReviewReq(file="sample.sgf"))
        await started.wait()
        response = await main.review_analyze(main.ReviewReq(file="sample.sgf"))
        assert response["already_running"]
        assert response["progress"] == 1
        assert len(response["analysis"]["positions"]) == 1
        release.set()
        await review_env.review_jobs["sample.sgf"]["task"]
        assert len(calls) == 5

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["switch", "error"])
def test_review_interruption_keeps_previous_saved_curve(review_env, tmp_path, failure):
    async def scenario():
        engine, _calls = setup_review_engine(review_env)
        await main.review_analyze(main.ReviewReq(file="sample.sgf"))
        await review_env.review_jobs["sample.sgf"]["task"]
        saved = (tmp_path / "sample.analysis.json").read_bytes()

        async def analyze(*args, **kwargs):
            if failure == "error":
                raise EngineError(code="engine.exited")
            review_env.engine.engine = object()
            return Analysis(BLACK, 0.2, -2.0, [0.0] * 81)

        engine.analyze = analyze
        await main.review_analyze(main.ReviewReq(file="sample.sgf", force=True))
        await review_env.review_jobs["sample.sgf"]["task"]
        assert (tmp_path / "sample.analysis.json").read_bytes() == saved
        assert review_env.broadcast.await_args.args[0]["type"] == "review_error"
        assert "analysis" not in review_env.review_jobs["sample.sgf"]

    asyncio.run(scenario())
