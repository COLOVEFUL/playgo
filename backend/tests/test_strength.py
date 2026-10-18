"""快速等级算法：关键着保护、收官、估计等级顺序与完整策略抽样。"""

from unittest.mock import Mock

import pytest

from playgo import strength


def test_stronger_rank_samples_more_candidates():
    for legal in (30, 100, 361):
        counts = [strength.candidate_count(k, legal) for k in (15, 10, 5, 1, 0, -2)]
        assert counts == sorted(counts)
        assert 1 <= counts[0] <= counts[-1] <= legal


def test_obvious_move_is_preserved(monkeypatch):
    sample = Mock()
    monkeypatch.setattr(strength.random, "sample", sample)
    assert strength.quick_move([0.95, 0.03, 0.01, 0.01], {0, 1, 2}, 15) == 0
    sample.assert_not_called()


def test_rank_uses_full_legal_policy_not_search_candidates(monkeypatch):
    policy = [0.001] * 362
    policy[0], policy[10], policy[-1] = 0.15, 0.01, 0.0
    policy[1] = -1  # 引擎非法点
    sample = Mock(return_value=[(10, 0.01), (200, 0.001)])
    monkeypatch.setattr(strength.random, "sample", sample)
    assert strength.quick_move(policy, set(range(2, 361)) | {0}, 15) == 10
    choices = sample.call_args.args[0]
    assert (200, 0.001) in choices
    assert all(p != 1 for p, _ in choices)
    assert sample.call_args.args[1] == strength.candidate_count(15, 360)


@pytest.mark.parametrize("legal", [set(), {0, 1}])
def test_quick_pass_when_top_policy_is_pass_or_no_legal_moves(legal):
    assert strength.quick_move([0.1, 0.1, 0.8], legal, 15) is None
