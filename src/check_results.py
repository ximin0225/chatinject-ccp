"""Verify result artifacts and sample denominators without running model APIs.

Run: python src/check_results.py
"""
import json
from pathlib import Path
from analyze_results import MODEL_MATRIX, SUITES, N_PER_SUITE

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"


def check() -> None:
    problems = []
    rows = []
    for model, settings in MODEL_MATRIX.items():
        for label, dirname in settings.items():
            base = RESULTS / dirname
            benign = label == "S0无攻击"
            expected = 57 if benign else 389
            expected_logs = 57 if benign else 410
            logs = list((base / "logs").rglob("*.json"))
            if len(logs) != expected_logs:
                problems.append(f"{model} / {label}: logs={len(logs)} expected={expected_logs}")
            total = 0
            for suite in SUITES:
                path = base / f"{suite}.json"
                if not path.is_file():
                    problems.append(f"missing {path}")
                    continue
                record = json.loads(path.read_text())
                target = {"banking": 16, "travel": 20, "slack": 21}[suite] if benign else N_PER_SUITE[suite]
                count = record.get("total_security_tasks") if not benign else record.get("total_tasks")
                if count != target:
                    problems.append(f"{dirname}/{suite}: n={count}, expected={target}")
                total += count if isinstance(count, int) else 0
                if not benign:
                    success = record.get("injection_successful_tasks")
                    avg = record.get("average_asr")
                    if success is None or avg is None or abs(100 * success / target - avg) > 1e-6:
                        problems.append(f"{dirname}/{suite}: ASR and success count disagree")
            if total != expected:
                problems.append(f"{dirname}: counted {total}/{expected} cases")
            rows.append((model, label, total, len(logs)))
    for model, label, n, log_n in rows:
        print(f"{model:17} {label:12} evaluated={n:3} logs={log_n:3}")
    if problems:
        print("\nAUDIT FAILED:")
        for item in problems:
            print(" -", item)
        raise SystemExit(1)
    print("\nAUDIT OK: 3 models, 7 attack variants + 1 benign baseline each.")


if __name__ == "__main__":
    check()
