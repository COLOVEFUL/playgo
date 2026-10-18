"""快速等级：适配 KaTrain 的 Calibrated Rank 策略，仅标估计棋力。

公式与关键着保护参考 sanderland/katrain/core/ai.py 的 RankStrategy（MIT），
其校准不直接转移到 PlayGo 的不同模型；许可见 docs/licenses/KATRAIN-LICENSE.txt。
"""

import math
import random


def candidate_count(kyu: int, legal_count: int, area: int = 361) -> int:
    fraction = legal_count / area
    original = 0.063015 + 0.7624 * area / 10 ** (-0.05737 * kyu + 1.9482)
    exponent = 3.002 * fraction**2 - fraction - 0.034889 * kyu - 0.5097
    adjusted = (0.3931 + 0.6559 * fraction * math.exp(-(exponent**2)) - 0.01093 * kyu) * original
    return min(legal_count, max(1, round(legal_count / (1.31165 * (adjusted + 1) - 0.082653))))


def quick_move(policy: list[float], legal: set[int], kyu: int) -> int | None:
    """均匀无放回抽候选后取最大策略概率；关键着/收官保护避免明显随手棋。"""
    ranked = sorted(
        ((p, w) for p, w in enumerate(policy[:-1]) if p in legal and math.isfinite(w) and w > 0),
        key=lambda x: x[1],
        reverse=True,
    )
    if not ranked:
        return None
    pass_weight = max(0.0, policy[-1])
    top, probability = ranked[0]
    if pass_weight >= probability:
        return None
    fraction = len(ranked) / (len(policy) - 1)
    override = 0.8 * (1 - 0.5 * (1 - fraction))
    top_two = sum(weight for _, weight in ranked[:2])
    pass_in_top_five = sum(weight > pass_weight for _, weight in ranked) < 5
    if pass_in_top_five or probability > override or top_two > 0.85 + max(0, 0.02 * (kyu - 8)):
        return top
    count = candidate_count(kyu, len(ranked), len(policy) - 1)
    point, weight = max(random.sample(ranked, count), key=lambda x: x[1])
    return top if weight < pass_weight else point
