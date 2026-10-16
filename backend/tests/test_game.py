"""对局状态机与计时读秒测试。"""

import time

import pytest

from playgo import settings
from playgo.game import MODE_AI, GameConfig, GameSession
from playgo.rules import BLACK, WHITE, IllegalMove


def test_turn_order_and_illegal():
    g = GameSession(GameConfig())
    g.play(BLACK, 3 * 19 + 3)
    with pytest.raises(IllegalMove) as ei:
        g.play(BLACK, 5 * 19 + 5)  # 黑连走
    assert ei.value.code == "game.not_your_turn"
    g.play(WHITE, 15 * 19 + 15)


def test_undo_pvp_and_ai():
    g = GameSession(GameConfig())
    g.play(BLACK, 3 * 19 + 3)
    g.play(WHITE, 15 * 19 + 15)
    assert g.undo() == 1
    assert len(g.moves) == 1
    assert g.to_play == WHITE

    cfg = GameConfig(mode=MODE_AI, human_color=BLACK)
    a = GameSession(cfg)
    a.play(BLACK, 3 * 19 + 3)  # 人
    a.play(WHITE, 15 * 19 + 15)  # AI
    assert a.undo() == 2  # 退 AI 一手 + 人一手，轮人
    assert a.to_play == BLACK


def test_timeout_byo_yomi():
    """主时 1s + 读秒 2s ×1：黑方未落子，超时判负。"""
    ts = settings.TimeSettings(main_seconds=1, byo_seconds=2, byo_periods=1)
    g = GameSession(GameConfig(time=ts))
    time.sleep(1.4)  # 黑主时耗尽 → 进入读秒
    assert g.tick()
    assert g.clocks[BLACK].in_byo
    time.sleep(2.2)  # 读秒也耗尽（仅 1 次机会）
    g.tick()
    assert g.status == "ended"
    assert g.result
    assert g.result["reason"] == "timeout"
    assert g.result["winner"] == WHITE
    assert "detail" not in g.result  # 文案由前端按 reason/winner 组合
    assert g.result["sgf_result"] == "W+T"


def test_resign_result_shape():
    g = GameSession(GameConfig())
    g.resign(BLACK)
    assert g.result == {
        "winner": WHITE,
        "reason": "resign",
        "margin": 0.0,
        "sgf_result": "W+R",
    }


def test_pass_then_scoring_flow():
    g = GameSession(GameConfig())
    g.play(BLACK, 3 * 19 + 3)
    g.pass_move(BLACK) if g.to_play == BLACK else None
    # 黑下完一手，轮白：白停、黑停
    g.pass_move(WHITE)
    g.pass_move(BLACK)
    assert g.status == "scoring"
    g.enter_scoring(set())
    # 点目预览只含数值/枚举，无显示文案
    assert "text" not in g.score_preview
    assert g.score_preview["winner"] in (BLACK, WHITE, 0)
    r = g.confirm_score()
    assert g.status == "ended"
    assert r["reason"] == "score"
    assert r["margin"] >= 0
    assert "detail" not in r
