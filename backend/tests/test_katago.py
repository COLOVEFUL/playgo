"""KataGo 封装的纯逻辑测试（不启动真实引擎）。"""

from pathlib import Path

from playgo.katago import Analysis, KataGoEngine, from_kata_coords, to_kata_coords
from playgo.rules import WHITE


def test_coord_roundtrip():
    assert to_kata_coords(3 + 3 * 19) == "D16"
    assert to_kata_coords(15 + 2 * 19) == "Q17"
    assert from_kata_coords("D16") == 3 + 3 * 19
    assert from_kata_coords("Q17") == 15 + 2 * 19


def test_auto_timeout_scales_with_visits_and_backend():
    gpu = KataGoEngine(Path("x"), Path("y"), "opencl")
    cpu = KataGoEngine(Path("x"), Path("y"), "eigen")
    assert gpu.auto_timeout(200) == 60.0  # 触及下限
    assert gpu.auto_timeout(800) == 126.0  # 30 + 800*0.12（困难档 GPU）
    assert cpu.auto_timeout(160) == 430.0  # 30 + 160*2.5（困难档 CPU 回退）


def _fake_data() -> dict:
    """黑方大优局面的引擎原始输出（reportAnalysisWinratesAs=BLACK 语义）。"""
    return {
        "rootInfo": {"winrate": 0.73, "scoreLead": 5.2, "visits": 64},
        "ownership": [0.9] * 361,
        "moveInfos": [
            {"move": "C6", "order": 1, "prior": 0.2, "winrate": 0.72, "scoreLead": 5.0},
            {"move": "Q16", "order": 0, "prior": 0.5, "winrate": 0.74, "scoreLead": 5.6},
            {"move": "pass", "order": 2, "prior": 0.01, "winrate": 0.4, "scoreLead": 0.0},
        ],
    }


def test_normalize_is_black_perspective_even_when_white_to_move():
    """引擎输出本身即黑方视角：轮白走也绝不能按行棋方翻转（历史 bug 回归测试）。"""
    eng = KataGoEngine(Path("x"), Path("y"), "eigen")
    ana = eng._normalize(_fake_data(), to_move=WHITE, size=19)
    assert isinstance(ana, Analysis)
    assert ana.winrate_black == 0.73  # 不翻转
    assert ana.score_lead_black == 5.2
    assert ana.ownership[0] == 0.9
    assert ana.to_move == WHITE  # 仅记录，不参与换算


def test_normalize_move_infos_sorted_and_pass_filtered():
    eng = KataGoEngine(Path("x"), Path("y"), "eigen")
    ana = eng._normalize(_fake_data(), to_move=WHITE, size=19)
    assert [m["point"] for m in ana.best_moves] == [
        from_kata_coords("Q16", 19),
        from_kata_coords("C6", 19),
    ]  # 按 order 排序，pass 被过滤
    assert ana.best_moves[0]["winrate_black"] == 0.74
    assert ana.best_moves[0]["score_lead_black"] == 5.6


def test_normalize_handles_missing_fields():
    eng = KataGoEngine(Path("x"), Path("y"), "eigen")
    ana = eng._normalize({}, to_move=WHITE, size=19)
    assert ana.winrate_black == 0.5
    assert ana.score_lead_black == 0.0
    assert len(ana.ownership) == 361
    assert ana.best_moves == []
