# 个性化公众号机会雷达 Agent

这是一个本地优先的演示项目：导入公众号文章文本，抽取竞赛、实习、科研、讲座等机会，再根据用户画像排序，并帮助用户生成待办、日历提醒和推进计划。

## 默认模式：无需 API Key

项目默认可以在没有任何外部服务账号或 API Key 的情况下运行：

- 文章机会抽取使用本地规则兜底。
- 推荐排序使用本地评分与本地说明。
- 用户画像、文章库、机会库、待办和日历使用本地 SQLite。

本地规则适合验证流程，但理解能力不如大模型。配置你自己的 DeepSeek Key 后，可以启用更高质量的文章抽取、机会助理、成长记忆和 AI 推进计划。

## 项目结构

```text
opportunity-radar-agent/
  app/                 FastAPI 后端
    api/               API 路由
    core/              配置和数据库
    models/            SQLAlchemy 数据模型
    schemas/           API 数据结构
    services/          抽取、推荐、记忆、搜索和推进服务
  frontend/            Streamlit 前端
  data/                可直接导入的示例公众号文章
  docs/                设计说明
  migrations/          Alembic 历史版本与冻结的初始结构
  requirements.txt     Python 依赖
```

## 首次启动

需要 Python 3.9 或更高版本。

### macOS / Linux

```bash
cd opportunity-radar-agent
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
python -m app.seed
sh run_backend.sh
```

另开一个终端：

```bash
cd opportunity-radar-agent
sh run_frontend.sh
```

### Windows PowerShell

```powershell
cd opportunity-radar-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m app.seed
.\run_backend.ps1
```

另开一个 PowerShell：

```powershell
cd opportunity-radar-agent
.\run_frontend.ps1
```

打开：

- 前端：http://127.0.0.1:8501
- API 文档：http://127.0.0.1:8000/docs
- 健康检查：http://127.0.0.1:8000/health
- 总览接口：http://127.0.0.1:8000/dashboard/summary
- 运行指标：http://127.0.0.1:8000/observability/metrics

## 运行测试

项目测试不依赖 API Key 或网络：

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m evaluation.run --check
python -m evaluation.real_data evaluate ranking evaluation/ranking_cases.jsonl --mode rules --k 3 --baseline evaluation/ranking_baseline.json
python -m compileall -q app evaluation frontend migrations tests
```

GitHub Actions 会在 Python 3.9 和 3.12 上自动执行同一套检查。

页面左侧现在可直接上传 JSON / TXT / Markdown，支持 UTF-8 BOM，最多 2 MiB、500 篇。批次先整体校验再写入，重复导入会跳过。接口及评测指标说明见 [QUALITY.md](docs/QUALITY.md)。

每个 API 响应都带 `X-Request-ID`，后端默认输出不含正文、查询参数和密钥的 JSON 日志。总览页的「工程运行状态」展示当前进程的 API、错误、耗时、模型调用和本地回退；语义与限制见 [OBSERVABILITY.md](docs/OBSERVABILITY.md)。

真实数据评测采用 Git 忽略的本地标注集：可从 SQLite 导出文章和候选机会，用独立的 Streamlit 工作台标注，再计算多机会抽取与推荐排序指标。当前已准备 9 篇文章和 1 组候选，但尚未完成人工标签，因此不会宣称真实准确率。完整流程见 [EVALUATION.md](docs/EVALUATION.md)。

## 数据库升级与备份

后端和 `python -m app.seed` 启动时会自动执行 Alembic 升级，不再用临时 `ALTER TABLE` 补字段。
已有 SQLite 升级前自动备份到数据库旁的 `.backups/`；保留文章、机会、推荐及其 ID。
重复启动不重复迁移或备份。旧库若存在重复正文，会报告冲突文章 ID 并回滚，不自动删除或合并。

更新代码后先安装新增依赖，再重启后端：

```bash
python -m pip install -r requirements.txt
python -m app.core.migrations current
python -m app.core.migrations upgrade
```

也可使用 `python -m alembic current`、`python -m alembic upgrade head`。
执行迁移前应停止其他写入该数据库的进程。详细备份恢复、开发流程与限制见 [数据库迁移说明](docs/DATABASE.md)。

## 可选：配置你自己的 DeepSeek

基础演示不需要执行这一步。准备使用大模型时，在 DeepSeek 官方平台创建 API Key，然后编辑本项目的 `.env`：

```text
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-flash
LLM_THINKING=disabled
LLM_MAX_TOKENS=4096
DEEPSEEK_API_KEY=你自己的密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

