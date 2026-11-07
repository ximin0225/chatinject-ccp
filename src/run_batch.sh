#!/usr/bin/env bash
# ChatInject 复现主实验批处理（并行版）
# 基准: AgentDojo v1.2.1 banking/travel/slack（389 例/设置）
#
# 用法（在 src/ 下执行）:
#   nohup bash run_batch.sh > ../results/logs/batch.log 2>&1 &   # 默认 DeepSeek
#   MODEL=zhipu  nohup bash run_batch.sh > ../results/logs/batch_zhipu.log 2>&1 &   # 智谱 GLM-4.5（已被平台下线，仅供留档）
#   MODEL=qwen   nohup bash run_batch.sh > ../results/logs/batch_qwen.log 2>&1 &    # 百炼 Qwen3-235B（已被平台下线，仅供留档）
#   MODEL=glm5f  nohup bash run_batch.sh > ../results/logs/batch_glm5f.log 2>&1 &   # 智谱 GLM-5.3-Flash（免费档，2026-11 增补）
#   MODEL=qwen37f nohup bash run_batch.sh > ../results/logs/batch_qwen37f.log 2>&1 & # 百炼 Qwen3.7-Flash（低价档，2026-11 增补）
#
# key 统一放 ../api_key.txt，每行 "provider: key"（deepseek / glm / qwen）。
set -u
cd "$(dirname "$0")"

# ---- 从 api_key.txt 导出全部已配置的 key（缺哪个自动跳过对应模型）----
# Respect explicitly configured environment variables; fall back to the local key file.
if [[ -f ../api_key.txt ]]; then
  DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY:-$(grep '^deepseek:' ../api_key.txt | head -1 | cut -d':' -f2- | tr -d ' ')}
  ZHIPU_API_KEY=${ZHIPU_API_KEY:-$(grep -E '^(glm|zhipu):' ../api_key.txt | head -1 | cut -d':' -f2- | tr -d ' ')}
  DASHSCOPE_API_KEY=${DASHSCOPE_API_KEY:-$(grep -E '^(qwen|dashscope):' ../api_key.txt | head -1 | cut -d':' -f2- | tr -d ' ')}
fi
export DEEPSEEK_API_KEY ZHIPU_API_KEY DASHSCOPE_API_KEY

# ---- 选择受试模型（默认 deepseek），并按模型选对应的"原生模板"攻击矩阵 ----
MODEL=${MODEL:-deepseek}
case "$MODEL" in
  deepseek)
    MODEL_ENUM=DEEPSEEK_CHAT; MODEL_NAME=deepseek-chat
    CI_NATIVE=chat_inject_deepseek;                    # 原生模板 ChatInject
    CI_THINK=chat_inject_deepseek_think; CI_TOOL=chat_inject_deepseek_tool
    MT_NATIVE=chat_inject_deepseek_with_utility_system_multiturn_7 ;;
  zhipu)
    MODEL_ENUM=ZHIPU_GLM_4_5; MODEL_NAME=glm-4.5
    CI_NATIVE=chat_inject_glm;                         # 官方实现的 GLM 原生模板
    CI_THINK=chat_inject_glm_think; CI_TOOL=chat_inject_glm_tool
    MT_NATIVE=chat_inject_glm_with_utility_system_multiturn_7 ;;
  qwen)
    MODEL_ENUM=DASHSCOPE_QWEN3_235B; MODEL_NAME=qwen3-235b-a22b
    CI_NATIVE=chat_inject_qwen3;                       # 官方实现的 Qwen-3 原生模板
    CI_THINK=chat_inject_qwen3_think; CI_TOOL=chat_inject_qwen3_tool
    MT_NATIVE=chat_inject_qwen3_with_utility_system_multiturn_7 ;;
  glm5f)                                               # [chatinject-ext] 2026-11: 论文原模型已下线，改用同厂继任代
    MODEL_ENUM=ZHIPU_GLM_5_3_FLASH; MODEL_NAME=glm-5.3-flash
    CI_NATIVE=chat_inject_glm5;                        # GLM-5.x 模板（对 GLM-5.3 tokenizer 实测核对）
    CI_THINK=chat_inject_glm5_think; CI_TOOL=chat_inject_glm5_tool
    MT_NATIVE=chat_inject_glm5_with_utility_system_multiturn_7 ;;
  qwen37f)
    MODEL_ENUM=DASHSCOPE_QWEN3_7_FLASH; MODEL_NAME=qwen3.7-flash
    CI_NATIVE=chat_inject_qwen3;                       # Qwen3.5/3.7 仍为 ChatML，官方 qwen3 模板即原生
    CI_THINK=chat_inject_qwen3_think; CI_TOOL=chat_inject_qwen3_tool
    MT_NATIVE=chat_inject_qwen3_with_utility_system_multiturn_7 ;;
  *) echo "未知 MODEL=$MODEL（可选 deepseek/zhipu/qwen/glm5f/qwen37f）"; exit 1 ;;
esac
echo "受试模型: $MODEL_NAME ($MODEL_ENUM)"

# Use a configurable interpreter instead of a developer-specific absolute path.
PY=${CHATINJECT_PYTHON:-$HOME/.venvs/chatinject/bin/python}
if [[ ! -x "$PY" ]]; then PY=$(command -v python3); fi
RES=../results

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
  return "$ec"
}

# [chatinject-ext] Detect incomplete experiments even when runs are started in parallel.
# The benchmark CLI now exits nonzero if any suite fails.
failures=0
run_pair() {
  run_attack "$1" &
  local pid1=$!
  run_attack "$2" &
  local pid2=$!
  wait "$pid1" || failures=$((failures + 1))
  wait "$pid2" || failures=$((failures + 1))
}

# 第一波：核心四变体（两组并行）
run_pair "injecagent" "$CI_NATIVE"
run_pair "injecagent_with_utility_system_multiturn_7" "$MT_NATIVE"

# 第二波：外来模板迁移 + 钩子
case "$MODEL" in
  deepseek|zhipu|glm5f) FOREIGN=chat_inject_qwen3 ;;
  qwen|qwen37f) FOREIGN=chat_inject_glm ;;
esac
run_pair "$FOREIGN" "$CI_TOOL"
run_attack "$CI_THINK" &
think_pid=$!

# 无攻击 benign utility 基线
$PY -m agentdojo.scripts.benchmark \
    --model "$MODEL_ENUM" \
    -s banking -s travel -s slack \
    --max-workers 3 \
    --logdir "$RES/${MODEL_NAME}_noattack/logs" \
    --eval-results-dir "$RES/${MODEL_NAME}_noattack"
benign_status=$?
if [ "$benign_status" -ne 0 ]; then
  failures=$((failures + 1))
fi
wait "$think_pid" || failures=$((failures + 1))
if [ "$failures" -ne 0 ]; then
  echo "[$(date '+%F %T')] INCOMPLETE: $failures run(s) failed; rerun to resume." >&2
  exit 1
fi
echo "[$(date '+%F %T')] ALL RUNS COMPLETE"
