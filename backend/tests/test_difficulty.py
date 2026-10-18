"""段级位策略、协议、旧档位迁移与失败隔离（无需真实引擎）。"""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from playgo import katago, main, settings
from playgo.game import GameConfig, GameSession
from playgo.katago import Analysis, EngineError, KataGoEngine
from playgo.rules import BLACK, WHITE


def analysis(**kwargs):
    return Analysis(
        to_move=WHITE,
        winrate_black=0.5,
        score_lead_black=0,
        ownership=[0.0] * 361,
        **kwargs,
    )


def engine():
    return KataGoEngine(Path("unused"), Path("unused"), "eigen")


def test_rank_order_and_aliases():
    ranks = list(settings.DIFFICULTY_PRESETS)
    assert ranks == ["20k", "15k", "10k", "5k", "1k", "1d", "3d", "5d", "7d", "9d", "max"]
    assert settings.normalize_difficulty("easy") == "15k"
    assert settings.normalize_difficulty("medium") == "1d"
    assert settings.normalize_difficulty("hard") == "max"


def test_human_samples_full_policy_without_temperature_or_pass(monkeypatch):
    policy = [-1.0] * 362
    policy[0], policy[5], policy[200], policy[361] = 0.5, 0.2, 0.01, 0.29
    policy[10], policy[11] = float("nan"), float("inf")
    choose = Mock(return_value=[200])
    monkeypatch.setattr(katago.random, "choices", choose)
    ana = analysis(human_policy=policy)
    assert engine()._choose(ana, settings.DIFFICULTY_PRESETS["10k"], {5, 10, 11, 200}) == 200
    choose.assert_called_once_with((5, 200), weights=(0.2, 0.01), k=1)


@pytest.mark.parametrize("rank", ["20k", "1d", "9d", "max"])
def test_engine_best_pass_is_honored(rank):
    ana = analysis(top_is_pass=True, human_policy=[1.0] * 362, best_moves=[{"point": 3}])
    assert engine()._choose(ana, settings.DIFFICULTY_PRESETS[rank], {3}) is None


@pytest.mark.parametrize("policy", [[], [0.0] * 361, [0.0] * 362])
def test_invalid_human_policy_never_falls_back_to_best(policy):
    ana = analysis(human_policy=policy, best_moves=[{"point": 3}])
    with pytest.raises(EngineError) as exc:
        engine()._choose(ana, settings.DIFFICULTY_PRESETS["10k"], {3})
    assert exc.value.code == "engine.human_policy_missing"


def test_normalization_retains_best_pass_and_human_policy():
    data = {
        "humanPolicy": [0.1] * 362,
        "moveInfos": [
            {"move": "C6", "order": 1, "winrate": 0.5, "scoreLead": 0},
            {"move": "pass", "order": 0},
        ],
    }
    ana = engine()._normalize(data, WHITE, 19)
    assert ana.top_is_pass
    assert ana.human_policy == [0.1] * 362
    assert len(ana.best_moves) == 1  # 推荐 DTO 仍不含 pass


def test_pick_uses_human_profile_and_filters_occupied_points(monkeypatch):
    eng = engine()
    eng.human_model = Path("human.bin.gz")
    policy = [0.0] * 362
    policy[0], policy[3] = 0.9, 0.1
    eng.analyze = AsyncMock(return_value=analysis(human_policy=policy))
    choose = Mock(return_value=[3])
    monkeypatch.setattr(katago.random, "choices", choose)
    point, _ = asyncio.run(eng.pick_move([(BLACK, 0)], WHITE, "medium", size=19, komi=6.5))
    assert point == 3
    eng.analyze.assert_awaited_once_with(
        [(BLACK, 0)],
        to_move=WHITE,
        max_visits=64,
        size=19,
        komi=6.5,
        human_profile="rank_1d",
        include_policy=False,
    )
    choose.assert_called_once_with((3,), weights=(0.1,), k=1)


