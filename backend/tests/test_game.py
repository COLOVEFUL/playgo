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


def test_byo_period_refreshes_each_turn():
    """读秒周期每回合刷新：读秒内落子作废当前周期，下回合重新满额。"""
    ts = settings.TimeSettings(main_seconds=1, byo_seconds=2, byo_periods=3)
    g = GameSession(GameConfig(time=ts))
    clock = g.clocks[BLACK]
    clock.in_byo = True  # 直接置入读秒：本回合已用 0.5s，周期剩 1.5s
    clock.main = 0.0
    clock.byo_left = 1.5
    g._turn_started = time.monotonic() - 0.5
    g.play(BLACK, 3 * 19 + 3)
    # 未超时落子 → 不扣周期，且周期作废重置回满额（而非结转剩余 1.0s）
    assert clock.periods_left == 3
    assert clock.byo_left == 2.0
    assert g.moves[-1].clock_left == 2.0  # 落子后剩余时间即满额周期
    # 白方回一手后再次轮到黑：黑从满额周期起算
    g.play(WHITE, 15 * 19 + 15)
    assert g.clocks[BLACK].byo_left == 2.0


def test_byo_multi_periods_in_one_turn():
    """同一回合可连续超时多次：每次扣一个周期，最后一个周期耗尽判负。"""
    ts = settings.TimeSettings(main_seconds=1, byo_seconds=2, byo_periods=3)
    g = GameSession(GameConfig(time=ts))
    clock = g.clocks[BLACK]
    clock.in_byo = True
    clock.main = 0.0
    clock.byo_left = 2.0
    g._turn_started = time.monotonic() - 3.0  # 本手耗时 > 周期长
    assert g.tick()  # 第 1 次超时：扣 1 周期，重置满额，本回合继续
    assert clock.periods_left == 2
    assert clock.byo_left == 2.0
    assert g.status == "playing"
    g._turn_started = time.monotonic() - 3.0
    assert g.tick()  # 第 2 次
    assert clock.periods_left == 1
    assert g.status == "playing"
    g._turn_started = time.monotonic() - 3.0
    assert g.tick()  # 第 3 次 → 判负
    assert g.status == "ended"
    assert g.result["reason"] == "timeout"
    assert g.result["winner"] == WHITE


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


def test_request_scoring_and_resume():
    """对弈中主动点目：立即进入点目；拒绝结果则原样返回对弈。"""
    g = GameSession(GameConfig())
    g.play(BLACK, 3 * 19 + 3)
    g.play(WHITE, 15 * 19 + 15)
    assert g.request_scoring() is True
    assert g.status == "scoring"
    assert g.score_preview is None  # 引擎判定完成前不给出预览
    assert g.request_scoring() is False  # 已在点目，幂等
    assert g.resume() is True
    assert g.status == "playing"
    assert len(g.moves) == 2  # 手数不动
    assert g.to_play == BLACK
    assert g.resume() is False  # 非点目阶段不可 resume
    # 终局后主动点目同样无效
    g.resign(BLACK)
    assert g.request_scoring() is False


def test_undo_blocked_in_scoring():
    """点目阶段悔棋无效（先 resume 返回对弈，再按常规悔棋）。"""
    g = GameSession(GameConfig())
    g.play(BLACK, 3 * 19 + 3)
    g.request_scoring()
    assert g.undo() == 0
    assert len(g.moves) == 1


def test_pass_scoring_resume_keeps_passes():
    """双停一手进点目后拒绝结果：两次停一手保留在棋谱，再停立即重回点目。"""
    g = GameSession(GameConfig())
    g.play(BLACK, 3 * 19 + 3)
    g.pass_move(WHITE)
    g.pass_move(BLACK)
    assert g.status == "scoring"
    assert g.resume() is True
    assert g.status == "playing"
    assert len(g.moves) == 3  # 停一手不因 resume 被撤
    g.pass_move(WHITE)  # 轮白；棋盘连续停一手计数仍 ≥2，一手即重回点目
    assert g.status == "scoring"


def test_resume_not_charged_clock():
    """点目审查耗时不计入行棋方时钟（resume 后重新起算）。"""
    ts = settings.TimeSettings(main_seconds=30, byo_seconds=5, byo_periods=3)
    g = GameSession(GameConfig(time=ts))
    g.play(BLACK, 3 * 19 + 3)  # 轮白，白方回合开始计时
    g.request_scoring()
    time.sleep(0.2)  # 点目审查
    g.resume()
    g.play(WHITE, 15 * 19 + 15)
    assert g.clocks[WHITE].main > 29.9


def test_takeover_seed_and_undo():
    """复盘接管：以棋谱前缀开局（小棋盘/贴目沿用），悔棋可退入前缀。"""
    free = settings.TimeSettings(main_seconds=0, byo_seconds=0, byo_periods=0)
    cfg = GameConfig(time=free, size=13, komi=6.5, takeover=True)
    g = GameSession(cfg)
    g.seed_moves([(BLACK, 3 * 13 + 3), (WHITE, 9 * 13 + 9)])
    assert g.board.size == 13
    assert len(g.moves) == 2
    assert g.to_play == BLACK  # 前缀末手为白 → 轮黑
    snap = g.snapshot()
    assert snap["takeover"] is True
    assert snap["size"] == 13
    assert snap["komi"] == 6.5
    assert g.clocks[BLACK].unlimited  # 接管不限时
    g.play(BLACK, 5 * 13 + 5)
    assert g.undo() == 1
    assert g.to_play == BLACK
    assert g.undo() == 1  # 再悔退入棋谱前缀
    assert len(g.moves) == 1
    assert g.to_play == WHITE
