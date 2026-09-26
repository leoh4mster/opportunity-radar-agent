# 设计说明

## MVP 边界

- 不处理公众号登录、反爬和真实抓取。
- 文章来源为本地 JSON / Markdown / TXT。
- 大模型抽取、总结可接真实 API；没有 Key 时使用规则 fallback。
- 待办和日历保存在本地数据库；联网搜索属于可选能力。

## 数据库表

### user_profiles

保存用户画像。

- id
- name
- major_direction
- grade_identity
- current_goals
- skills
- interested_fields
- disliked_contents
- detailed_needs
- time_preference
- location_preference
- created_at
- updated_at

### articles

保存导入的公众号文章。

- id
- title
- source
- author
- published_at
- content
- content_hash（服务端正文身份，非空且唯一）
- url
- imported_at
- processed

### opportunities

保存从文章中抽取的机会。

- id
- article_id
- name
- category
- organizer
- event_time
- deadline
- location
- target_audience
- link
- requirements
- summary
- benefit
- cost
- credibility
- raw_payload
- official_url
- registration_url
- verification_status
- credibility_score
- risk_level
- risk_flags
- verification_summary
- evidence_sources
- enriched_at
- verified_at
- created_at

增强字段只会在用户主动触发工具后更新。默认推荐流水线不会强制二次检索，也不会依赖这些字段。

### recommendations

保存用户和机会之间的推荐结果。

- id
- user_id
- opportunity_id
- relevance_score
- urgency_score
- benefit_score
- cost_score
- credibility_score
- total_score
- reason
- content_overview
- relevance_explanation
- risk_notes
- anti_recommendation_reason
- action_suggestion
- opportunity_state
- deadline
- deadline_urgency
- deadline_note
- created_at

### tool_calls

保存工具调用记录。

- id
- user_id
- opportunity_id
- tool_name
- payload
- status
- result
- created_at

### tool_call_logs

保存按需 Agent 工具调用记录。

- id
- user_id
- opportunity_id
- action
- tool_name
- input_json
- output_json
- status
- created_at

### user_events

保存用户关键行为日志，只记录结构化事件，不保存聊天历史。

- id
- user_id
- event_type
- event_target
- event_metadata
- created_at

支持事件类型：

- view_opportunity
- save_opportunity
- verify_opportunity
- create_todo
- create_calendar
- mark_useful
- mark_irrelevant
- mark_not_interested
- mark_too_easy
- mark_too_hard
- apply_opportunity

### memory_reflections

保存由行为日志压缩得到的长期洞察。

- id
- user_id
- reflection_type
- summary
- confidence
- created_at
- updated_at

## 核心模块

- `import_service`：解析本地文件并写入文章表。
- `llm_service`：封装 DeepSeek 调用和无 Key 时的本地规则 fallback。
- `extraction_service`：从文章抽取结构化机会。
- `matching_service`：根据用户画像打分、排序、生成行动建议。
- `tool_service`：统一记录搜索、日历和待办操作。
- `agent_tools`：轻量工具层，包含 `BaseTool`、`ToolRegistry`、本地规则核验、补全、日历和待办。
- `opportunity_agent`：按用户 action 选择工具，执行后写入数据库。结构预留为 `OpportunityState -> ToolDecision -> ToolExecution -> ResultPersist -> UserFeedback`。
- `growth_memory.memory_updater`：写入关键行为日志。
- `growth_memory.snapshot_service`：按用户操作手动生成五部分成长记忆快照。
- `growth_memory.memory_manager`：统一管理行为事件和成长记忆快照。
- `core.observability`：关联请求 ID、结构化日志和单进程运行指标；不记录请求正文或模型提示词。

## 打分逻辑

总分是内部排序信号，前端不直接展示具体分数。当前权重：

```text
total =
  relevance * 0.55
+ urgency * 0.05
+ benefit * 0.35
+ cost * 0.05
+ 状态/核验/截止时间修正
+ 地点/时间偏好修正
```

- 相关性 `relevance`：先由规则根据目标、专业、技能、兴趣、详细需求关键词匹配得到基础分；配置 DeepSeek 时，会再调用模型根据文章语义和用户画像校正。
- 紧急程度 `urgency`：deadline 越近越高，已过期为低分。
- 成长收益 `benefit`：先使用抽取阶段的机会价值估计；配置 DeepSeek 时，会再调用模型根据成长、申请、简历、科研价值校正。
- 准备轻重 `cost`：要求越轻、行动成本越低，得分越高。
- 可信度 `credibility`：仍会保存并用于核验展示/风险判断，但不再作为基础总分权重。

