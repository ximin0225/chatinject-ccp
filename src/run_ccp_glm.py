"""Full paired GLM S6/CCP evaluation with mandatory low-effort thinking."""

import argparse
import hashlib
import json
import os
import shutil
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from random import Random

import run_ccp_comparison as comparison
import run_selective_template as existing
from agentdojo.agent_pipeline.llms import openai_llm
from agentdojo.agent_pipeline.llms.openai_llm import OpenAILLM
from agentdojo.models import ModelsEnum

MODEL = ModelsEnum("glm-5.3-flash")
ARMS = {
    "S6": "chat_inject_glm5_with_utility_system_multiturn_7",
    "CCP": "chat_inject_glm5_ccp",
}
existing.MODEL = MODEL
comparison.ARMS = ARMS
observed_models = set()
reasoning_calls = 0
reasoning_cache = {}
provider_responses = []
reasoning_reinsertions = 0
worker_output = None


def init_worker(output):
    global worker_output
    worker_output = output
    existing.init_worker(output, ARMS)
    for element in existing.worker[2].elements:
        if isinstance(element, OpenAILLM):
            element.extra_body = {"thinking": {"type": "enabled", "clear_thinking": False}}
            element.reasoning_effort = "low"
            element.client = element.client.with_options(timeout=90, max_retries=0)
    tracked_request = openai_llm.chat_completion_request

    def record_response(client, model, messages, tools, reasoning_effort,
                        temperature=0.0, extra_body=None):
        global reasoning_calls, reasoning_reinsertions
        native_messages = []
        for message in messages:
            native = dict(message)
            if message["role"] == "assistant" and message.get("tool_calls"):
                key = tuple(call["id"] for call in message["tool_calls"])
                if key in reasoning_cache:
                    native["reasoning_content"] = reasoning_cache[key]
                    reasoning_reinsertions += 1
            native_messages.append(native)
        response = tracked_request(client, model, native_messages, tools,
                                   reasoning_effort, temperature, extra_body)
        observed_models.add(response.model)
        provider_responses.append(response.model_dump(mode="json"))
        for choice in response.choices:
            message = choice.message
            reasoning = getattr(message, "reasoning_content", None)
            reasoning_calls += int(bool(reasoning))
            if message.tool_calls:
                key = tuple(call.id for call in message.tool_calls)
                reasoning_cache[key] = reasoning or ""
        return response

    openai_llm.chat_completion_request = record_response


