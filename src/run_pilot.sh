#!/usr/bin/env bash
# [chatinject-ext] 2026-11 增补模型试跑（pilot）：banking user_task_0 × injection_task_0 各 1 例，
# 验证 glm-5.3-flash / qwen3.7-flash 管线（provider、关思考参数、模板 payload 透传、工具调用）。
# 全量跑请用 run_batch.sh（MODEL=glm5f / qwen37f）。
set -u
cd "$(dirname "$0")"

export DEEPSEEK_API_KEY=$(grep '^deepseek:' ../api_key.txt 2>/dev/null | head -1 | cut -d':' -f2- | tr -d ' ')
export ZHIPU_API_KEY=$(grep -E '^(glm|zhipu):' ../api_key.txt 2>/dev/null | head -1 | cut -d':' -f2- | tr -d ' ')
export DASHSCOPE_API_KEY=$(grep -E '^(qwen|dashscope):' ../api_key.txt 2>/dev/null | head -1 | cut -d':' -f2- | tr -d ' ')

PY=/home/tlsn/.venvs/chatinject/bin/python
RES=../results

run_pilot () {  # $1=MODEL_ENUM $2=MODEL_NAME $3=attack
  local enum="$1" name="$2" atk="$3"
  echo "[$(date '+%F %T')] PILOT ${name} attack=${atk}"
  $PY -m agentdojo.scripts.benchmark \
      --model "$enum" \
      -s banking \
      -ut user_task_0 -it injection_task_0 \
      --attack "$atk" \
      --logdir "$RES/${name}_${atk}/logs" \
      --eval-results-dir "$RES/${name}_${atk}"
}

# ---- glm-5.3-flash：S2 原生模板 / S4 tool 钩子 / S6 多轮 ----
run_pilot ZHIPU_GLM_5_3_FLASH glm-5.3-flash chat_inject_glm5 &
run_pilot ZHIPU_GLM_5_3_FLASH glm-5.3-flash chat_inject_glm5_think &
wait
run_pilot ZHIPU_GLM_5_3_FLASH glm-5.3-flash chat_inject_glm5_tool &
run_pilot ZHIPU_GLM_5_3_FLASH glm-5.3-flash chat_inject_glm5_with_utility_system_multiturn_7 &
wait
# ---- qwen3.7-flash：S1 明文 / S2 原生模板 / S4 tool 钩子 / S6 多轮 ----
run_pilot DASHSCOPE_QWEN3_7_FLASH qwen3.7-flash injecagent &
run_pilot DASHSCOPE_QWEN3_7_FLASH qwen3.7-flash chat_inject_qwen3 &
wait
run_pilot DASHSCOPE_QWEN3_7_FLASH qwen3.7-flash chat_inject_qwen3_tool &
run_pilot DASHSCOPE_QWEN3_7_FLASH qwen3.7-flash chat_inject_qwen3_with_utility_system_multiturn_7 &
wait
echo "[$(date '+%F %T')] PILOT DONE"
