#!/usr/bin/env bash
# [chatinject-ext] glm-5.3-flash 提速版 v2：并发收敛到实测服务端上限。
# 实测 zhipu flash 档并发上限 ~10-14 路请求：5 个攻击流 × 3 suite = 15 路略过冲，
# 由加强后的指数退避重试（6 次，上限 60s）吸收；24 路全并行已被证实会打穿重试。
set -u
cd "$(dirname "$0")"

export ZHIPU_API_KEY=$(grep -E '^(glm|zhipu):' ../api_key.txt 2>/dev/null | head -1 | cut -d':' -f2- | tr -d ' ')

PY=/home/tlsn/.venvs/chatinject/bin/python
RES=../results
MODEL_ENUM=ZHIPU_GLM_5_3_FLASH
MODEL_NAME=glm-5.3-flash

run_attack () {  # $1=attack name
  local atk="$1"
  echo "[$(date '+%F %T')] START attack=$atk"
  $PY -m agentdojo.scripts.benchmark \
      --model "$MODEL_ENUM" \
      -s banking -s travel -s slack \
      --attack "$atk" \
      --max-workers 3 \
      --logdir "$RES/${MODEL_NAME}_${atk}/logs" \
      --eval-results-dir "$RES/${MODEL_NAME}_${atk}"
  ec=$?
  echo "[$(date '+%F %T')] DONE attack=$atk (exit=$ec)"
}

# 第一组：4 个完全未跑的大设置（各 ~380 集）
run_attack chat_inject_glm5_think &
run_attack chat_inject_glm5_tool &
run_attack chat_inject_qwen3 &
run_attack chat_inject_glm5_with_utility_system_multiturn_7 &
wait

# 第二组：残量补齐 + 明文多轮（S5，未跑）
run_attack injecagent &
run_attack chat_inject_glm5 &
run_attack injecagent_with_utility_system_multiturn_7 &
wait

$PY -m agentdojo.scripts.benchmark \
    --model "$MODEL_ENUM" \
    -s banking -s travel -s slack \
    --max-workers 3 \
    --logdir "$RES/${MODEL_NAME}_noattack/logs" \
    --eval-results-dir "$RES/${MODEL_NAME}_noattack"
echo "[$(date '+%F %T')] DONE noattack (exit=$?)"
wait
echo "[$(date '+%F %T')] ALL RUNS COMPLETE"