def test_human_query_has_per_request_settings_and_does_not_bias_hint():
    async def run():
        eng = engine()
        eng.ready = True
        sent = []

        def write(raw):
            payload = json.loads(raw)
            sent.append(payload)
            eng._handle_stdout_line(json.dumps({"id": payload["id"], "rootInfo": {}}))

        eng.proc = SimpleNamespace(stdin=SimpleNamespace(write=write, drain=AsyncMock()))
        await eng.analyze([], to_move=WHITE, max_visits=64, human_profile="rank_20k", komi=0.5)
        await eng.analyze([], to_move=BLACK, max_visits=80, size=9, komi=6.5)
        assert sent[0]["includePolicy"] is True
        assert sent[0]["overrideSettings"] == {
            "humanSLProfile": "rank_20k",
            "ignorePreRootHistory": False,
        }
        assert sent[0]["initialPlayer"] == "W"
        assert sent[0]["komi"] == 0.5
        assert "includePolicy" not in sent[1]
        assert "overrideSettings" not in sent[1]
        assert sent[1]["boardXSize"] == 9

    asyncio.run(run())


@pytest.mark.parametrize(
    ("difficulty", "code"),
    [
        ("bogus", "game.bad_difficulty"),
        ("10k", "engine.human_model_required"),
    ],
)
def test_invalid_new_game_preserves_current_game_and_ai(monkeypatch, difficulty, code):
    app_state = main.AppState()
    app_state.game = GameSession(GameConfig())
    old = app_state.game
    app_state._ai_task = Mock()
    app_state._ai_task.done.return_value = False
    app_state.engine.status = Mock(return_value={"human_sl": {"installed": False}})
    monkeypatch.setattr(main, "state", app_state)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            main.new_game(main.NewGameReq(mode="ai", difficulty=difficulty, ai_style="human"))
        )
    assert isinstance(exc.value.detail, dict)
    assert exc.value.detail["code"] == code
    assert app_state.game is old
    app_state._ai_task.cancel.assert_not_called()


def test_new_game_alias_normalizes_snapshot_and_sgf(monkeypatch):
    app_state = main.AppState()
    app_state.emit_state = Mock()
    app_state.schedule_ai = Mock()
    app_state.engine.status = Mock(return_value={"human_sl": {"installed": True}})
    monkeypatch.setattr(main, "state", app_state)
    snap = asyncio.run(main.new_game(main.NewGameReq(mode="ai", difficulty="easy")))
    assert snap["difficulty"] == "15k"
    assert app_state.game is not None
    assert snap["ai_style"] == "rank"
    assert app_state.game.to_sgf().white_name == "KataGo (15k, rank)"


def test_download_progress_from_worker_thread(monkeypatch):
    async def run():
        app_state = main.AppState()
        app_state.broadcast = AsyncMock()
        app_state.engine.restart = AsyncMock()
        app_state.schedule_ai = Mock()
        monkeypatch.setattr(main, "state", app_state)

        def start(ids, cb):
            async def download():
                await asyncio.to_thread(cb, {"id": "human-model", "phase": "done"})

            app_state.downloads.task = asyncio.create_task(download())

        monkeypatch.setattr(app_state.downloads, "start", start)
        await main.engine_download(main.DownloadReq(ids=["human-model"]))
        assert app_state.downloads.task is not None
        await app_state.downloads.task
        await asyncio.sleep(0)
        assert any(
            call.args[0].get("type") == "download" for call in app_state.broadcast.await_args_list
        )

    asyncio.run(run())


def test_quick_mode_requires_no_human_model_and_uses_one_visit(monkeypatch):
    eng = engine()
    eng.human_model = None
    policy = [0.0] * 362
    policy[5] = 1.0
    eng.analyze = AsyncMock(return_value=analysis(policy=policy))
    point, _ = asyncio.run(eng.pick_move([], BLACK, "10k", style="rank"))
    assert point == 5
    assert eng.analyze.call_args.kwargs["max_visits"] == 1
    assert eng.analyze.call_args.kwargs["include_policy"] is True
    assert eng.analyze.call_args.kwargs["human_profile"] is None


@pytest.mark.parametrize("rank", ["20k", "5d", "7d", "9d"])
def test_quick_mode_rejects_extrapolated_ranks(rank):
    with pytest.raises(EngineError) as exc:
        asyncio.run(engine().pick_move([], BLACK, rank, style="rank"))
    assert exc.value.code == "game.quick_rank_unavailable"


def test_invalid_quick_policy_does_not_pass_silently():
    eng = engine()
    eng.analyze = AsyncMock(return_value=analysis(policy=[0.0] * 362))
    with pytest.raises(EngineError) as exc:
        asyncio.run(eng.pick_move([], BLACK, "10k", style="rank"))
    assert exc.value.code == "engine.policy_missing"