def evaluate(job):
    global reasoning_calls, reasoning_reinsertions
    observed_models.clear()
    reasoning_cache.clear()
    provider_responses.clear()
    reasoning_calls = 0
    reasoning_reinsertions = 0
    row = comparison.evaluate(job)
    row["response_models"] = sorted(observed_models)
    row["responses_with_reasoning_content"] = reasoning_calls
    row["reasoning_history_reinsertions"] = reasoning_reinsertions
    arm, (suite, user, goal) = job
    path = worker_output / "provider_responses" / arm / suite / user / (goal + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    comparison.write_json(path, provider_responses)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=421)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("workers must be positive")
    existing.load_api_keys()
    if not os.getenv("ZHIPU_API_KEY"):
        parser.error("GLM key is missing")
    root = Path(__file__).resolve().parent.parent
    cases = []
    for name in existing.SUITES:
        suite = existing.get_suite(existing.VERSION, name)
        users = ["user_task_0"] if args.smoke else sorted(suite.user_tasks)
        goals = [next(iter(suite.injection_tasks))] if args.smoke else sorted(suite.injection_tasks)
        cases.extend((name, user, goal) for user in users for goal in goals)
    source_paths = [
        "src/run_ccp_glm.py", "src/run_ccp_comparison.py", "src/run_selective_template.py",
        "src/agentdojo/task_suite/task_suite.py", "src/agentdojo/attacks/baseline_attacks.py",
        "src/agentdojo/agent_pipeline/agent_pipeline.py", "src/agentdojo/agent_pipeline/llms/openai_llm.py",
        "src/agentdojo/attacks/multi_turn_data/ccp_multiturn_7_generation_output.json",
        "src/agentdojo/attacks/multi_turn_data/with_utility_multi_turn_7_generation_output.json",
    ]
    plan = dict(model=MODEL.value, requested_model=MODEL.value,
                response_model_policy="Record provider response.model in every episode",
                benchmark_version=existing.VERSION, temperature=0.0, enable_thinking=True, reasoning_effort="low",
                thinking={"type": "enabled", "clear_thinking": False}, defense=None, repetitions=1,
                seed=args.seed, arms=ARMS, smoke=args.smoke, cases=[list(case) for case in cases],
                source_sha256={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in source_paths})
    output = args.output.resolve()
    ledger_path = output / "episodes.jsonl"
    jobs = [(arm, case) for case in cases for arm in ARMS]
    results, attempts = {}, []
    if args.resume:
        if json.loads((output / "plan.json").read_text()) != plan:
            parser.error("Stored plan or source hashes differ")
        for line in ledger_path.read_text().splitlines():
            row = json.loads(line)
            key = (row["arm"], tuple(row["case"]))
            if key not in jobs:
                parser.error("Unexpected ledger episode")
            results[key] = row
            attempts.append(row)
    else:
        output.mkdir(parents=True, exist_ok=False)
        comparison.write_json(output / "plan.json", plan)
    Random(args.seed).shuffle(jobs)
    with ledger_path.open("a", encoding="utf-8", buffering=1) as ledger:
        for attempt in range(2):
            pending = [job for job in jobs if job not in results or
                       (results[job]["error"] and results[job]["attempt"] < attempt)]
            if not pending:
                continue
            for arm, case in pending:
                if (arm, case) in results:
                    trace = output / "logs" / MODEL.value / case[0] / case[1] / ARMS[arm] / (case[2] + ".json")
                    if trace.exists():
                        backup = output / "failed_attempts" / arm / case[0] / case[1] / (case[2] + ".json")
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(trace, backup)
            print(f"START attempt={attempt} pending={len(pending)} total={len(jobs)} workers={args.workers}", flush=True)
            with ProcessPoolExecutor(args.workers, initializer=init_worker, initargs=(output,)) as pool:
                futures = {pool.submit(evaluate, job): job for job in pending}
                for future in as_completed(futures):
                    row = future.result()
                    row["attempt"] = attempt
                    results[futures[future]] = row
                    attempts.append(row)
                    ledger.write(json.dumps(row) + "\n")
                    comparison.write_json(output / "progress.json", dict(
                        completed=len(results), planned=len(jobs), attempts=len(attempts),
                        errors=sum(item["error"] for item in results.values())))
                    if len(attempts) % 10 == 0 or row["error"] or args.smoke:
                        print(f"PROGRESS completed={len(results)}/{len(jobs)} attempts={len(attempts)} latest_error={row['error']} models={row['response_models']}", flush=True)
    comparison.finalize(output, cases, results, attempts, plan)
    summary = json.loads((output / "summary.json").read_text())
    response_models = sorted({model for row in results.values() for model in row["response_models"]})
    summary["observed_response_models"] = response_models
    summary["responses_with_reasoning_content"] = sum(row["responses_with_reasoning_content"] for row in attempts)
    comparison.write_json(output / "summary.json", summary)
    report_path = output / "comparison.md"
    report = report_path.read_text(encoding="utf-8").replace("全量 Qwen", "GLM low 思考模式").replace("关闭思考模式", "开启思考模式，reasoning_effort=low")
    if args.smoke:
        report = report.replace("正式配对对照", "冒烟验证")
    report += f"\n请求模型为 glm-5.3-flash，实际返回标识为 {response_models}。该模型强制思考，两组都使用 reasoning_effort=low、temperature=0，保留工具调用历史中的 reasoning_content。\n"
    report_path.write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()

