import pytest

from src.benchmarker import hit_rate_at_k, recall_at_k, mrr_at_k


def test_metric_math_known_ranking():
    rankings = [
        [True, False, False],      # RR=1
        [False, True, False],      # RR=1/2
        [False, False, False],     # RR=0
        [False, False, True],      # RR=1/3
    ]
    assert hit_rate_at_k(rankings, 3) == pytest.approx(0.75)
    assert recall_at_k(rankings, 3) == pytest.approx(0.75)
    assert mrr_at_k(rankings, 3) == pytest.approx((1 + 0.5 + 0 + 1/3) / 4)


def test_mrr_miss_outside_k_scores_zero():
    rankings = [[False, False, True]]
    assert mrr_at_k(rankings, 2) == 0.0
