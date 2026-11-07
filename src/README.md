# ChatInject 复现 —— 环境配置与执行说明

本目录包含《ChatInject: Abusing Chat Templates for Prompt Injection in LLM Agents》(ICLR 2026) 的课程复现代码。基础代码来自[论文官方仓库](https://github.com/hwanchang00/chatinject)（AgentDojo fork），我们对其做了少量扩展（文件内以 `[chatinject-ext]` 注释标记）。

## 一、目录结构

```
chatInject_reproduction/
├── src/                        # 复现代码（本目录）
│   ├── agentdojo/              # 官方 AgentDojo 框架 + ChatInject 攻击（含我们的扩展）
│   │   ├── attacks/baseline_attacks.py   # 四种攻击变体 + DeepSeek 模板与钩子扩展 ★
│   │   ├── attacks/multi_turn_data/      # 官方 GPT-4.1 生成的 2~13 轮多轮对话数据
│   │   ├── agent_pipeline/agent_pipeline.py  # LLM 接入层（新增 deepseek/zhipu/dashscope provider）
│   │   ├── agent_pipeline/llms/openai_llm.py # system 角色兼容性修复
│   │   ├── models.py           # 模型注册表（新增直连模型）
│   │   └── scripts/benchmark.py  # 基准测试入口（修复并行模式两处上游 bug）
│   ├── run_experiments.py      # 单次实验 runner（支持注入任务子集、用量统计）
│   ├── run_batch.sh            # 主实验批处理（8 组设置一键运行）★
│   └── analyze_results.py      # 结果汇总与论文对比表生成 ★
├── data/
│   └── official_eval_results/  # 论文官方原始实验输出（用于对比，GLM-4.5 等）
├── results/                    # 实验输出（logs/ + 每组设置的 per-suite JSON）
├── report/                     # （不入库）报告图表与文档写入脚本，负责人本地维护
├── 文章参考/                    # 论文 PDF、PPT、笔记
├── 课程报告.docx
└── api_key.txt                 # API key（格式：每行 "provider: key"，如 "deepseek: sk-xxx"）
```

## 二、环境搭建

```bash
# Python >= 3.10（我们用 3.13）
python3 -m venv ~/.venvs/chatinject
~/.venvs/chatinject/bin/pip install -r requirements.txt
```

依赖清单见 `requirements.txt`。核心依赖：openai、pydantic、click、rich、tenacity、python-dotenv、pyyaml、deepdiff、docstring-parser、anthropic、cohere、google-genai、langchain（后五项为 agentdojo 导入链所需，与本次实验的模型无关）。

## 三、API Key 配置

在项目根目录 `api_key.txt` 中写入（每行一个）：

```
deepseek: sk-xxxxxxxx
glm: xxxxxxxx        # 智谱，可选
qwen: sk-xxxxxxxx    # 阿里百炼，可选
```

run_batch.sh 读取全部已配置的行并导出为 `DEEPSEEK_API_KEY` / `ZHIPU_API_KEY` / `DASHSCOPE_API_KEY`。
换用其他 provider 时改脚本里的 `--model`（可选值见 `agentdojo/models.py`，注意 CLI 接受的是枚举名如
`DEEPSEEK_CHAT`、`ZHIPU_GLM_5_3_FLASH`、`DASHSCOPE_QWEN3_7_FLASH`）。

## 四、运行实验

```bash
cd src
nohup bash run_batch.sh > ../results/logs/batch.log 2>&1 &          # 默认 deepseek-chat，全量 8 组
MODEL=glm5f  nohup bash run_batch.sh > ../results/logs/batch_glm5f.log 2>&1 &   # glm-5.3-flash（智谱免费档）
MODEL=qwen37f nohup bash run_batch.sh > ../results/logs/batch_qwen37f.log 2>&1 & # qwen3.7-flash（百炼低价档）
tail -f ../results/logs/batch.log                                   # 看进度
```

> 注：glm-5.3-flash 走智谱免费档，服务端限并发（~10–14 路请求、聚合 ~20 集/分钟），若 suite 因 429
> 阵亡会打印 `Suite ... FAILED`，**重跑同一命令即可断点续跑**（已有 episode 自动跳过）。
> qwen3.7-flash 的历史运行约 85 分钟。批量脚本现已在任一 suite 失败时返回非零状态，避免误报“全部完成”。

单组运行示例：

```bash
export DEEPSEEK_API_KEY=$(grep '^deepseek:' ../api_key.txt | cut -d':' -f2 | tr -d ' ')
~/.venvs/chatinject/bin/python -m agentdojo.scripts.benchmark \
    --model DEEPSEEK_CHAT \
    -s banking -s travel -s slack \
    --attack chat_inject_deepseek \
    --max-workers 3 \
    --logdir ../results/deepseek-chat_chat_inject_deepseek/logs \
    --eval-results-dir ../results/deepseek-chat_chat_inject_deepseek
```

说明：
- 结果按 suite 写入 `--eval-results-dir`（banking/travel/slack.json），字段与官方 eval_results 一致（average_asr / utility_under_attack）
- episode 级日志在 logs/ 下，**同 logdir 重跑会跳过已完成的 episode（断点续跑）；若改动模型请求参数，应使用新的 logdir 或强制重跑，不要把新旧配置的日志混入同一组结果**，`--force-rerun` 强制全量重跑
- 可用攻击列表：`~/.venvs/chatinject/bin/python -c "from agentdojo.attacks.attack_registry import ATTACKS; print(sorted(ATTACKS))"`

## 五、查看与汇总结果

```bash
cd src && ~/.venvs/chatinject/bin/python analyze_results.py
cd src && ~/.venvs/chatinject/bin/python analyze_results.py --compare   # 三模型跨代对照表
```

输出各设置的加权 ASR / Utility、episode 数与错误 episode 计数，并附论文 Table 1 数值对照；
`--compare` 额外输出 deepseek-chat / glm-5.3-flash / qwen3.7-flash 的八设置对照矩阵。

## 六、实验矩阵（与论文对应关系）

三个受试模型共用同一矩阵（7 种攻击设置 × 389 例 + 1 组良性基线 × 57 例），仅"原生模板/外来模板"两列按模型替换：

| 运行目录前缀 | 原生模板攻击 | 外来模板攻击 |
|---|---|---|
| deepseek-chat_ | chat_inject_deepseek* | chat_inject_qwen3（Qwen-3→DeepSeek） |
| glm-5.3-flash_ | chat_inject_glm5*（GLM-5.x 模板） | chat_inject_qwen3（Qwen-3→GLM） |
| qwen3.7-flash_ | chat_inject_qwen3（ChatML，论文官方类） | chat_inject_glm（GLM→Qwen） |

以 deepseek 为例的完整目录（glm-5.3-flash_ / qwen3.7-flash_ 前缀同理）：

| 运行目录 | 攻击 | 论文对应 |
|---|---|---|
| deepseek-chat_injecagent | Default InjecPrompt | Table 1 第 1 列 |
| deepseek-chat_chat_inject_deepseek | InjecPrompt+ChatInject（DeepSeek 原生模板） | Table 1 第 2 列 |
| deepseek-chat_chat_inject_deepseek_think | ChatInject + 推理钩子 | Table 1 第 3 列（+think） |
| deepseek-chat_chat_inject_deepseek_tool | ChatInject + 工具调用钩子 | Table 1 第 4 列（+tool） |
| deepseek-chat_injecagent_with_utility_system_multiturn_7 | Default Multi-turn | Table 1 第 5 列 |
| deepseek-chat_chat_inject_deepseek_with_utility_system_multiturn_7 | Multi-turn+ChatInject | Table 1 第 6 列 |
| deepseek-chat_chat_inject_qwen3 | 外来模板迁移（Qwen-3→DeepSeek） | Table 2 迁移设置 |
| deepseek-chat_noattack | 无攻击 benign utility | Table 4 benign 列 |

## 七、注意事项（交接给下一位同学）

1. 论文实验经 OpenRouter 调用（temperature=0）；本项目改为官方 API 直连。审查发现历史版本在 `chat_completion_request()` 中使用了 `temperature or NOT_GIVEN`，导致零温参数在请求中被省略，服务端实际采样配置无法由现有日志证明。该问题已修复，**旧实验不应宣称与论文完全采用同一温度配置；修复后的结果仍需重跑确认**。
2. 官方仓库 `benchmark.py` 的 `--max-workers` 并行模式有多处上游 bug（suite 未解析、starmap 参数错位、
   suite 级异常炸整个 CLI），均已修复（`[chatinject-ext]` 标记），勿回退。
3. `openai_llm.py` 中 system→developer 角色映射对 DeepSeek 等 API 不兼容，已按模型名分流；
   工具调用参数 JSON 容错（qwen3.7-flash 偶发输出坏 JSON）与 `extra_body` 透传（zhipu/dashscope 关思考
   参数）同样在此文件。
4. DeepSeek 模板特殊字符为全角（`｜` U+FF5C、`▁` U+2581），编辑 `baseline_attacks.py` 时注意别被输入法/编辑器替换为半角。
5. **已执行的实验**：2026-11-03 deepseek-chat 7 组攻击 + 1 组良性（2,723 正式攻击组合 + 147 条可行性校验 + 57 条良性任务 = 2,927 条日志、零错误、¥12.11）；2026-11-04 增补
   glm-5.3-flash 与 qwen3.7-flash 各 8 组（glm 免费、qwen 约 ¥2，两模型合计 5,854 条日志（正式攻击组合共 5,446 个）、零错误）。
   三模型汇总与执行过程见 `results/执行记录.md`。
6. 复现不含 InjecAgent 基准与防御评测（官方未放出对应代码）；如需扩展见 `课程报告.docx` 2.6 节差异说明。
7. 论文原模型已不可用：glm-4.5 平台下线（现服务名 glm-5.3/glm-5.3-flash）、qwen3-235b-a22b 已从百炼
   移除（继任 qwen3.5-397b-a17b / qwen3.7-flash）。`--model ZHIPU_GLM_5_3_FLASH` / `DASHSCOPE_QWEN3_7_FLASH`
   即当前可用档位；如需更换模型，在 `models.py` 加枚举 + provider，并在 `baseline_attacks.py` 补对应
   模板配置（对照官方 tokenizer 的 chat_template.jinja 转录，参考 `glm5` 条目注释）。
8. 两条 API 工程事实（踩过的坑）：zhipu 免费档限并发导致 429 时，重跑同一命令即可断点续跑；
   dashscope 千问关思考用 `enable_thinking:false`、zhipu 用 `thinking:{"type":"disabled"}`（已内置）。

## 八、审计修复与复跑提醒（2026-11-04）

- **统计分母**：每个攻击设置的正式 ASR/Utility 分母均为 389，文件总数 410 中有额外 21 条注入目标可行性校验日志；无攻击基线为 57。单模型共 2,927 条日志，三模型共 8,781 条。
- **采样参数**：修复前 `temperature=0` 没有真正发送给 API；因此现有结果代表历史请求配置，不能直接宣称“贪心解码严格复现”。需重新执行至少 S1/S2/S5/S6 核心对照，并保存模型 API 响应的实际模型标识与采样配置。
- **调用与统计**：修复了单次 runner 的 `extra_body` 参数转发，以及对已经是百分数的 ASR/Utility 再乘 100 的错误；历史 DeepSeek 良性汇总文件的 9122.81% 修正为 91.23%。
- **状态完整性**：基准测试某 suite 失败时将返回非零退出码，批处理脚本累计失败数量并以非零状态结束。
- **结论范围**：报告只讨论所测模型与 API 的观察结果；“模型免疫”“服务端过滤 token”“模板结构识别是必要条件”均没有独立证据，暂不作为已证明的机制结论。
- **文件生成**：报告与其生成脚本（`report/write_report.py`）不入库，由负责人本地维护；修改后重新生成 `课程报告.docx` 并做 Word/PDF 排版检查。
- **静态一致性检查**：执行 `python src/check_results.py` 验证三模型的样本量、日志文件数量与成功数计算。
