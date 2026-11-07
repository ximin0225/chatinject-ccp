"""Paired ChatInject studies on simulated AgentDojo tasks."""

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from random import Random
from statistics import mean

from agentdojo.agent_pipeline.agent_pipeline import AgentPipeline, PipelineConfig
from agentdojo.attacks.attack_registry import load_attack
from agentdojo.benchmark import load_task_results, run_task_with_injection_tasks
from agentdojo.logging import OutputLogger
from agentdojo.models import ModelsEnum
from agentdojo.task_suite.load_suites import get_suite
from run_experiments import install_usage_tracker, load_api_keys

VERSION = "v1.2.1"
MODEL = ModelsEnum.DASHSCOPE_QWEN3_7_FLASH
SUITES = ("banking", "travel", "slack")
ARMS = {
    "s5_plain": "injecagent_with_utility_system_multiturn_7",
    "s6_full": "chat_inject_qwen3_with_utility_system_multiturn_7",
    "early_pair": "chat_inject_qwen3_multiturn_7_early_pair",
    "late_pair": "chat_inject_qwen3_multiturn_7_late_pair",
}


TOOL_CUE_ARMS = {
    "s6_full": ARMS["s6_full"],
    "s6_plain_tool_cue": "chat_inject_qwen3_multiturn_7_plain_tool_cue",
    "s6_wrapped_tool_cue": "chat_inject_qwen3_multiturn_7_wrapped_tool_cue",
}


STUDIES = {
    "selective": ARMS,
    "tool-cue": TOOL_CUE_ARMS,
    "tool-cue-confirm": {
        arm: TOOL_CUE_ARMS[arm] for arm in ("s6_full", "s6_wrapped_tool_cue")
    },
}


def sample_cases(suites, per_suite, rng, excluded_users=()):
    cases = []
    for name, suite in suites.items():
        # Cycle through injection goals to cover each goal before drawing another user task.
        users = sorted(user for user in suite.user_tasks if (name, user) not in excluded_users)
        goals = sorted(suite.injection_tasks)
        if not 1 <= per_suite <= len(users) * len(goals):
            raise ValueError(f"Invalid case count for {name}: {per_suite}")
        rng.shuffle(goals)
        users_by_goal = {goal: rng.sample(users, len(users)) for goal in goals}
        pairs = [(users_by_goal[goal][index], goal) for index in range(len(users)) for goal in goals]
        cases.extend((name, user, goal) for user, goal in pairs[:per_suite])
    rng.shuffle(cases)
    return cases


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def summarize(rows):
    return {
        "cases": len(rows),
        "asr_pct": round(100 * mean(row["attack_success"] for row in rows), 2),
        "utility_pct": round(100 * mean(row["utility"] for row in rows), 2),
        "joint_pct": round(100 * mean(row["attack_success"] and row["utility"] for row in rows), 2),
        "errors": sum(bool(row["error"]) for row in rows),
        "calls": sum(row["calls"] for row in rows),
        "prompt_tokens": sum(row["prompt_tokens"] for row in rows),
        "completion_tokens": sum(row["completion_tokens"] for row in rows),
    }


def init_worker(output, arms):
    global worker
    logdir = output / "logs"
    usage = install_usage_tracker(output / "usage.json")
    pipeline = AgentPipeline.from_config(
        PipelineConfig(llm=MODEL, model_id=None, defense=None,
                       system_message_name=None, system_message=None)
    )
    suites = {name: get_suite(VERSION, name) for name in SUITES}
    attacks = {
        (suite_name, arm): load_attack(attack, suite, pipeline)
        for suite_name, suite in suites.items()
        for arm, attack in arms.items()
    }
    worker = logdir, usage, pipeline, suites, attacks


def evaluate(job):
    arm, (suite_name, user_id, goal_id) = job
    logdir, usage, pipeline, suites, attacks = worker
    suite = suites[suite_name]
    user = suite.get_user_task_by_id(user_id)
    attack = attacks[suite_name, arm]
    before = usage.copy()
    with OutputLogger(str(logdir)):
        utility, success = run_task_with_injection_tasks(
            suite, pipeline, user, attack, logdir, True, (goal_id,), VERSION
        )
    case_key = (user_id, goal_id)
    trace = load_task_results(pipeline.name, suite_name, user_id, attack.name, goal_id, logdir)
    return {
        "arm": arm,
        "case": [suite_name, user_id, goal_id],
        "utility": utility[case_key],
        "attack_success": success[case_key],
        "error": bool(trace.error),
        **{key: usage[key] - before[key]
           for key in ("calls", "prompt_tokens", "completion_tokens")},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--study", choices=STUDIES, default="selective")
    parser.add_argument("--exclude-users-from", type=Path, help="Earlier plan.json to hold out its user tasks")
    parser.add_argument("--per-suite", type=int, default=12)
    parser.add_argument("--seed", type=int, default=421)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    arms = STUDIES[args.study]
    suites = {name: get_suite(VERSION, name) for name in SUITES}
    rng = Random(args.seed)
    excluded_users = set()
    if args.exclude_users_from is not None:
        prior_plan = json.loads(args.exclude_users_from.read_text(encoding="utf-8"))
        excluded_users = {(name, user) for name, user, _ in prior_plan["cases"]}
    cases = sample_cases(suites, args.per_suite, rng, excluded_users)
    plan = {
        "model": MODEL.value,
        "temperature": 0.0,
        "enable_thinking": False,
        "benchmark_version": VERSION,
        "seed": args.seed,
        "arms": arms,
        "cases": [list(case) for case in cases],
    }
    if excluded_users:
        plan["excluded_users"] = [list(pair) for pair in sorted(excluded_users)]
    if args.plan_only:
        print(json.dumps(plan, indent=2))
        return
    if args.output is None or args.workers < 1:
        parser.error("An --output directory and a positive --workers count are required")
    load_api_keys()
    if not os.getenv("DASHSCOPE_API_KEY"):
        parser.error("Configure the DashScope key in api_key.txt or DASHSCOPE_API_KEY")

    output = args.output.resolve()
    ledger_path = output / "episodes.jsonl"
    jobs = [(arm, case) for case in cases for arm in rng.sample(list(arms), len(arms))]
    results = {}
    if args.resume:
        if json.loads((output / "plan.json").read_text(encoding="utf-8")) != plan:
            parser.error("The stored plan differs from the requested plan")
        expected = set(jobs)
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            key = (row["arm"], tuple(row["case"]))
            if key not in expected or key in results:
                parser.error(f"Unexpected or duplicate episode: {key}")
            results[key] = row
    else:
        output.mkdir(parents=True, exist_ok=False)
        write_json(output / "plan.json", plan)

    pending = [job for job in jobs if job not in results]
    print(f"Completed {len(results)}/{len(jobs)} episodes; workers={args.workers}", flush=True)
    with ledger_path.open("a", encoding="utf-8", buffering=1) as ledger:
        with ProcessPoolExecutor(args.workers, initializer=init_worker, initargs=(output, arms)) as pool:
            futures = {pool.submit(evaluate, job): job for job in pending}
            try:
                for future in as_completed(futures):
                    row = future.result()
                    results[futures[future]] = row
                    ledger.write(json.dumps(row) + "\n")
                    if len(results) % len(arms) == 0:
                        print(f"Completed {len(results)}/{len(jobs)} episodes", flush=True)
            except BaseException:
                for future in futures:
                    future.cancel()
                raise

    summary = {arm: summarize([results[arm, case] for case in cases]) for arm in arms}
    write_json(output / "summary.json", summary)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
