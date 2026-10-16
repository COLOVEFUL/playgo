"""围棋规则引擎测试。"""

import pytest

from playgo.rules import BLACK, EMPTY, WHITE, Board, IllegalMove, opponent


def pt(b: Board, x: int, y: int) -> int:
    return y * b.size + x


# ── 基础落子与提子 ──────────────────────────────────────


def test_place_and_occupy():
    b = Board()
    b.play(BLACK, pt(b, 3, 3))
    assert b.color_at(pt(b, 3, 3)) == BLACK
    with pytest.raises(IllegalMove) as ei:
        b.play(WHITE, pt(b, 3, 3))
    assert ei.value.code == "move.occupied"
    assert ei.value.params == {"point": pt(b, 3, 3)}


def test_out_of_bounds():
    b = Board()
    with pytest.raises(IllegalMove) as ei:
        b.play(BLACK, 999)
    assert ei.value.code == "move.out_of_bounds"
    assert ei.value.params == {"point": 999}


def test_capture_single_stone():
    b = Board()
    # 黑 (1,0)，白四面围住 → 提黑
    b.play(BLACK, pt(b, 1, 0))
    b.play(WHITE, pt(b, 0, 0))
    b.play(BLACK, pt(b, 18, 18))  # 黑随便走一手
    b.play(WHITE, pt(b, 2, 0))
    b.play(BLACK, pt(b, 18, 17))
    r = b.play(WHITE, pt(b, 1, 1))
    assert r.captured == [pt(b, 1, 0)]
    assert b.color_at(pt(b, 1, 0)) == EMPTY
    assert b.captures[WHITE] == 1


def test_capture_group():
    b = Board()
    # 黑二连 (0,1),(1,1)；白五点围死后提二子
    b.play(BLACK, pt(b, 0, 1))
    b.play(BLACK, pt(b, 1, 1))
    fillers = iter([(10, 10), (11, 11), (12, 12), (13, 13)])
    for xy in [(0, 0), (1, 0), (2, 1), (0, 2), (1, 2)]:
        if xy != (1, 2):
            b.play(BLACK, pt(b, *next(fillers)))
        b.play(WHITE, pt(b, *xy))
    assert b.captures[WHITE] == 2
    assert b.color_at(pt(b, 0, 1)) == EMPTY
    assert b.color_at(pt(b, 1, 1)) == EMPTY


def test_suicide_illegal():
    b = Board()
    # 黑围出 (0,0) 空点后，白入 (0,0) 自杀
    b.play(BLACK, pt(b, 1, 0))
    b.play(WHITE, pt(b, 18, 18))
    b.play(BLACK, pt(b, 0, 1))
    with pytest.raises(IllegalMove) as ei:
        b.play(WHITE, pt(b, 0, 0))
    assert ei.value.code == "move.suicide"
    assert b.color_at(pt(b, 0, 0)) == EMPTY  # 状态未变


def test_multi_stone_suicide_illegal():
    b = Board()
    # 黑占住 (2,0),(0,1),(1,1)，白先后入 (0,0),(1,0) 成无气二连 → 自杀
    for i, xy in enumerate([(2, 0), (0, 1), (1, 1), (2, 1)]):
        b.play(BLACK, pt(b, *xy))
        b.play(WHITE, pt(b, 10 + i, 10))
    b.play(BLACK, pt(b, 10, 5))
    b.play(WHITE, pt(b, 0, 0))  # 仅剩 (1,0) 一口气，合法
    b.play(BLACK, pt(b, 10, 6))
    with pytest.raises(IllegalMove):
        b.play(WHITE, pt(b, 1, 0))  # 二连无气 → 自杀


# ── 劫 ──────────────────────────────────────────────────


