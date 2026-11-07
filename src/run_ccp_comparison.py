"""Full paired S6 versus CCP comparison using the existing Qwen experiment pipeline."""

import argparse
import hashlib
import json
import math
import shutil
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from random import Random

import run_selective_template as existing

ARMS = {
    "S6": "chat_inject_qwen3_with_utility_system_multiturn_7",
    "CCP": "chat_inject_qwen3_ccp",
}


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def evaluate(job):
    usage = existing.worker[1]
    before = usage.copy()
    try:
        row = existing.evaluate(job)
    except Exception as exc:
        row = {
            "arm": job[0], "case": list(job[1]), "utility": False,
            "attack_success": False, "error": True, "error_type": type(exc).__name__,
        }
    row["usage"] = {key: usage[key] - before[key] for key in usage}
    return row


def paired_summary(cases, results):
    valid = [case for case in cases if all(
        (arm, case) in results and not results[arm, case]["error"] for arm in ARMS
    )]
    arms = {}
    for arm in ARMS:
        rows = [results[arm, case] for case in valid]
        successes = sum(row["attack_success"] for row in rows)
        utilities = sum(row["utility"] for row in rows)
        arms[arm] = {
            "n": len(rows), "attack_successes": successes, "utility_successes": utilities,
            "asr_pct": 100 * successes / len(rows) if rows else None,
            "utility_pct": 100 * utilities / len(rows) if rows else None,
            "error_cases": sum(results.get((arm, case), {}).get("error", False) for case in cases),
        }
    ccp_only = sum(results["CCP", case]["attack_success"] and not results["S6", case]["attack_success"] for case in valid)
    s6_only = sum(results["S6", case]["attack_success"] and not results["CCP", case]["attack_success"] for case in valid)
    both = sum(results["S6", case]["attack_success"] and results["CCP", case]["attack_success"] for case in valid)
    discordant = ccp_only + s6_only
    pvalue = min(1.0, 2 * sum(math.comb(discordant, k) for k in range(min(ccp_only, s6_only) + 1)) / 2 ** discordant) if discordant else 1.0
    difference = (ccp_only - s6_only) / len(valid) if valid else None
    interval = None
    if len(valid) > 1:
        variance = ((ccp_only + s6_only) - len(valid) * difference ** 2) / (len(valid) - 1)
        margin = 1.959963984540054 * math.sqrt(max(0, variance) / len(valid))
        interval = [100 * max(-1, difference - margin), 100 * min(1, difference + margin)]
    return {
        "planned_pairs": len(cases), "complete_error_free_pairs": len(valid),
        "excluded_pairs": len(cases) - len(valid), "arms": arms,
        "CCP_minus_S6_asr_percentage_points": 100 * difference if difference is not None else None,
        "paired_normal_95pct_ci_percentage_points": interval,
        "mcnemar_exact_two_sided_p": pvalue,
        "both_success": both, "CCP_only_success": ccp_only, "S6_only_success": s6_only,
        "neither_success": len(valid) - both - discordant,
    }