`.env` 已被 Git 忽略。不要把真实密钥写进 Python 文件、README、截图或提交记录。

配置后优先运行 `.venv/bin/python -m evaluation.check_deepseek --allow-network`：只发送一条虚构通知，执行一次严格远程检查。配置、真实评测和 Agent 闭环验收步骤见 [DeepSeek 接入说明](docs/DEEPSEEK.md)。

## 业务一致性更新（2026-09-26）

本地规则检查现在明确标记为“未联网核验”。待办入口统一落库，每个推进子任务拥有独立待办身份；删除文章和用户会清理完整关联数据。模型输出增加严格业务校验，成长记忆快照进入增强推荐上下文。标注台采用空白人工标签和“尚未判断”选项。

本地 116 项测试及合成抽取、排序基线通过。数据库迁移包含 `0003_business_integrity` 和 `0004_durable_jobs`，旧库升级前自动备份；历史计划项需要重新同步，原待办保留。恢复方式及历史核验修正见 [数据库说明](docs/DATABASE.md)，验收范围见 [质量说明](docs/QUALITY.md)。

## 真实样本驱动的质量修复（2026-09-26）

已完成首批 9 篇抽取、1 组排序的 AI 辅助人工确认。修复攻略误报、主办方边界、叙述句日期和字段格式；相同开发集抽取 F1 从 0.8889 提升到 1.0、字段匹配从 13/20 提升到 20/20。该批数据已用于优化，不能作为独立测试集或总体准确率。明确结束的活动会降权且不再建议报名；缺少年份、开放区间和实习开始日不会被当成明确结束时间。

DeepSeek 已完成虚构数据、临时数据库上的真实服务链验收：模型抽取、推荐、顾问、多轮计划、用户确认后的待办/日历、进度调整和记忆复用均通过。复测 12 次请求、约 32 秒，零规则回退。复跑命令为 `.venv/bin/python -m evaluation.check_agent_live --allow-network`，报告默认仅保留本地；这不替代真实语料效果、浏览器或后台恢复测试。

## 当前能力边界

- 基础模式不会联网核验机会，重要截止日期和报名入口应查看原文。
- “机会助理”“成长记忆”“AI 推进”需要配置 DeepSeek 才能生成高质量结果。
- 微信搜索需要 Python 3.10+，并另外安装 `requirements-mcp.txt`、启动兼容的 MCP 服务。
- 联网核实需要配置你自己的博查搜索 Key。
- 桌面公众号采集脚本在上级目录 `pyautogui/scripts`，它依赖桌面权限和可选视觉模型，不是基础启动的必要条件。

## 安全约定

- 所有真实凭据只放在本地 `.env` 或操作系统环境变量中。
- 仓库只保留空白的 `.env.example`。
- 不提交 `.db`、`.db-wal`、`.db-shm`、日志和本地虚拟环境。
- 发布到公网前必须增加登录、权限隔离、限流和文件导入目录限制。

### 持久化任务与异步接口

抽取、推荐刷新、推进分析和联网核验统一排队，支持有限重试、租约恢复、阶段复用和重复请求合并。提交接口返回 HTTP 202 与任务标识，页面自动轮询；采集抽取失败保留文章，推荐失败保留旧结果。接口迁移、运行方式和验收边界见 [JOBS.md](docs/JOBS.md)。真实 worker 验收使用虚构数据，6 次模型请求通过；私人数据未外发。
