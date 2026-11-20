"""CI 回归判定（REQ-036）：复现一致 → `run_id` 未变 → 指标无退化。

判定顺序照需求逐条来，任何一条不满足即非零退出：
1. 同一配置连跑两次，最后两个 `attempt-N/metrics.json` 必须逐字节一致——不一致说明
   复现性破了（`run_id` 相同却出两套数，比退化更严重，先报这个）；
2. 本次 `metrics.json` 的 `run_id` 必须等于基准 `run_id`；变了说明语料/用例/切分/模型
   等进入规范串的字段被改过，属有意变更，须走变更单重定基线（REQ-037），而不是在 CI 里放过；
3. 计数型指标（Recall@k、HitRate@k）相对基准**任何下降**即 fail；连续型（MRR、nDCG@5）
   允许 1e-6 浮点容差。指标变好不算 fail。

基准存 `evals/baseline.json`（随仓库走，CI 与本地同一份）。

判失败时每条原因都带 `::error::` 前缀（GitHub workflow command），CI 上直接进 run 的
annotation，页面上不登录也能看到是哪一条不满足（①/②/③）与具体数值。

用法（项目根目录下）：
    set RAG_DB_PATH=data\\rag.db
    set HF_HOME=.cache/models
    .venv\\Scripts\\python.exe scripts/ci_check.py            # 跑两次评测再判定
    .venv\\Scripts\\python.exe scripts/ci_check.py --skip-run # 只校验已有 attempt
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
COUNT_METRICS = ("recall@1", "recall@3", "recall@5", "hitrate@5")
CONTINUOUS_METRICS = ("mrr", "ndcg@5")
TOLERANCE = 1e-6


def fail(message: str) -> None:
    """输出判失败原因。

    前面加 GitHub workflow command 前缀 ``::error::``：在 CI 里这行会变成 run 的
    annotation（无需登录读 job 日志即可看到失败分支与数值），本地运行时则原样打印
    ``::error::FAIL：…``，人眼一样能读。按 GitHub 要求转义 ``%``／回车／换行。
    """
    text = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print("::error::" + text)


def load_baseline(path: pathlib.Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    missing = [name for name in COUNT_METRICS + CONTINUOUS_METRICS if name not in payload.get("metrics", {})]
    if missing:
        raise SystemExit("基准文件缺少指标：%s" % ", ".join(missing))
    return payload


def compare_metrics(actual: dict, expected: dict, tolerance: float = TOLERANCE) -> list[str]:
    """返回退化清单（空表示通过）。计数型零容忍，连续型给浮点容差。"""
    problems: list[str] = []
    for name in COUNT_METRICS:
        if name not in actual:
            problems.append("%s 缺失" % name)
            continue
        if actual[name] < expected[name]:
            problems.append(
                "计数型退化 %s：%.6f < 基准 %.6f（降 %.6f）"
                % (name, actual[name], expected[name], expected[name] - actual[name])
            )
    for name in CONTINUOUS_METRICS:
        if name not in actual:
            problems.append("%s 缺失" % name)
            continue
        if actual[name] < expected[name] - tolerance:
            problems.append(
                "连续型退化 %s：%.6f < 基准 %.6f（超容差 %.1e）"
                % (name, actual[name], expected[name], tolerance)
            )
    return problems


def attempt_dirs(run_dir: pathlib.Path) -> list[pathlib.Path]:
    def index_of(path: pathlib.Path) -> int:
        suffix = path.name.split("-")[-1]
        return int(suffix) if suffix.isdigit() else 0

    candidates = [path for path in run_dir.glob("attempt-*") if path.is_dir()]
    return sorted(candidates, key=index_of)


def run_eval_once(extra_args: list[str] | None = None) -> int:
    command = [sys.executable, "-m", "src.cli.eval", *(extra_args or [])]
    print("运行：%s" % " ".join(command))
    return subprocess.call(command, cwd=str(PROJECT_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="CI 回归判定：复现一致、run_id 未变、指标无退化")
    parser.add_argument("--baseline", default="evals/baseline.json")
    parser.add_argument("--runs", type=int, default=2, help="重跑评测的次数（默认 2，用于复现比对）")
    parser.add_argument("--skip-run", action="store_true", help="不重跑，只校验已有 attempt 目录")
    parser.add_argument("--eval-args", default="", help="传给 src.cli.eval 的额外参数，空格分隔")
    args = parser.parse_args()

    baseline = load_baseline(PROJECT_ROOT / args.baseline)
    run_id = baseline["run_id"]

    if not args.skip_run:
        extra = args.eval_args.split()
        for _ in range(max(2, args.runs)):
            code = run_eval_once(extra)
            if code != 0:
                fail("FAIL ⓪：评测命令退出码 %d" % code)
                return 1

    run_dir = PROJECT_ROOT / "data" / "runs" / run_id
    attempts = attempt_dirs(run_dir)
    if len(attempts) < 2:
        fail("FAIL ①：%s 下只有 %d 个 attempt，无法做复现比对" % (run_dir, len(attempts)))
        fail("若 run_id 已变，说明配置/用例改动未按 REQ-037 走变更单重定基线")
        return 1

    latest, previous = attempts[-1], attempts[-2]
    latest_bytes = (latest / "metrics.json").read_bytes()
    previous_bytes = (previous / "metrics.json").read_bytes()
    if latest_bytes != previous_bytes:
        fail("FAIL ①：%s 与 %s 的 metrics.json 不一致（复现性被破坏）" % (previous.name, latest.name))
        return 1
    print("PASS ①：%s 与 %s 的 metrics.json 逐字节一致（%d 字节）" % (previous.name, latest.name, len(latest_bytes)))

    payload = json.loads(latest_bytes.decode("utf-8"))
    if payload.get("run_id") != run_id:
        fail("FAIL ②：本次 run_id=%s 与基准 %s 不同，须走变更单重定基线" % (payload.get("run_id"), run_id))
        return 1
    print("PASS ②：run_id 未变（%s）" % run_id)

    problems = compare_metrics(payload["metrics"], baseline["metrics"])
    if problems:
        fail("FAIL ③：指标退化 %d 项" % len(problems))
        for item in problems:
            fail("- %s" % item)
        return 1
    print(
        "PASS ③：六项指标无退化（R@1 %.4f / @3 %.4f / @5 %.4f / MRR %.4f / nDCG@5 %.4f / HitRate@5 %.4f）"
        % tuple(
            payload["metrics"][name]
            for name in ("recall@1", "recall@3", "recall@5", "mrr", "ndcg@5", "hitrate@5")
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
