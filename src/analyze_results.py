"""汇总复现实验结果，生成报告用对比表（CSV + 控制台输出）

数据来源：
  ../results/deepseek-chat_<attack>/{banking,travel,slack}.json   复现结果（本脚本前置于 CLI 输出）
  ../results/deepseek-chat_noattack/                              无攻击 benign utility
  ../data/official_eval_results/                                  官方（论文）原始实验输出

论文 Table 1（AgentDojo 部分）数值以常量内置，用于对照；注释标明出处页码。
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS = PROJECT_ROOT / "results"
OFFICIAL = PROJECT_ROOT / "data" / "official_eval_results"

SUITES = ["banking", "travel", "slack"]
N_PER_SUITE = {"banking": 144, "travel": 140, "slack": 105}  # v1.2.1: 16×9, 20×7, 21×5

# 攻击设置 -> 目录名 / 论文 Table 1 对应列名
RUNS = {
    "injecagent": ("Default InjecPrompt", "deepseek-chat_injecagent"),
    "chat_inject_deepseek": ("ChatInject(原生模板)", "deepseek-chat_chat_inject_deepseek"),
    "chat_inject_deepseek_think": ("ChatInject+think", "deepseek-chat_chat_inject_deepseek_think"),
    "chat_inject_deepseek_tool": ("ChatInject+tool", "deepseek-chat_chat_inject_deepseek_tool"),
    "injecagent_with_utility_system_multiturn_7": ("Default Multi-turn", "deepseek-chat_injecagent_with_utility_system_multiturn_7"),
    "chat_inject_deepseek_with_utility_system_multiturn_7": ("Multi-turn+ChatInject", "deepseek-chat_chat_inject_deepseek_with_utility_system_multiturn_7"),
    "chat_inject_qwen3": ("ChatInject(Qwen-3外来模板)", "deepseek-chat_chat_inject_qwen3"),
    "noattack": ("无攻击(benign)", "deepseek-chat_noattack"),
}

# 论文 Table 1 AgentDojo ASR（%），六个开源模型：default / ChatInject / +think / +tool / MT-default / MT+ChatInject
PAPER_TABLE1_ASR = {
    "Qwen-3":  [17.5, 54.8, 66.1, 69.4, 60.9, 80.5],
    "GPT-oss": [0.3, 51.4, 48.6, 47.4, 3.6, 55.5],
    "Llama-4": [1.0, 17.2, None, 19.8, 1.8, 11.1],
    "GLM-4.5": [0.3, 20.3, 24.8, 36.0, 17.5, 48.1],
    "Kimi-K2": [5.9, 29.3, None, 44.2, 12.3, 13.9],
    "Grok-2":  [6.1, 19.3, None, None, 23.7, 24.7],
}
# 论文 Table 1 / Table 4 AgentDojo Utility（%）：benign / default / ChatInject / +think / +tool / MT-default / MT+ChatInject
PAPER_UTILITY = {
    "Qwen-3":  [80.7, 50.9, 28.3, 24.4, 22.9, 52.4, 27.5],
    "GPT-oss": [66.7, 19.6, 18.8, 11.1, 9.0, 38.3, 8.0],
    "Llama-4": [22.8, 16.5, 15.9, None, 14.7, 18.5, 16.2],
    "GLM-4.5": [86.0, 78.4, 67.9, 65.7, 68.1, 75.8, 67.9],
    "Kimi-K2": [77.2, 71.5, 35.0, None, 35.2, 72.0, 69.9],
    "Grok-2":  [47.4, 41.7, 29.8, None, None, 33.9, 31.9],
}


def load_run(dirname: str) -> dict:
    """读取一次运行的 per-suite 结果 JSON，返回 {suite: {asr, utility, n}}。"""
    out = {}
    for s in SUITES:
        p = RESULTS / dirname / f"{s}.json"
        if not p.exists():
            out[s] = None
            continue
        j = json.loads(p.read_text())
        out[s] = {
            "asr": j.get("average_asr"),
            "utility": j.get("utility_under_attack", j.get("benign_utility")),
            "n_util": j.get("total_tasks"),
            "n_sec": j.get("total_security_tasks"),
        }
    return out


def weighted(dirname: str, key: str) -> float | None:
    per = load_run(dirname)
    num = den = 0
    for s, r in per.items():
        if r is None or r.get(key) is None:
            continue
        n = r.get("n_sec") if key == "asr" else r.get("n_util")
        num += r[key] * n
        den += n
    return round(num / den, 2) if den else None


def error_scan(dirname: str) -> int:
    """统计带 error 字段的 episode 日志数（用于复现差异说明与补跑判断）。"""
    logs = RESULTS / dirname / "logs"
    if not logs.exists():
        return -1
    n = 0
    for f in logs.rglob("*.json"):
        try:
            j = json.loads(f.read_text())
        except Exception:
            continue
        if j.get("error"):
            n += 1
    return n


def episode_count(dirname: str) -> int:
    logs = RESULTS / dirname / "logs"
    return len(list(logs.rglob("*.json"))) if logs.exists() else 0


def main() -> None:
    print("=" * 100)
    print(f"{'设置':<32}{'banking':>10}{'travel':>10}{'slack':>10}{'加权ASR':>10}{'加权Utility':>12}{'episodes':>10}{'errors':>8}")
    print("-" * 100)
    for atk, (label, dirname) in RUNS.items():
        per = load_run(dirname)
        cells = []
        for s in SUITES:
            r = per[s]
            if atk == "noattack":
                cells.append(f"{r['utility']:.1f}" if r and r.get("utility") is not None else "--")
            else:
                cells.append(f"{r['asr']:.1f}" if r and r.get("asr") is not None else "--")
        asr = weighted(dirname, "asr") if atk != "noattack" else None
        util = weighted(dirname, "utility")
        print(f"{label:<32}{cells[0]:>10}{cells[1]:>10}{cells[2]:>10}"
              f"{(f'{asr:.1f}' if asr is not None else '--'):>10}"
              f"{(f'{util:.1f}' if util is not None else '--'):>12}"
              f"{episode_count(dirname):>10}{error_scan(dirname):>8}")

    print()
    print("论文 Table 1 (AgentDojo, ASR%): default / ChatInject / +think / +tool / MT / MT+CI")
    for m, row in PAPER_TABLE1_ASR.items():
        print(f"  {m:<10}", " / ".join("--" if v is None else f"{v:5.1f}" for v in row))


# --------------------------------------------------------------------------
# [chatinject-ext] 2026-11 增补：跨模型对照（deepseek-chat / glm-5.3-flash / qwen3.7-flash）
# 每个模型一套原生模板攻击矩阵 + 共用的明文/明文多轮/无攻击设置。
SET_COLS = ["S1明文", "S2原生CI", "S3+think", "S4+tool", "S5明文MT", "S6MT+CI", "S7外来模板"]

MODEL_MATRIX = {
    "deepseek-chat": {
        "S1明文": "deepseek-chat_injecagent",
        "S2原生CI": "deepseek-chat_chat_inject_deepseek",
        "S3+think": "deepseek-chat_chat_inject_deepseek_think",
        "S4+tool": "deepseek-chat_chat_inject_deepseek_tool",
        "S5明文MT": "deepseek-chat_injecagent_with_utility_system_multiturn_7",
        "S6MT+CI": "deepseek-chat_chat_inject_deepseek_with_utility_system_multiturn_7",
        "S7外来模板": "deepseek-chat_chat_inject_qwen3",
        "S0无攻击": "deepseek-chat_noattack",
    },
    "glm-5.3-flash": {
        "S1明文": "glm-5.3-flash_injecagent",
        "S2原生CI": "glm-5.3-flash_chat_inject_glm5",
        "S3+think": "glm-5.3-flash_chat_inject_glm5_think",
        "S4+tool": "glm-5.3-flash_chat_inject_glm5_tool",
        "S5明文MT": "glm-5.3-flash_injecagent_with_utility_system_multiturn_7",
        "S6MT+CI": "glm-5.3-flash_chat_inject_glm5_with_utility_system_multiturn_7",
        "S7外来模板": "glm-5.3-flash_chat_inject_qwen3",
        "S0无攻击": "glm-5.3-flash_noattack",
    },
    "qwen3.7-flash": {
        "S1明文": "qwen3.7-flash_injecagent",
        "S2原生CI": "qwen3.7-flash_chat_inject_qwen3",
        "S3+think": "qwen3.7-flash_chat_inject_qwen3_think",
        "S4+tool": "qwen3.7-flash_chat_inject_qwen3_tool",
        "S5明文MT": "qwen3.7-flash_injecagent_with_utility_system_multiturn_7",
        "S6MT+CI": "qwen3.7-flash_chat_inject_qwen3_with_utility_system_multiturn_7",
        "S7外来模板": "qwen3.7-flash_chat_inject_glm",
        "S0无攻击": "qwen3.7-flash_noattack",
    },
}


def compare_models() -> None:
    """跨模型 ASR/Utility 对照表：行=模型，列=八设置。"""
    print()
    print("=" * 100)
    print("跨模型对照（AgentDojo v1.2.1 三域加权，%）")
    print(f"{'模型':<16}" + "".join(f"{c:>12}" for c in SET_COLS) + f"{'S0良性Util':>12}")
    print("-" * 100)
    for model, dirs in MODEL_MATRIX.items():
        cells = []
        for col in SET_COLS:
            v = weighted(dirs[col], "asr")
            cells.append("--" if v is None else f"{v:.1f}")
        b = weighted(dirs["S0无攻击"], "utility")
        print(f"{model:<16}" + "".join(f"{c:>12}" for c in cells) + f"{('--' if b is None else f'{b:.1f}'):>12}")
    print()
    print("加权 Utility（攻击下）：")
    print(f"{'模型':<16}" + "".join(f"{c:>12}" for c in SET_COLS))
    print("-" * 100)
    for model, dirs in MODEL_MATRIX.items():
        cells = []
        for col in SET_COLS:
            v = weighted(dirs[col], "utility")
            cells.append("--" if v is None else f"{v:.1f}")
        print(f"{model:<16}" + "".join(f"{c:>12}" for c in cells))
    print()
    print("完整性核对（episodes / 错误数）：")
    for model, dirs in MODEL_MATRIX.items():
        for col in ["S0无攻击"] + SET_COLS:
            d = dirs[col]
            print(f"  {model:<16}{col:<12}{episode_count(d):>5} 集, 错误 {error_scan(d)}")


if __name__ == "__main__" and "--compare" in sys.argv:
    compare_models()
elif __name__ == "__main__":
    main()
