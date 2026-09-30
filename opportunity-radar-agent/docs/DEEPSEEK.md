# DeepSeek 接入与真实 Agent 验收

现在即可申请 Key。已有人工确认基线后，下一阶段应尽早验证真实模型，不需要先把本地规则修到完美。

项目已有 DeepSeek 网关、结构化抽取、推荐解释、成长记忆和推进计划的模型调用路径。模型规划与待办/日历执行由应用服务编排。2026-09-26 已用真实 API 和虚构数据验证含用户确认的服务链；目前还没有通用的自主工具调用循环，真实语料效果与浏览器交互仍需分别验收。

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

验收记录应包含模型版本、成功率、工具真实落库、耗时、失败路径和平台用量。持久化任务和恢复机制现已接入，见 [JOBS.md](JOBS.md)；后续增加由模型选择受限工具的有界循环。联网搜索核验需要独立搜索能力；仅有 DeepSeek Key 不等于获得真实网页证据。

## 已完成的真实 API 验收

```bash
.venv/bin/python -m evaluation.check_agent_live --allow-network
```

该命令必须在独立进程启动，先将数据库切换到临时 SQLite，再加载业务模块；所有画像、文章和反馈由脚本生成。默认最多 16 次 HTTP 请求，可通过 `--max-requests` 降低上限。真实 HTTP 响应经过生产服务解析，没有伪造模型响应；模板 Key 不会写入报告。报告只保存在 Git 忽略的 `evaluation/private/agent-live/`，临时数据库结束后删除。

2026-09-26 修复后复测：`deepseek-flash`、非思考模式，9 个阶段通过，12 次真实 HTTP 请求、约 32 秒、19,295 tokens，零请求失败、零规则回退。

覆盖：抽取正负例并保存机会、画像匹配和摘要、机会顾问、多轮推进分析、模拟用户确认后创建计划、独立待办与重复同步、日历幂等、进展重新规划及确认、成长记忆生成/复用/用户隔离并进入新推荐。

首轮实测发现并修复了计划完成但待办仍 pending 的问题；确认操作现在将关联子待办的状态、标题、描述和优先级与计划变更原子提交，并验证待办所属用户和任务身份。另修复推荐刷新时会话对象冲突；记忆输入增加当前计划判断和风险，避免丢失来源不确定性。

边界：脚本模拟用户确认，不代表模型获得自动执行权限。分析 worker 在测试中同步调用，未覆盖浏览器、后台线程调度或重启恢复；模型回复的事实性仍需人工审阅。首次报告中阶段通过不代表没有缺陷，复测已加入“关联待办必须同步完成”的断言。上述 tokens 只描述复测，不是账户账单或总费用上限。

## 持久化 worker 的真实验收

2026-09-27 新增 `evaluation.check_jobs_live --allow-network --max-requests 16`，经实际 HTTP 提交和生命周期 worker 验收抽取、推荐、推进分析和核验四条任务链。虚构数据共 6 次真实 DeepSeek 请求、9,038 tokens、约 26 秒，全部成功；搜索使用测试替身。临时数据库与本地报告位置、浏览器验收范围见 [任务说明](JOBS.md)。此结果与上面的 12 请求服务链测试分开记录，不替代私人语料效果或真实搜索验证。
