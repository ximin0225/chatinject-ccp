"""ChatInject 复现实验 runner
==============================

在 AgentDojo (v1.2.1, banking/travel/slack 三域) 上以指定攻击方法运行基准测试，
结果写入 ../results/<run_name>/。

用法（在 src/ 目录下执行）:
    python run_experiments.py --attack injecagent                    # 全量 389 例
    python run_experiments.py --attack chat_inject_deepseek -i 3     # 每域前 3 个注入任务（省费用子集）
    python run_experiments.py --list                                 # 列出可用攻击

API key 从项目根目录 ../api_key.txt 读取（格式: "deepseek: sk-xxx"，每行一个）。
也可用环境变量 DEEPSEEK_API_KEY / ZHIPU_API_KEY / DASHSCOPE_API_KEY 覆盖。
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KEY_FILE = PROJECT_ROOT / "api_key.txt"
RESULTS_DIR = PROJECT_ROOT / "results"

# 各 provider 可用的模型（OpenAI 兼容直连）
PROVIDER_MODELS = {
    "deepseek": "deepseek-chat",
    "zhipu": "glm-4.5",
    "dashscope": "qwen3-235b-a22b",
}


def load_api_keys() -> None:
    """从 api_key.txt 读取 key 并导出为环境变量（已存在的环境变量优先）。"""
    if not KEY_FILE.exists():
        return
    env_map = {"deepseek": "DEEPSEEK_API_KEY", "glm": "ZHIPU_API_KEY", "zhipu": "ZHIPU_API_KEY",
               "qwen": "DASHSCOPE_API_KEY", "dashscope": "DASHSCOPE_API_KEY"}
    for line in KEY_FILE.read_text().splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        provider, key = line.split(":", 1)
        env_name = env_map.get(provider.strip().lower())
        if env_name and key.strip() and not os.getenv(env_name):
            os.environ[env_name] = key.strip()


def install_usage_tracker(log_path: Path) -> dict:
    """给 OpenAILLM 的请求函数打补丁，累计 token 用量与调用次数（用于成本核算）。"""
    from agentdojo.agent_pipeline.llms import openai_llm

    usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
             "prompt_cache_hit_tokens": 0, "errors": 0}

    def wrapped(client, model, messages, tools, reasoning_effort, temperature=0.0, extra_body=None):
        try:
            resp = openai_llm._orig_chat_completion_request(
                client, model, messages, tools, reasoning_effort, temperature, extra_body)
        except Exception:
            usage["errors"] += 1
            raise
        usage["calls"] += 1
        if getattr(resp, "usage", None) is not None:
            u = resp.usage
            usage["prompt_tokens"] += getattr(u, "prompt_tokens", 0) or 0
            usage["completion_tokens"] += getattr(u, "completion_tokens", 0) or 0
            # DeepSeek 返回的缓存命中字段（其他 provider 无此字段则为 0）
            pd = getattr(u, "prompt_cache_hit_tokens", 0)
            usage["prompt_cache_hit_tokens"] += pd or 0
        return resp

    if not hasattr(openai_llm, "_orig_chat_completion_request"):
        openai_llm._orig_chat_completion_request = openai_llm.chat_completion_request
        openai_llm.chat_completion_request = wrapped
    return usage


def flush_usage(usage: dict, path: Path) -> None:
    path.write_text(json.dumps(usage, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--attack", type=str, default="injecagent", help="攻击名（--list 查看）")
    parser.add_argument("--model", type=str, default="deepseek-chat", help="目标模型")
    parser.add_argument("--provider", type=str, default="deepseek", choices=list(PROVIDER_MODELS))
    parser.add_argument("-s", "--suites", type=str, nargs="+", default=["banking", "travel", "slack"])
    parser.add_argument("-i", "--injection-tasks", type=int, default=0,
                        help=">0 时每域仅运行前 N 个注入任务（省钱子集）；0 为全量")
    parser.add_argument("--run-name", type=str, default=None, help="结果目录名（默认 model_attack）")
    parser.add_argument("--benchmark-version", type=str, default="v1.2.1")
    parser.add_argument("--force-rerun", action="store_true")
    parser.add_argument("--list", action="store_true", help="列出可用攻击后退出")
    args = parser.parse_args()

    load_api_keys()

    from agentdojo.attacks.attack_registry import ATTACKS
    from agentdojo.models import ModelsEnum
    from agentdojo.scripts.benchmark import benchmark_suite
    from agentdojo.task_suite.load_suites import get_suite

    if args.list:
        print("可用攻击:", sorted(ATTACKS))
        return

    if args.provider not in PROVIDER_MODELS or PROVIDER_MODELS[args.provider] != args.model:
        # 允许自定义 model id，但默认校验 provider 匹配
        if args.model not in [m.value for m in ModelsEnum]:
            print(f"[warn] {args.model} 不在 ModelsEnum 中，尝试直接使用")

    run_name = args.run_name or f"{args.model.replace('/', '_')}_{args.attack}"
    out_dir = RESULTS_DIR / run_name
    out_dir.mkdir(parents=True, exist_ok=True)
    usage_log = out_dir / "usage.json"
    usage = install_usage_tracker(usage_log)

    # 注入任务子集（确定性选取：按 ID 排序取前 N）
    injection_tasks = None
    if args.injection_tasks > 0:
        injection_tasks = {}

    print(f"=== run: {run_name} | suites: {args.suites} ===")
    t0 = time.time()
    all_results = {}
    for suite_name in args.suites:
        suite = get_suite(args.benchmark_version, suite_name)
        inj_ids = None
        if args.injection_tasks > 0:
            inj_ids = tuple(sorted(suite.injection_tasks.keys())[: args.injection_tasks])
            print(f"[subset] {suite_name}: injection tasks {inj_ids}")
        results = benchmark_suite(
            suite,
            ModelsEnum(args.model),
            logdir=out_dir / "logs",
            force_rerun=args.force_rerun,
            benchmark_version=args.benchmark_version,
            attack=args.attack,
            injection_tasks=inj_ids or (),
        )
        n_util = len(results["utility_results"])
        n_sec = len(results["security_results"])
        util = 100 * sum(results["utility_results"].values()) / n_util if n_util else float("nan")
        asr = 100 * sum(results["security_results"].values()) / n_sec if n_sec else float("nan")
        print(f"[{suite_name}] utility={util:.1f}% (n={n_util})  ASR={asr:.1f}% (n={n_sec})")
        all_results[suite_name] = {
            "n_utility": n_util,
            "n_security": n_sec,
            "utility_pct": round(util, 2) if n_util else None,
            "asr_pct": round(asr, 2) if n_sec else None,
        }
        flush_usage(usage, usage_log)

    # 汇总（按样本量加权）
    tot_util = sum(r["n_utility"] for r in all_results.values())
    tot_sec = sum(r["n_security"] for r in all_results.values())
    summary = {
        "run_name": run_name,
        "model": args.model,
        "provider": args.provider,
        "attack": args.attack,
        "benchmark_version": args.benchmark_version,
        "suites": args.suites,
        "injection_subset": args.injection_tasks or "all",
        "per_suite": all_results,
        "elapsed_sec": round(time.time() - t0, 1),
        "usage": usage,
    }
    if tot_util:
        summary["utility_pct_weighted"] = round(
            sum(r["utility_pct"] * r["n_utility"] for r in all_results.values()) / tot_util, 2)
    if tot_sec:
        summary["asr_pct_weighted"] = round(
            sum(r["asr_pct"] * r["n_security"] for r in all_results.values()) / tot_sec, 2)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    flush_usage(usage, usage_log)
    print(json.dumps({k: v for k, v in summary.items() if k != "per_suite"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
