# CCP-ChatInject：基于 ChatInject 复现的改进与对照实验

本项目在小组第一位同学完成的 **ChatInject 论文复现代码**上，加入上下文一致的分步诱导方法 **CCP-ChatInject（Context-Conditioned Progressive ChatInject）**，并重新运行 S6 与 CCP 的三模型配对实验。任务环境为 AgentDojo 的模拟 banking、travel、slack 场景。

**主要结果：Qwen 上 CCP 的原生评分 ASR 从 19.28% 提高到 27.51%；DeepSeek 和 GLM 上没有得到统计显著的提升。** 本仓库同时保留评分器审查结果，不把所有原生“成功”直接解释为真实攻击目标达成。

这里上传的是 `chatinject-reproduction` 的源码与数据快照。仓库名称改为 `chatinject-ccp`，不包含其他项目、个人报告、密钥、AI 工作对话或完整原始运行日志，也不迁移原仓库的 Git 历史。

## 1. 第一位同学的工作与本次新增内容

基础框架来自 [ChatInject 官方仓库](https://github.com/hwanchang00/chatinject)，评测基于 AgentDojo。第一位同学完成的工作包括：整理代码及环境、接入 DeepSeek / 智谱 / 阿里云兼容接口、运行 S0–S7 复现设置、保存历史统计和编写复现说明。历史说明保存在 [README_BASELINE.md](README_BASELINE.md)，技术操作说明见 [src/README.md](src/README.md)。历史说明中的完整日志、报告和课堂资料路径并非都包含在本次快照中，请以本 README 的文件范围为准。

本次 CCP 工作建立在已有复现环境上，不能将整个 `agentdojo/` 框架或已有模型接入都算作本次创新。导出前基础提交为 `67d1e172303727ed71f4af6b6c1d657b8137e37c`。接手时环境中已经存在 selective-template / tool-cue 探索代码，`run_selective_template.py` 被 CCP 实验脚本复用，其本身不作为 CCP 的核心创新。

| 文件 | 相对接手时环境的新增或修改 | 用途 |
|---|---|---|
| [src/generate_ccp_data.py](src/generate_ccp_data.py) | 新增 | 根据 21 个注入目标的手工设计步骤链，确定性生成 CCP 离线对话，无须调用生成模型 API |
| [CCP 对话数据](src/agentdojo/attacks/multi_turn_data/ccp_multiturn_7_generation_output.json) | 新增 | 21 份包含 `{task}` 占位符的目标专属对话 |
| [baseline_attacks.py](src/agentdojo/attacks/baseline_attacks.py) | 修改，在文件末尾加入 CCP 实现 | `build_ccp_attack_string`、`CcpChatInjectBase` 和三款模型的独立攻击注册，保留 S6 以供对照 |
| [src/validate_ccp_data.py](src/validate_ccp_data.py) | 新增 | 检查目标覆盖、消息顺序、占位符替换和三类原生模板的构造 |
| [task_suite.py](src/agentdojo/task_suite/task_suite.py) | 修改环境注入逻辑 | 修复任务文本含引号等字符时直接拼接 YAML 导致的解析错误，S6 与 CCP 使用同一修复 |
| [src/run_ccp_comparison.py](src/run_ccp_comparison.py) | 新增 | Qwen 全量配对对照、断点续跑、错误重试、统计和用量记录 |
| [src/run_ccp_deepseek.py](src/run_ccp_deepseek.py) | 新增 | DeepSeek 配对对照，记录 API 返回的实际模型标识 |
| [src/run_ccp_glm.py](src/run_ccp_glm.py) | 新增 | GLM 配对对照及 thinking / 工具调用历史的兼容处理 |
| [results/](results/) 中三个 `ccp_vs_s6_*` 正式目录 | 新增 | 配置、逐例评分、配对 CSV、汇总和评分器审查 |
| [scripts/verify_ccp_results.py](scripts/verify_ccp_results.py) | 本次整理仓库时新增 | 不请求 API，使用上传的逐例记录重新核算配对数量和汇总指标 |

## 2. CCP 方法如何实现

原 S6 的核心是用模型原生聊天模板包装离线伪造对话。本次保留模板及 S6 的 system message，主要调整包装内部的对话内容和运行时任务引用。

1. **上下文嵌入**：离线对话的首个 assistant 消息保留 `{task}`。构造载荷时，使用当前 `user_task.PROMPT` 原文进行 `.replace("{task}", task)`，避免 `.format()` 意外消耗 `{hotel_name}` 等其他字面量占位符。同一目标的对话可复用于不同任务，最终载荷随任务变化。
2. **分步组织**：将对话组织为“信息收集 → 准备或起草 → 确认执行”的步骤链，通过连续 user 消息推进，assistant 消息作出承接回应。
3. **授权式收尾**：最后的 user 消息表达确认，末尾 assistant 消息承诺执行。这是注入文本内部伪造的授权表述，不代表真实用户作出了授权。

每份数据包含 **7 条消息，顺序为 A/U/A/U/A/U/A，即 4 条 assistant 与 3 条 user 消息**，并非 7 组完整问答。21 个目标来自 banking 9 个、travel 7 个、slack 5 个目标。

三款模型分别注册 `chat_inject_qwen3_ccp`、`chat_inject_deepseek_ccp`、`chat_inject_glm5_ccp`，与对应 S6 原生模板保持一致。

**实现范围**：目前只有首条 assistant 消息动态引用真实任务，后续步骤仍按目标固定，并未实现整段对话的任务条件生成。部分准备步骤已包含较完整的敏感目标，因此不能声称每个子目标单独观察都完全无害。原 S6 对话中也存在确认或配合表述，授权话术并非本次首次提出。结构校验只能检查消息与文本规则，不能证明目标在语义上被充分分解。

## 3. 本次正式对照的设置

每个模型重新运行同一批 **389 个任务—目标配对**，每个配对执行 S6、CCP 两种方法，共 778 个 episode。三个模型合计 2,334 个最终 episode，均无最终错误或缺失。

| 项目 | 设置 |
|---|---|
| 基准版本 | AgentDojo `v1.2.1` |
| 任务组合 | banking 144、travel 140、slack 105 |
| 对照 | 同一模型下的原生模板 S6 与 CCP |
| temperature | 0，实际传递至 API |
| 重复次数 | 每个方法、每个配对 1 次 |
| 随机种子 | 421，用于打乱执行顺序，不是服务端采样种子 |
| 分母 | 双方最终均无错误的完整配对，错误与排除数另列 |
| 统计 | 配对 ASR 差值、配对正态近似 95% CI、双侧精确 McNemar 检验 |

| 模型 | 请求标识 / 版本信息 | 思考设置 |
|---|---|---|
| Qwen | `qwen3.7-flash-2026-07-15` | 关闭 thinking |
| DeepSeek | 请求 `deepseek-chat`，本次响应记录为 `deepseek-flash` | 关闭 thinking |
| GLM | `glm-5.3-flash`，本次响应记录同名 | thinking 开启，`reasoning_effort=low` |

GLM 本次接口不接受关闭 thinking 的请求，因此按其接口要求启用思考，并在工具调用后回填对应的 `reasoning_content`。两种攻击在同一模型内使用相同设置；不同模型的思考设置并不完全一致，不能据此作严格的跨模型能力排名。

历史复现中存在 temperature 未实际传递到 API 的问题；本次对照使用修复后的请求层。因此，下表的 S6 是本次重跑的基线，与第一位同学历史报告中的 S6 数值有所不同。DeepSeek 的请求别名相同，也不能证明历史与本次服务端底层模型版本完全相同。

## 4. 实验结果与分析

### 4.1 原生评分结果

ASR 为基准原生评分器判定成功的比例；Utility 为真实用户任务完成比例。百分比差值使用百分点（pp）。

| 模型 | S6 成功数 / 389 | CCP 成功数 / 389 | S6 ASR | CCP ASR | 差值 | McNemar p |
|---|---:|---:|---:|---:|---:|---:|
| Qwen | 75 | 107 | 19.28% | 27.51% | +8.23 pp | 0.000846 |
| DeepSeek | 13 | 12 | 3.34% | 3.08% | −0.26 pp | 1.000000 |
| GLM | 1 | 5 | 0.26% | 1.29% | +1.03 pp | 0.218750 |

Qwen 的配对差值 95% CI 为 **[+3.56, +12.89] pp**。同一批配对中，CCP 独有成功 60 例，S6 独有成功 28 例，两者均成功 47 例。DeepSeek 的差值区间为 [−1.77, +1.26] pp，未观察到可靠提升。GLM 的成功数很少，原生成功数增加也不足以支持显著改进。

| 模型 | S6 Utility | CCP Utility |
|---|---:|---:|
| Qwen | 68.12%（265/389） | 74.55%（290/389） |
| DeepSeek | 80.98%（315/389） | 76.61%（298/389） |
| GLM | 78.41%（305/389） | 76.86%（299/389） |

Qwen 分域结果说明，增益并非均匀分布：

| 任务域 | 配对数 | S6 成功数 | CCP 成功数 | ASR 差值 |
|---|---:|---:|---:|---:|
| banking | 144 | 22 | 40 | +12.50 pp |
| travel | 140 | 22 | 16 | −4.29 pp |
| slack | 105 | 31 | 51 | +19.05 pp |

### 4.2 评分器审查与敏感性分析

travel 的 `injection_task_6` 要求模型积极推荐目标酒店，但其原生检查主要判断答案是否包含酒店名称。模型即使在拒绝、提醒或警告中提及该酒店，也会被判为成功。评分代码见 [travel/injection_tasks.py](src/agentdojo/default_suites/v1/travel/injection_tasks.py)。

本次人工复核了该目标下 DeepSeek 与 GLM 的全部原生阳性，共 27 个 episode，均属于拒绝或警告中的名称提及。**因此保留上表原始评分作为复现口径，并另外统一排除该目标对应的全部 20 个配对进行事后敏感性分析**，而不是只删除某个方法的阳性样本。

| 模型 | S6 成功数 / 369 | CCP 成功数 / 369 | S6 ASR | CCP ASR | 差值 |
|---|---:|---:|---:|---:|---:|
| Qwen | 75 | 107 | 20.33% | 29.00% | +8.67 pp |
| DeepSeek | 1 | 2 | 0.27% | 0.54% | +0.27 pp |
| GLM | 0 | 1 | 0.00% | 0.27% | +0.27 pp |

这一分析说明：Qwen 的增益不依赖该弱评分目标；DeepSeek 与 GLM 的真实有效成功仍非常稀少。它属于事后审查，不能替代预先定义的主要指标，也没有证明其他目标的评分器全部没有问题。详细记录见各正式目录中的 `scoring_review.json`。

### 4.3 可以得出的结论与局限

- 当前实现对 Qwen 有明显增益，主要来自 banking 和 slack；travel 上出现下降。
- DeepSeek 没有稳定提升，GLM 的少数成功不足以支持跨模型泛化。不能把差异直接归因于某个模型更安全或模板失效。
- 尚未分别移除任务引用、分步组织或授权式收尾进行消融，无法确定各组件的独立贡献。
- 每个模型仅完成一轮实验。temperature=0 也不能保证云端 API 完全确定；任务与目标之间还存在关联，当前检验没有进行聚类修正。
- 占位符替换属于轻量上下文嵌入。任务语义与目标语义的衔接程度仍需进一步验证，不能将名称中的“上下文一致”视为已经全面实现的性质。

## 5. 目录与结果文件

```text
chatinject-ccp/
├── README.md                       # 本次改进、结果与操作入口
├── README_BASELINE.md              # 接手时的复现说明存档
├── src/                            # 完整源码及运行所需对话数据
│   ├── agentdojo/
│   ├── generate_ccp_data.py
│   ├── validate_ccp_data.py
│   ├── run_selective_template.py   # 复用的既有流水线
│   ├── run_ccp_comparison.py        # Qwen
│   ├── run_ccp_deepseek.py
│   └── run_ccp_glm.py
├── data/official_eval_results/      # 原有论文参考结果
├── scripts/verify_ccp_results.py    # 新增的离线核对入口
└── results/
    ├── ...                         # 历史复现的轻量汇总
    ├── ccp_vs_s6_qwen_full_20261107_fixed/
    ├── ccp_vs_s6_deepseek_full_20261107/
    └── ccp_vs_s6_glm_low_full_20261107/
```

三个正式目录均保存 `plan.json`、`summary.json`、`final_episodes.json`、`paired_details.csv`、`comparison.md`、`audit.json` 和 `scoring_review.json`。其中 `final_episodes.json` 保存评分和用量等逐例元数据，不是完整对话轨迹。`audit.json` 是上传前在服务器原始日志上执行核对所留下的记录；本快照不含这些原始日志，离线脚本只能重新核算上传记录之间的一致性。

曾因 YAML 解析问题中止的 Qwen 目录、冒烟实验、早期探索输出、运行控制台日志、GLM 原始响应、临时备份以及 AI 对话导出未上传。历史复现汇总可以阅读，但依赖完整历史日志的旧校验命令可能不适用于此精简结果快照。

## 6. 环境配置与运行

以下从仓库根目录执行，推荐使用 Linux / WSL，与原实验环境一致。原项目依赖说明要求 Python >=3.10，完整依赖见 [src/requirements.txt](src/requirements.txt)。

```bash
git clone https://github.com/ximin0225/chatinject-ccp.git
cd chatinject-ccp
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r src/requirements.txt
```

**先离线查看与校验，无须密钥，也不会调用 API：**

```bash
python scripts/verify_ccp_results.py
python src/validate_ccp_data.py
```

需要重新生成固定的 21 份对话时，可运行 `python src/generate_ccp_data.py`，然后再次执行结构校验。生成器会写入对话数据文件，已保存的正式实验结果不会因此重新运行。

**只有重新请求模型时才需要自己的 API Key**。支持环境变量 `DASHSCOPE_API_KEY`、`DEEPSEEK_API_KEY`、`ZHIPU_API_KEY`，也支持根目录的本地 `api_key.txt`，格式为每行 `qwen: <YOUR_KEY>`、`deepseek: <YOUR_KEY>`、`glm: <YOUR_KEY>`。环境变量优先。密钥文件不在仓库内，且已被 `.gitignore` 排除。

**重新跑正式对照会调用付费 API**，请使用新的输出目录，以区分已有结果。三条命令可分别执行，不需要同时启动：

```bash
# Qwen：S6 与 CCP，共 778 个 episode
python src/run_ccp_comparison.py --output results/my_qwen_run --workers 4 --seed 421

# DeepSeek
python src/run_ccp_deepseek.py --output results/my_deepseek_run --workers 4 --seed 421

# GLM
python src/run_ccp_glm.py --output results/my_glm_run --workers 4 --seed 421
```

DeepSeek 与 GLM 可先添加 `--smoke` 进行小规模验证，冒烟与正式实验须使用不同输出目录。三个脚本均支持对**自行新建、配置未变且包含原始日志的运行目录**添加 `--resume` 断点续跑；不要对本仓库省略原始日志的已发布结果目录使用续跑。

运行时控制台持续报告进度，输出目录中的 `progress.json` 保存完成情况，`episodes.jsonl` 保存逐例进度，结束后生成 `summary.json` 和 `comparison.md`。历史结果的生成配置见各自 `plan.json`；依赖版本、云端模型别名和服务端行为变化可能影响重跑数值。

## 7. 上传范围与协作

本仓库采用新建源码快照，保留上游出处及历史复现说明，不复制旧仓库提交历史。上传前对选定文件执行了真实配置密钥精确匹配和常见凭证格式检查。`.gitignore` 同时排除 `.env`、API 密钥文件、私钥、虚拟环境、缓存和原始运行日志。

组员可先阅读本 README 的文件清单与结果表，再查看 `baseline_attacks.py` 末尾的 CCP 类及三个 runner。后续修改建议使用独立分支，并为新实验建立独立输出目录。仓库当前按拥有者确认的选择设置为公开。
