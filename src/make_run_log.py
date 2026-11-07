"""从 batch.log 与 results/ 生成实验执行记录（results/执行记录.md）

包含：每组设置的起止时间、episode 数、错误数、ASR/Utility 汇总、费用快照。
"""

import json
import re
import subprocess
import sys
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULTS = PROJECT_ROOT / "results"
BATCH_LOG = RESULTS / "logs" / "batch.log"

sys.path.insert(0, str(Path(__file__).parent))
import analyze_results as A  # noqa: E402


def balance() -> str | None:
    key = ""
    kf = PROJECT_ROOT / "api_key.txt"
    if kf.exists():
        for line in kf.read_text().splitlines():
            if line.startswith("deepseek:"):
                key = line.split(":", 1)[1].strip()
    if not key:
        return None
    try:
        out = subprocess.run(
            ["curl", "-s", "https://api.deepseek.com/user/balance",
             "-H", f"Authorization: Bearer {key}"],
            capture_output=True, text=True, timeout=20).stdout
        return json.loads(out)["balance_infos"][0]["total_balance"]
    except Exception:
        return None


def main() -> None:
    events = []  # (time, attack, kind)
    if BATCH_LOG.exists():
        for line in BATCH_LOG.read_text(errors="ignore").splitlines():
            m = re.match(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] (START|DONE)\s+attack=(\S+)", line)
            if m:
                events.append((m.group(1), m.group(3), m.group(2)))

    lines = ["# ChatInject 复现实验执行记录", ""]
    lines.append(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    cur = balance()
    if cur:
        lines.append(f"- 当前 DeepSeek 余额：¥{cur}（实验开始前为 ¥259.37）")
    lines.append("")

    lines.append("## 各设置执行情况")
    lines.append("")
    lines.append("| 攻击设置 | 开始 | 结束 | episodes | 错误 | 加权ASR% | 加权Utility% |")
    lines.append("|---|---|---|---|---|---|---|")
    for atk, (label, dirname) in A.RUNS.items():
        starts = [t for t, a, k in events if a == atk and k == "START"]
        dones = [t for t, a, k in events if a == atk and k == "DONE"]
        t0 = min(starts) if starts else "--"
        t1 = max(dones) if dones else "（未完成）"
        asr = A.weighted(dirname, "asr") if atk != "noattack" else None
        util = A.weighted(dirname, "utility")
        lines.append(
            f"| {label} | {t0} | {t1} | {A.episode_count(dirname)} | {A.error_scan(dirname)} | "
            f"{(f'{asr:.2f}' if asr is not None else '--')} | "
            f"{(f'{util:.2f}' if util is not None else '--')} |")

    lines.append("")
    lines.append("## 说明")
    lines.append("")
    lines.append("- 每组设置 = AgentDojo v1.2.1 banking/travel/slack 三域全量（389 例；noattack 为 57 例用户任务）")
    lines.append("- episode 日志：`results/deepseek-chat_<attack>/logs/`；汇总 JSON：同目录下 banking/travel/slack.json")
    lines.append("- 复跑方式与完整依赖见 `src/README.md`")
    out = RESULTS / "执行记录.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("written:", out)
    print("\n".join(lines[:14]))


if __name__ == "__main__":
    main()
