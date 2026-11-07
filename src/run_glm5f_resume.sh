#!/usr/bin/env bash
# [chatinject-ext] glm-5.3-flash 补跑：v3 组1 中 suite 阵亡的三个攻击
# （chat_inject_glm5_tool / chat_inject_glm5_with_utility_system_multiturn_7 / chat_inject_qwen3）
# 断点续跑：已有 episode 自动跳过；完成时重写全套 eval JSON（覆盖试跑/中断的残留文件）。
set -u
cd "$(dirname "$0")"

export ZHIPU_API_KEY=$(grep -E '^(glm|zhipu):' ../api_key.txt 2>/dev/null | head -1 | cut -d':' -f2- | tr -d ' ')

PY=/home/tlsn/.venvs/chatinject/bin/python
RES=../results
MODEL_ENUM=ZHIPU_GLM_5_3_FLASH
MODEL_NAME=glm-5.3-flash

run_attack () {  # $1=attack name
  local atk="$1"
  echo "[$(date '+%F %T')] START resume attack=$atk"
  $PY -m agentdojo.scripts.benchmark \
      --model "$MODEL_ENUM" \
      -s banking -s travel -s slack \
      --attack "$atk" \
      --max-workers 3 \
      --logdir "$RES/${MODEL_NAME}_${atk}/logs" \
      --eval-results-dir "$RES/${MODEL_NAME}_${atk}"
  ec=$?
  echo "[$(date '+%F %T')] DONE resume attack=$atk (exit=$ec)"
}

run_attack chat_inject_glm5_tool &
run_attack chat_inject_qwen3 &
run_attack chat_inject_glm5_with_utility_system_multiturn_7 &
wait
echo "[$(date '+%F %T')] RESUME COMPLETE"
