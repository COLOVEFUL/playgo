"""引擎冒烟测试：启动 OpenCL → 空盘分析 → 校验符号约定与选点。

用法: uv run python scripts/smoke_engine.py
"""

import asyncio
import sys
import time

sys.path.insert(0, "src")

from playgo.katago import EngineManager, from_kata_coords, to_kata_coords
from playgo.rules import BLACK


def test_coords() -> None:
    # (x=3,y=3) 19路 → KataGo "D16"；pass 已在别处覆盖
    assert to_kata_coords(3 + 3 * 19) == "D16", to_kata_coords(3 + 3 * 19)
    assert to_kata_coords(15 + 2 * 19) == "Q17"
    assert from_kata_coords("D16") == 3 + 3 * 19
    assert from_kata_coords("Q17") == 15 + 2 * 19
    print("[OK] 坐标转换")


async def main() -> None:
    test_coords()
    mgr = EngineManager()
    t0 = time.monotonic()
    engine = await mgr.ensure_started()
    print(f"[OK] 引擎就绪 {engine.describe()} 用时 {time.monotonic() - t0:.1f}s")

    # 空盘分析（首次含 OpenCL 调优）
    t0 = time.monotonic()
    ana = await engine.analyze([], to_move=BLACK, max_visits=40)
    dt = time.monotonic() - t0
    print(
        f"[OK] 空盘分析 {dt:.1f}s 黑胜率={ana.winrate_black:.3f} "
        f"目差={ana.score_lead_black:+.1f} visits={ana.visits}"
    )
    top = ana.best_moves[:3]
    for m in top:
        print(
            f"     候选 order={m['order']} point={m['point']} "
            f"prior={m['prior']:.3f} 黑胜率={m['winrate_black']:.3f}"
        )
    assert 0.25 < ana.winrate_black < 0.65, f"空盘黑胜率异常: {ana.winrate_black}"
    assert top, "应有候选着法"
    # 星位/小目一类点位（空盘 KataGo 最优通常是角部）
    assert all(0 <= m["point"] < 361 for m in top)

    # 下了几手后再分析，验证 ownership 符号（黑棋区域应为正）
    moves = [(BLACK, 3 + 3 * 19), (3 - BLACK, 15 + 15 * 19), (BLACK, 15 + 3 * 19)]
    moves = [(1, 3 + 3 * 19), (2, 15 + 15 * 19), (1, 15 + 3 * 19)]
    t0 = time.monotonic()
    ana2 = await engine.analyze(moves, to_move=2, max_visits=40)
    own = ana2.ownership
    near_black_corner = own[2 + 2 * 19]  # 黑星位(3,3)附近
    near_white_corner = own[16 + 16 * 19]  # 白星位(16,16)附近
    print(
        f"[OK] 3手后分析 {time.monotonic() - t0:.1f}s 黑角ownership={near_black_corner:+.2f} "
        f"白角ownership={near_white_corner:+.2f}"
    )
    assert near_black_corner > 0.2, "黑棋角部 ownership 应为正（黑视角归一化）"
    assert near_white_corner < -0.2, "白棋角部 ownership 应为负"

    # AI 选点（各难度）
    for diff in ("easy", "medium", "hard"):
        t0 = time.monotonic()
        pt, _ = await engine.pick_move(moves[:2], to_move=1, difficulty=diff)
        print(f"[OK] {diff} 选点 {pt} 用时 {time.monotonic() - t0:.1f}s")

    await mgr.shutdown()
    print("全部通过 ✅")


if __name__ == "__main__":
    asyncio.run(main())
