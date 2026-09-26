# DeepSeek 接入与真实 Agent 验收

现在即可申请 Key。已有人工确认基线后，下一阶段应尽早验证真实模型，不需要先把本地规则修到完美。

项目已有 DeepSeek 网关、结构化抽取、推荐解释、成长记忆和推进计划的模型调用路径。模型规划与待办/日历执行由应用服务编排；目前还没有用真实 API 验收完整闭环，也没有通用的自主工具调用循环。接通 API 后，需要分别验证模型输出与业务执行结果。

## 1. 申请并配置

前往 [DeepSeek 官方平台](https://platform.deepseek.com/api_keys) 创建自己的 Key，并确认账户有可用额度。按需少量充值即可，不需要为了接入一次性购买大额额度；费用以 [官方模型价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/) 和实际用量为准。

编辑主应用目录下的 `.env`，不要覆盖已有数据库或搜索配置。若文件不存在，以 `.env.example` 为模板创建。

```dotenv
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-flash
LLM_THINKING=disabled
LLM_MAX_TOKENS=4096
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_API_KEY=在本机填写自己的密钥
```

2026-09-26 核对的 [官方接入文档](https://api-docs.deepseek.com/zh-cn/) 列出 `deepseek-flash` 和 `deepseek-v4-pro`。本项目模板采用 Flash，已有 `.env` 如果显式写了旧模型名，需要手动更新；程序不会改写个人配置。

网关显式发送非思考模式和单次输出 token 上限，适合先验证结构化抽取。可通过配置开启思考模式，但思考也消耗输出预算；调小上限可能导致截断，截断会明确报错。上限是单次输出限制，**不是账户总费用上限**，输入、重试和多次调用仍可能计费。[请求参数说明](https://api-docs.deepseek.com/zh-cn/api/create-chat-completion/)

Key 只放在 `.env`，不要发到聊天、截图或 GitHub。修改配置后需重启后端；新启动的命令行进程会重新加载配置。

## 2. 先做一次可控连通检查

在主应用目录执行：

```bash
.venv/bin/python -m evaluation.check_deepseek --allow-network
```

它只发送内置的虚构讲座句子，执行一次不重试的 JSON 请求，不读私人数据库或评测正文。未显式授权联网、缺少 Key、模型报错、截断或结构不符都会失败，不会以本地规则结果冒充远程成功。输出仅包含模型名、耗时及调用统计，不输出 Key。

这一关只证明真实 API 和一次结构化输出可用；不能证明复杂抽取、排序或 Agent 已完成。余额不足、无权限和模型不存在应先在平台/配置中解决，不要盲目重试。

## 3. 对同一份人工标签比较模型

以下操作会把评测正文或画像/候选信息发给 DeepSeek 并可能计费，执行前需要用户明确接受。默认 CI 不执行这些命令。

```bash
.venv/bin/python -m evaluation.real_data compare extraction evaluation/private/review-2026-09-26/extraction.jsonl --allow-network --output evaluation/private/review-2026-09-26/reports/extraction-deepseek-compare.json
.venv/bin/python -m evaluation.real_data compare ranking evaluation/private/review-2026-09-26/ranking.jsonl --allow-network --k 3 --output evaluation/private/review-2026-09-26/reports/ranking-deepseek-compare.json
```

先记录本地规则与真实模型在同一数据指纹下的结果，再分析错误。9 篇抽取、1 个排序画像已经用于改规则，是开发集；需要补充独立保留样本才能判断模型泛化收益。本轮人工标签是 AI 辅助、用户首次确认，尚无第二位盲标者。

## 4. Agent 闭环验收

用虚构机会和隔离测试画像跑一条可追溯流程：

1. 用户给出目标，模型从文章抽取机会并解释画像匹配。
2. 模型生成含明确步骤的推进计划，程序验证结构与时间约束。
3. 用户确认后，服务执行待办和日历工具并保存真实记录，不能只返回“已创建”文字。
4. 将工具实际结果和用户进度输入后续计划调整，验证记忆参与且不同用户隔离。
5. 注入超时、无效 JSON、重复请求、工具失败，检查错误提示、有限重试、幂等与回滚。

验收记录应包含模型版本、成功率、工具真实落库、耗时、失败路径和平台用量。后续再增加由模型选择受限工具的有界循环、可靠后台任务和恢复机制。联网搜索核验需要独立搜索能力；仅有 DeepSeek Key 不等于获得真实网页证据。