def finalize(output, cases, results, attempts, plan):
    groups = {"overall": cases, **{
        name: [case for case in cases if case[0] == name] for name in existing.SUITES
    }}
    summary = {
        "plan": plan,
        "denominator": "Paired cases with error-free final episodes in both arms. Excluded pairs and error counts are reported explicitly.",
        "groups": {name: paired_summary(group, results) for name, group in groups.items()},
        "usage_including_retries": {key: sum(row["usage"].get(key, 0) for row in attempts) for key in ("calls", "prompt_tokens", "completion_tokens", "errors")},
        "attempts": len(attempts), "final_episodes": len(results),
    }
    write_json(output / "summary.json", summary)
    lines = [
        "# S6 与 CCP 正式配对对照", "",
        f"模型为 `{existing.MODEL.value}`，AgentDojo `{existing.VERSION}`。temperature 0，关闭思考模式，无额外防御。",
        "本实验为单模型、单次运行。ASR 为 AgentDojo 攻击目标评分，Utility 为真实用户任务完成评分。",
        "两组均有效的配对样本用于比较。错误样本会重试一次，最终仍出错的配对另行列出。", "",
        "| 范围 | 有效配对 / 计划配对 | S6 ASR | CCP ASR | CCP−S6 百分点 | S6 Utility | CCP Utility | S6 / CCP 错误数 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, group in summary["groups"].items():
        a, b = group["arms"]["S6"], group["arms"]["CCP"]
        def rate(row, metric, count):
            return f'{row[metric]:.2f}% ({row[count]}/{row["n"]})' if row["n"] else "无有效样本"
        delta = group["CCP_minus_S6_asr_percentage_points"]
        lines.append(f'| {name} | {a["n"]}/{group["planned_pairs"]} | {rate(a, "asr_pct", "attack_successes")} | {rate(b, "asr_pct", "attack_successes")} | {delta:+.2f} | {rate(a, "utility_pct", "utility_successes")} | {rate(b, "utility_pct", "utility_successes")} | {a["error_cases"]}/{b["error_cases"]} |' if delta is not None else f'| {name} | 0/{group["planned_pairs"]} | 无有效样本 | | | | | |')
    overall = summary["groups"]["overall"]
    lines.extend(["", f'仅 CCP 成功 {overall["CCP_only_success"]} 例，仅 S6 成功 {overall["S6_only_success"]} 例，两组均成功 {overall["both_success"]} 例，两组均失败 {overall["neither_success"]} 例。',
                  f'配对 McNemar 精确双侧 p 值为 {overall["mcnemar_exact_two_sided_p"]:.6g}。',
                  f'ASR 差值的配对正态近似 95% 置信区间（百分点）为 {overall["paired_normal_95pct_ci_percentage_points"]}。',
                  "", "实验标签为全量 Qwen 单次配对对照。结果的推广范围受模型、任务集及单次运行限制。",
                  "逐次尝试记录见 episodes.jsonl，最终逐例记录见 final_episodes.json，原始对话见 logs/，错误尝试备份见 failed_attempts/。"])
    (output / "comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_json(output / "final_episodes.json", list(results.values()))
    print(json.dumps(summary["groups"], ensure_ascii=False, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=421)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("workers must be positive")
    root = Path(__file__).resolve().parent.parent
    cases = []
    for suite_name in existing.SUITES:
        suite = existing.get_suite(existing.VERSION, suite_name)
        cases.extend((suite_name, user, goal) for user in sorted(suite.user_tasks) for goal in sorted(suite.injection_tasks))
    source_paths = ["src/run_ccp_comparison.py", "src/run_selective_template.py", "src/agentdojo/task_suite/task_suite.py", "src/agentdojo/attacks/baseline_attacks.py", "src/agentdojo/attacks/multi_turn_data/ccp_multiturn_7_generation_output.json", "src/agentdojo/attacks/multi_turn_data/with_utility_multi_turn_7_generation_output.json"]
    plan = dict(model=existing.MODEL.value, benchmark_version=existing.VERSION,
                temperature=0.0, enable_thinking=False, defense=None, repetitions=1,
                seed=args.seed, arms=ARMS, cases=[list(case) for case in cases],
                source_sha256={path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in source_paths})
    output = args.output.resolve()
    ledger_path = output / "episodes.jsonl"
    attempts = []
    results = {}
    jobs = [(arm, case) for case in cases for arm in ARMS]
    if args.resume:
        if json.loads((output / "plan.json").read_text()) != plan:
            parser.error("Stored plan or source hashes differ from this run")
        for line in ledger_path.read_text().splitlines():
            row = json.loads(line)
            key = (row["arm"], tuple(row["case"]))
            if key not in jobs:
                parser.error("Unexpected ledger episode")
            results[key] = row
            attempts.append(row)
    else:
        output.mkdir(parents=True, exist_ok=False)
        write_json(output / "plan.json", plan)
    existing.load_api_keys()
    if not existing.os.getenv("DASHSCOPE_API_KEY"):
        parser.error("DashScope key is missing")
    rng = Random(args.seed)
    rng.shuffle(jobs)
    with ledger_path.open("a", encoding="utf-8", buffering=1) as ledger:
        for attempt in range(2):
            pending = [job for job in jobs if job not in results or (results[job]["error"] and results[job]["attempt"] < attempt)]
            if not pending:
                continue
            for arm, case in pending:
                if (arm, case) in results:
                    path = output / "logs" / existing.MODEL.value / case[0] / case[1] / ARMS[arm] / (case[2] + ".json")
                    if path.exists():
                        backup = output / "failed_attempts" / arm / case[0] / case[1] / (case[2] + ".json")
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(path, backup)
            print(f"START attempt={attempt} pending={len(pending)} total={len(jobs)} workers={args.workers}", flush=True)
            with ProcessPoolExecutor(args.workers, initializer=existing.init_worker, initargs=(output, ARMS)) as pool:
                futures = {pool.submit(evaluate, job): job for job in pending}
                for future in as_completed(futures):
                    row = future.result()
                    row["attempt"] = attempt
                    results[futures[future]] = row
                    attempts.append(row)
                    ledger.write(json.dumps(row) + "\n")
                    write_json(output / "progress.json", dict(completed=len(results), planned=len(jobs), attempts=len(attempts), errors=sum(row["error"] for row in results.values())))
                    if len(attempts) % 10 == 0 or row["error"]:
                        print(f"PROGRESS completed={len(results)}/{len(jobs)} attempts={len(attempts)} latest_error={row['error']}", flush=True)
    finalize(output, cases, results, attempts, plan)


if __name__ == "__main__":
    main()
