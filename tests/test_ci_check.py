"""CI 回归判定的单测：计数型零容忍、连续型容差、缺指标、attempt 排序。"""

from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from scripts.ci_check import CONTINUOUS_METRICS, COUNT_METRICS, attempt_dirs, compare_metrics, load_baseline

BASE = {
    "recall@1": 0.56,
    "recall@3": 0.86,
    "recall@5": 0.90,
    "hitrate@5": 0.90,
    "mrr": 0.7045,
    "ndcg@5": 0.754284,
}


class TestCompare(unittest.TestCase):
    def test_identical_passes(self):
        self.assertEqual(compare_metrics(dict(BASE), BASE), [])

    def test_improvement_passes(self):
        better = dict(BASE, **{"recall@5": 0.91, "mrr": 0.71, "ndcg@5": 0.76})
        self.assertEqual(compare_metrics(better, BASE), [])

    def test_count_metric_any_drop_fails(self):
        for name in COUNT_METRICS:
            worse = dict(BASE)
            worse[name] = BASE[name] - 0.000001
            problems = compare_metrics(worse, BASE)
            self.assertEqual(len(problems), 1, name)
            self.assertIn("计数型退化", problems[0])
            self.assertIn(name, problems[0])

    def test_continuous_metric_within_tolerance_passes(self):
        nudged = dict(BASE, mrr=BASE["mrr"] - 5e-7, **{"ndcg@5": BASE["ndcg@5"] - 9e-7})
        self.assertEqual(compare_metrics(nudged, BASE), [])

    def test_continuous_metric_beyond_tolerance_fails(self):
        for name in CONTINUOUS_METRICS:
            worse = dict(BASE)
            worse[name] = BASE[name] - 1e-5
            problems = compare_metrics(worse, BASE)
            self.assertEqual(len(problems), 1, name)
            self.assertIn("连续型退化", problems[0])

    def test_missing_metric_fails(self):
        broken = dict(BASE)
        del broken["hitrate@5"]
        self.assertIn("hitrate@5 缺失", compare_metrics(broken, BASE))


class TestBaselineFile(unittest.TestCase):
    def test_loads_repo_baseline(self):
        payload = load_baseline(pathlib.Path("evals/baseline.json"))
        self.assertEqual(payload["run_id"], "r31a95a0e1de6")
        self.assertEqual(payload["case_count"], 100)
        for name in COUNT_METRICS + CONTINUOUS_METRICS:
            self.assertIn(name, payload["metrics"])

    def test_missing_metric_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "baseline.json"
            path.write_text(json.dumps({"run_id": "x", "metrics": {"recall@1": 1.0}}), encoding="utf-8")
            with self.assertRaises(SystemExit):
                load_baseline(path)


class TestAttemptDirs(unittest.TestCase):
    def test_numeric_order_not_lexicographic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            for name in ("attempt-10", "attempt-2", "attempt-1"):
                (root / name).mkdir()
            self.assertEqual([p.name for p in attempt_dirs(root)], ["attempt-1", "attempt-2", "attempt-10"])

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(attempt_dirs(pathlib.Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