如果某条机会已被用户主动核验，排序会额外考虑：

- `verified` 且 `credibility_score` 高：小幅加权。
- `uncertain`：不加或轻微降权。
- `suspicious` / `high risk`：明显降权。
- 未核验：不惩罚，只在前端标记“未核验”。

前端推荐排序页只展示排序后的机会顺序，不展示 `total_score`、分项星级、机会类型、风险提示或反推荐理由。推荐卡片保留：

- 当前状态
- 截止时间、紧急程度
- `内容概括`：由 DeepSeek 在推荐生成阶段生成；没有 Key 或调用失败时使用本地规则 fallback
- `相关性`：由 DeepSeek 分析文章内容与用户画像的关系；没有 Key 或调用失败时使用本地规则 fallback
- 行动建议和工具/反馈按钮

推荐生成阶段的模型输出会保存到 `content_overview` 和 `relevance_explanation`，同时可返回 `relevance_score`、`benefit_score` 作为排序校正信号。排序公式仍由 `matching_service` 控制，避免完全依赖模型不可解释判断。

## 按需工具调用

默认流水线只做文章导入、机会抽取、初步推荐和排序。核验、补全、日历、待办只在用户点击某条机会时触发。

支持 action：

- `verify`：核验真实性，更新 `verification_status`、`credibility_score`、`risk_level`、`risk_flags` 等字段。
- `enrich`：补全官方链接、报名链接、deadline、地点、要求等字段，无法确认则返回 `unknown`。
- `calendar`：把具有明确日期的机会写入本地日历表，并支持导出 `.ics`。
- `todo`：生成行动待办清单。

完整调用示例：

1. 用户在推荐卡片看到“AI 实验室春季本科生科研助理招募”。
2. 点击“核验真实性”。
3. 前端调用 `POST /opportunities/1/actions`，请求体为 `{"user_id": 1, "action": "verify", "extra_params": {}}`。
4. `OpportunityAgent` 读取 opportunity 和 user_profile，选择 `VerifyOpportunityTool`。
5. `VerifyOpportunityTool` 通过本地规则检查信息完整性和风险词；它不能替代官网核验。
6. 系统写入 `tool_call_logs`，并更新 opportunity 的核验字段。
7. 推荐卡片展示“仅本地规则检查 · 未联网核验”；本地检查不生成真实证据、可信度分数或 `verified` 状态。

## Growth Memory

本项目使用轻量成长记忆：用户行为先写入结构化事件表，用户主动点击生成时，再压缩成五部分成长记忆快照。

不做：

- 不保存完整历史对话。
- 不把全部用户行为塞进 Prompt。
- 不引入向量数据库。
- 不构建聊天机器人式 Memory。

成长记忆快照会提供给机会助理、AI 推进和增强推荐模块使用。推荐按用户读取最新快照并传入模型评分上下文，带快照 ID 和提示词版本；显式画像目标优先。无 Key 时排序继续使用确定性规则和反馈加权，不把记忆文本任意转成分数。旧的 `memory_reflections` 表与检索器仅为兼容历史数据保留，不再由推荐路径读取。

## API

- `POST /profiles`
- `GET /profiles`
- `GET /profiles/{user_id}`
- `PUT /profiles/{user_id}`
- `DELETE /profiles/{user_id}`
- `POST /articles/import`
- `GET /articles`
- `POST /pipeline/process`
- `GET /opportunities`
- `POST /recommendations/generate/{user_id}`
- `GET /recommendations/{user_id}`
- `POST /tools/{tool_name}`
- `POST /opportunities/{opportunity_id}/actions`
- `POST /opportunities/{opportunity_id}/actions/verify`
- `POST /opportunities/{opportunity_id}/actions/enrich`
- `POST /opportunities/{opportunity_id}/actions/calendar`
- `POST /opportunities/{opportunity_id}/actions/todo`
- `POST /memory/events`
- `GET /memory/events/{user_id}`
- `POST /memory/{user_id}/generate`
- `GET /memory/{user_id}/latest`
