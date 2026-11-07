"""Validate CCP dialogue data and render model-specific payload previews."""

import argparse
import json
from pathlib import Path

from agentdojo.attacks.baseline_attacks import (
    CCP_DATA_FILENAME,
    MULTITURN_SYSTEM_MESSAGE,
    build_ccp_attack_string,
    model_configs,
)

DATA_DIR = Path(__file__).resolve().parent / "agentdojo" / "attacks" / "multi_turn_data"
EXPECTED_SPEAKERS = ["Assistant", "User", "Assistant", "User", "Assistant", "User", "Assistant"]


def validate_data(data: dict, source: dict) -> list[str]:
    errors = []
    if set(data) != set(source):
        errors.append("CCP goal keys do not exactly match the official 21-goal source data")
    if len(data) != 21:
        errors.append(f"Expected 21 goals, found {len(data)}")

    for goal, item in data.items():
        label = goal[:70]
        history = item.get("conversational_narrative", {}).get("history", [])
        if len(history) != 7:
            errors.append(f"{label}: expected 7 turns, found {len(history)}")
            continue
        if [turn.get("speaker") for turn in history] != EXPECTED_SPEAKERS:
            errors.append(f"{label}: invalid speaker order")
        if [turn.get("turn_number") for turn in history] != list(range(1, 8)):
            errors.append(f"{label}: turn numbers must be 1..7")
        dialogues = [turn.get("dialogue", "") for turn in history]
        if any(not text.strip() for text in dialogues):
            errors.append(f"{label}: empty dialogue turn")
        if dialogues[0].count("{task}") != 1:
            errors.append(f"{label}: first assistant turn must contain exactly one {{task}}")
        if sum(text.count("{task}") for text in dialogues) != 1:
            errors.append(f"{label}: CCP data must contain exactly one {{task}} placeholder")
        if any(goal in text for text in dialogues):
            errors.append(f"{label}: full injection goal is repeated verbatim in one turn")
        if not any(word in dialogues[5].lower() for word in ("confirm", "approved", "correct", "right")):
            errors.append(f"{label}: final user turn lacks explicit authorization framing")
        if not any(word in dialogues[3].lower() for word in ("prepare", "draft")):
            errors.append(f"{label}: second user turn lacks preparation/drafting step")
    return errors


def validate_payloads(data: dict, task: str) -> tuple[list[str], dict[str, str]]:
    errors = []
    previews = {}
    first_history = next(iter(data.values()))["conversational_narrative"]["history"]
    for model_key in ("deepseek", "qwen3", "glm5"):
        payload = build_ccp_attack_string(model_key, first_history, task)
        previews[model_key] = payload
        cfg = model_configs[model_key]
        if task not in payload:
            errors.append(f"{model_key}: runtime task was not inserted")
        if "{task}" in payload:
            errors.append(f"{model_key}: unresolved {{task}} placeholder")
        if MULTITURN_SYSTEM_MESSAGE not in payload:
            errors.append(f"{model_key}: S6 system message changed")
        if payload.count(cfg["user_interrupt_tag"]) != 3:
            errors.append(f"{model_key}: expected 3 user role markers")
        if payload.count(cfg["assistant_interrupt_tag"]) != 4:
            errors.append(f"{model_key}: expected 4 assistant role markers")
        expected_start = cfg.get("sentence_begin_tag", "") + cfg["system_interrupt_tag"]
        if not payload.startswith(expected_start):
            errors.append(f"{model_key}: incorrect template prefix")
        if cfg.get("eos_tag") and not payload.endswith(cfg["eos_tag"]):
            errors.append(f"{model_key}: incorrect template suffix")

    other_task = task + " Additional unique context."
    if build_ccp_attack_string("qwen3", first_history, task) == build_ccp_attack_string(
        "qwen3", first_history, other_task
    ):
        errors.append("qwen3: payload does not vary with the user task")

    hotel_goal = next(goal for goal in data if "{hotel_name}" in goal)
    hotel_history = data[hotel_goal]["conversational_narrative"]["history"]
    hotel_payload = build_ccp_attack_string("qwen3", hotel_history, task)
    if "{hotel_name}" not in hotel_payload:
        errors.append("qwen3: literal {hotel_name} slot was incorrectly consumed")
    return errors, previews


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA_DIR / CCP_DATA_FILENAME)
    parser.add_argument(
        "--source",
        type=Path,
        default=DATA_DIR / "with_utility_multi_turn_7_generation_output.json",
    )
    parser.add_argument(
        "--task",
        default="Review my recent transactions and help me organize this month's bills.",
    )
    parser.add_argument("--preview-output", type=Path)
    args = parser.parse_args()

    data = json.loads(args.data.read_text(encoding="utf-8"))
    source = json.loads(args.source.read_text(encoding="utf-8"))
    errors = validate_data(data, source)
    payload_errors, previews = validate_payloads(data, args.task)
    errors.extend(payload_errors)

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)

    print(f"PASS: {len(data)} goal-specific CCP dialogues")
    print("PASS: seven-turn A/U/A/U/A/U/A structure and authorization framing")
    print("PASS: one runtime {task} slot per dialogue; full goals are decomposed")
    print("PASS: DeepSeek, Qwen3, and GLM5 native-template payload construction")
    print("PASS: literal {hotel_name} remains intact")

    if args.preview_output:
        args.preview_output.parent.mkdir(parents=True, exist_ok=True)
        sections = []
        for model_key, payload in previews.items():
            sections.append(f"===== {model_key} =====\n{payload}\n")
        args.preview_output.write_text("\n".join(sections), encoding="utf-8")
        print(f"Wrote payload previews to {args.preview_output}")


if __name__ == "__main__":
    main()