def test_ko_immediate_recapture_illegal():
    b = Board()
    # 经典劫形（直接摆子）：
    #   黑: (0,1),(1,0),(1,2)          —— 围住白劫子的三颗黑子
    #   白: (1,1)劫子 + (3,1),(2,0),(2,2) —— 白边界，使黑提子后仅剩一口气
    for xy in [(0, 1), (1, 0), (1, 2)]:
        b.grid[pt(b, *xy)] = BLACK
    for xy in [(1, 1), (3, 1), (2, 0), (2, 2)]:
        b.grid[pt(b, *xy)] = WHITE
    b._pos_keys.clear()
    b._pos_keys.add((bytes(b.grid), BLACK))

    r = b.play(BLACK, pt(b, 2, 1))  # 黑提白(1,1)
    assert r.captured == [pt(b, 1, 1)]

    with pytest.raises(IllegalMove) as ei:
        b.play(WHITE, pt(b, 1, 1))  # 立即回提 → 重现局面 → 非法
    assert ei.value.code == "move.superko"

    b.play(WHITE, pt(b, 10, 10))  # 白先寻劫材
    b.play(BLACK, pt(b, 10, 11))
    r2 = b.play(WHITE, pt(b, 1, 1))  # 此时回提合法
    assert r2.captured == [pt(b, 2, 1)]


def test_superko_prevents_cycle():
    b = Board()
    # 三劫循环类局面构造复杂，这里验证 pos_keys 机制：
    # 同一 (局面, 行棋方) 不可能第二次出现
    key0 = (bytes(b.grid), BLACK)
    b.play(BLACK, pt(b, 3, 3))
    b.play(WHITE, pt(b, 15, 15))
    assert key0 in b._pos_keys
    # 棋盘恢复不可能（没有提子），机制由劫测试覆盖
    assert b.move_count == 2


# ── 停一手与终局 ────────────────────────────────────────


def test_two_passes_end():
    b = Board()
    b.play(BLACK, None)
    b.play(WHITE, None)
    assert b.is_over_by_passes()
    b.play(BLACK, pt(b, 3, 3))
    assert not b.is_over_by_passes()


def test_pass_then_move_resets():
    b = Board()
    b.play(BLACK, None)
    b.play(WHITE, pt(b, 3, 3))
    b.play(BLACK, None)
    assert not b.is_over_by_passes()


# ── 数子（中国规则） ────────────────────────────────────


def test_score_empty_board():
    b = Board(komi=7.5)
    s = b.score()
    assert s.black_area == 0
    assert s.white_area == 7.5
    assert s.winner == WHITE
    assert s.margin == 7.5


def test_score_simple_territory():
    b = Board(size=5, komi=0)
    # 黑占 (0,0)，围住整个角落? 5路盘黑连成一道墙到边太费手，直接摆子：
    # 黑占第一行整行 + 第一列整行 → 左上大块归黑
    for x in range(5):
        b.grid[pt(b, x, 0)] = BLACK
    for y in range(5):
        b.grid[pt(b, 0, y)] = WHITE  # 注意 (0,0) 最终为白
    b._pos_keys.clear()
    s = b.score()
    # 黑：第一行 4 子((0,0)被白覆盖)；白：第一列 5 子。其余空点接壤双色 → 中立
    assert s.black_area == 4
    assert s.white_area == 5
    assert s.winner == WHITE


def test_score_with_dead_stones():
    b = Board(size=5, komi=0)
    # 白一子死在黑包围中
    for x in range(5):
        b.grid[pt(b, x, 0)] = BLACK
    for y in range(1, 5):
        b.grid[pt(b, 0, y)] = BLACK
    b.grid[pt(b, 2, 2)] = WHITE  # 白死子
    b._pos_keys.clear()
    s = b.score(dead_stones={pt(b, 2, 2)})
    # 黑: 9子 + 死子点(2,2)归黑 + 空点若只接黑归黑
    assert s.winner == BLACK
    assert s.ownership[pt(b, 2, 2)] == BLACK


def test_komi_decides():
    b = Board(size=5, komi=0.5)
    s = b.score()
    assert s.winner == WHITE
    assert s.margin == 0.5


# ── 杂项 ────────────────────────────────────────────────


def test_opponent():
    assert opponent(BLACK) == WHITE
    assert opponent(WHITE) == BLACK


def test_legal_moves_excludes_suicide_and_ko():
    b = Board()
    b.play(BLACK, pt(b, 1, 0))
    b.play(WHITE, pt(b, 18, 18))
    b.play(BLACK, pt(b, 0, 1))
    moves = b.legal_moves(WHITE)
    assert pt(b, 0, 0) not in moves  # 自杀点
    assert pt(b, 5, 5) in moves
