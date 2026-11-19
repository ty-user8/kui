"""bootstrap 的单元测试：区间覆盖、判定口径、百分位。"""

from __future__ import annotations

import unittest

from src.eval.bootstrap import paired_bootstrap, percentiles, verdict


class TestBootstrap(unittest.TestCase):
    def test_identical_groups_interval_straddles_zero(self):
        values = [1.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0]
        interval = paired_bootstrap(values, values, rounds=500)
        self.assertAlmostEqual(interval["mean"], 0.0)
        self.assertLessEqual(interval["lower"], 0.0)
        self.assertGreaterEqual(interval["upper"], 0.0)
        self.assertEqual(verdict(interval), "overlap")

    def test_clear_improvement_is_significant(self):
        baseline = [0.0] * 40
        candidate = [1.0] * 40
        interval = paired_bootstrap(baseline, candidate, rounds=500)
        self.assertAlmostEqual(interval["mean"], 1.0)
        self.assertEqual(verdict(interval), "improved")

    def test_clear_degradation_is_negative(self):
        interval = paired_bootstrap([1.0] * 40, [0.0] * 40, rounds=500)
        self.assertEqual(verdict(interval), "degraded")

    def test_mismatched_length_raises(self):
        with self.assertRaises(ValueError):
            paired_bootstrap([1.0, 0.0], [1.0])

    def test_deterministic_with_same_seed(self):
        left = [1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0]
        right = [1.0, 1.0, 1.0, 0.0, 1.0, 1.0, 1.0, 0.0]
        first = paired_bootstrap(left, right, rounds=300, seed=7)
        second = paired_bootstrap(left, right, rounds=300, seed=7)
        self.assertEqual(first, second)


class TestPercentiles(unittest.TestCase):
    def test_p50_p95(self):
        values = [float(i) for i in range(1, 101)]
        stats = percentiles(values)
        self.assertAlmostEqual(stats["p50"], 51.0)
        self.assertAlmostEqual(stats["p95"], 95.0)

    def test_empty_returns_none(self):
        self.assertIsNone(percentiles([])["p50"])


if __name__ == "__main__":
    unittest.main()
