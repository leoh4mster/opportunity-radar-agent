# Opportunity Radar Agent 交接记录

最后更新：2026-09-26（Asia/Shanghai）

## 0. 2026-09-26 业务正确性修复与当前进度

本节为最新状态；后面的 1–9 节保留 2026-09-16 交接背景，旧测试数、迁移版本、端口状态和提交状态不代表现在。

### 已完成

- 本地核验不再生成占位证据、可信度分数或真实 `verified` 状态；原文链接不再直接补为官网或报名链接。
- 待办 action 和旧工具入口统一调用实际持久化服务；待办、状态、行为和日志在同一事务内提交。
- 计划子任务通过 `task_key=plan-item:<ID>` 与机会总待办区分，重复同步幂等、整批失败回滚。
- 删除文章或用户清理完整关联图，包括日历、推进任务/计划/版本/更新；运行时开启 SQLite 外键约束。
- 新增迁移 `0003_business_integrity`，保留旧待办与推荐 ID；历史计划项恢复为待同步。明确属于本地规则的旧核验被降为 `rule_checked`，撤销旧加权，建议刷新推荐。
- 推荐使用最新 `GrowthMemorySnapshot` 作为增强模型上下文，携带版本；本地模式仍使用规则和反馈加权。记忆输入保留明确反馈文字。
- 模型结果增加字段、类型、数值范围和有限值校验；摘要验证失败不会误返回成功；严格评测模式无配置时拒绝规则回退。
- 标注台不预填模型答案；排序必须逐项明确判断，切换记录隔离控件状态。

### 验证与数据边界

- 本机 Python 3.9.6：93 项测试通过，含完整 API 流程、故障回滚和 Streamlit 控件测试。
- 合成抽取 15 例 F1 1.0、字段 40/40；排序 3 组 NDCG@3 1.0、Precision@3 0.6667。
- 已对现有个人 SQLite 的临时副本完成升级演练，业务记录数量保持一致、外键检查无违规；测试不修改个人数据库。
- 用户已在 `evaluation/private/review-2026-09-26/` 完成 9 篇抽取、1 组排序的首次确认（labeled，不是二次 reviewed）。原始队列仍未标注，后续请用复核目录。
- 修复前真实规则报告位于该目录 `reports/rules-20260926T061741Z/`。修复后同批开发集 F1 0.8889→1.0、字段 13/20→20/20；排序 NDCG@3 仍 1.0、Precision@3 仍 0.3333。该批已用于调试，不能声称独立泛化性能。
- 新增主办方/字段/叙述日期抽取与攻略/回顾/取消边界；明确结束活动降权且不建议报名。未知年份和不完整区间保守处理；尚未实现推荐展示过滤，也不会重写历史机会数据。
- 默认 DeepSeek 模型改为 deepseek-flash，非思考模式、单次输出上限 4096；新增严格的一次虚构数据连通检查。当前 Key 尚未配置，未调用真实模型或外发私人正文。详见 `docs/DEEPSEEK.md`。
- 本轮用户已授权完成检查后提交并推送 GitHub。提交和 CI 结果以 Git 历史及 GitHub Actions 为准，不把测试结果当作远程 CI 已通过。

### 后续执行顺序

1. 用户可立即申请并在本机 .env 配置 DeepSeek Key；先执行一次虚构文本检查，明确同意正文外发与费用后运行真实模型对比，再验收计划—工具执行—结果反馈闭环。同时扩充独立保留集和第二次标注复查。
2. 可靠任务机制：文章先落库、调用移出写事务，增加原子领取、租约、有限重试与重启恢复。现有 daemon thread 和进程内锁尚未重构。
3. 独立 Collector：先纯 Python 数据与传输边界、持久化补传、dry-run 和假 transport 测试，再接剪贴板/GUI/OCR。旧采集器仍不能作为可靠自动采集链路。
4. 日期/时区、列表分页和前端拆分；随后按实际部署目标补认证、权限隔离与部署方案。

启动与人工标注命令仍见下文；新迁移不能自动 downgrade 合并待办，回退须使用升级前备份和对应旧代码，详见 `opportunity-radar-agent/docs/DATABASE.md`。

## 1. 当前任务与目标

把最初从小组 GitHub 仓库取得的 AI Agent 代码，清理为用户本人可完全控制、无需原作者权限也能运行的独立项目，并持续完善为可用于实习/求职面试展示的代表项目。

项目定位不是普通文章摘要工具，而是一条可持续运行的机会决策链：

```text
公众号文章 / 本地文件
  → 结构化机会抽取
  → 用户画像匹配与排序
  → 风险核验、待办和日历
  → 行为反馈
  → 成长记忆与下一步建议
```

当前阶段的重点已经从“能运行”推进到“结果可验证、工程过程可解释”。最近完成的是人工标注与真实数据评测工具链；下一项拟进行的工程工作是整理桌面采集实验并形成独立 Collector 模块。

## 2. 仓库与运行状态

- 工作区根目录：`/Users/zhouyuehan/Documents/code/Agent-wechat-summary`
- 主应用目录：`opportunity-radar-agent/`
- 当前分支：`main`
- 远程仓库：`https://github.com/leoh4mster/opportunity-radar-agent.git`
- 当前提交：`1e77444 feat: add human-labeled evaluation workflow`
- `main` 与 `origin/main` 已同步。
- 创建本文档前 Git 工作区干净；`HANDOFF.md` 是本次新增文件。
- 最近一次确认的 GitHub Actions：Python 3.9、3.12 均通过。
  - Run：<https://github.com/leoh4mster/opportunity-radar-agent/actions/runs/34331166219>
- 最近一次本地全量测试：54 项通过。
- 截至 2026-09-16，本机仍有进程监听：
  - FastAPI：`127.0.0.1:8000`
  - Streamlit 主界面：`127.0.0.1:8501`
  - Streamlit 人工标注台：`127.0.0.1:8502`

端口监听只是当前机器状态，不应假设下次会话仍在运行。访问失败时先重启相应服务。

## 3. 已完成内容

### 3.1 项目归属与安全清理

- 已迁移到用户自己的 GitHub 仓库和提交历史，当前历史从安全导入提交开始。
- 旧开发者的密钥不再存在于当前代码配置中。
- `.env`、数据库、日志、虚拟环境、采集截图及私有评测数据均被 Git 忽略。
- `.env.example` 只保留空配置模板。
- DeepSeek、博查搜索和微信 MCP 都是可选依赖；没有 Key 时基础流程仍能运行。
- 曾经公开过的旧密钥仍应视为已泄露，由原密钥持有人在对应平台撤销；清理 Git 历史不能让已经暴露的密钥重新安全。

### 3.2 产品总览与基础体验

- 增加 Streamlit 产品总览页面，展示文章、机会、推荐、处理进度、行动状态和可选能力状态。
- 支持用户画像管理、文章库、机会库、推荐卡片、反馈、待办、日历和成长记忆。
- 修复 Streamlit 首次启动交互导致的无法访问问题；启动脚本关闭遥测提示并绑定本机地址。
- 无 Key 时使用确定性本地规则完成抽取和推荐说明，不因缺少原开发者账号而无法演示。

### 3.3 导入、事务和并发可靠性

- 支持浏览器上传 JSON、TXT、Markdown，含 UTF-8 BOM。
- 单文件限制 2 MiB、最多 500 篇；非法格式、空正文和错误编码会被拒绝。
- 批次先整体校验再写入，失败时整批回滚。
- 文章正文由服务端规范化后计算 SHA-256；客户端传入哈希不作为可信身份。
- `articles.content_hash` 已持久化并具有数据库唯一约束。
- 上传、路径导入、采集接口共用相同去重语义。
- 已测试 8 个并发上传/采集请求只创建一篇文章、只抽取一次。
- 已覆盖保存点、事务回滚、SQLite WAL 备份和并发迁移。

### 3.4 数据库迁移

- 接入 Alembic。
- `0001_baseline` 是冻结的初始结构。
- `0002_article_identity` 增加文章内容哈希及唯一约束。
- 旧 SQLite 升级前会创建一致性备份。
- 遇到旧库重复正文时迁移会停止并回滚，不擅自删除或合并用户数据。
- 并发启动迁移已做串行化测试。

### 3.5 可观测性

- 每个 HTTP 请求带 `X-Request-ID`，可关联响应和后端日志。
- 默认输出结构化 JSON 日志，不记录正文、请求参数、提示词或密钥。
- 记录 HTTP 状态、耗时、慢路由、LLM 调用/重试/失败和本地回退原因。
- 总览页提供“工程运行状态”展示。
- `GET /observability/metrics` 返回当前单进程指标。
- 指标明确是内存级、单进程级，重启会清零，不冒充生产监控平台。

### 3.6 离线抽取回归

- `evaluation/cases.json` 有 15 条手写虚构案例：10 条机会、5 条非机会。
- 本地规则当前回归结果：
  - Precision：0.7692
  - Recall：1.0000
  - F1：0.8696
  - 字段精确匹配率：0.9750
- 已知失败案例：自然语言日期漏抽，以及回顾、取消、经验指导文章误报。
- CI 会运行 `python -m evaluation.run --check`，指标下降时失败。
- 这些数字只用于代码回归，不能称为真实业务准确率或 DeepSeek 效果。

### 3.7 人工标注与真实数据评测工具链

- 新增版本化 JSONL 数据结构和原子写入。
- 新增本地人工标注台：`evaluation/annotation_app.py`。
- 私有标注文件只能写入 `evaluation/private/`，该目录不会进入 Git。
- 模型现有输出只作为 `model_suggestions` / `model_order` 展示，不会自动成为人工真值。
- 抽取评测支持：
  - 文章级机会检测；
  - 一篇多机会的一对一匹配；
  - Precision / Recall / F1；
  - 总体与分字段精确匹配；
  - 失败案例 ID。
- 推荐排序评测支持：
  - 0～3 分级相关性；
  - NDCG@K、MRR、Hit Rate@K、Precision@K；
  - Pairwise Accuracy；
  - 固定 `as_of` 日期，防止截止时间随运行日期漂移。
- 每份数据和基线绑定数据指纹，数据改变后不会静默沿用旧门槛。
- 仓库包含三组虚构排序回归案例，当前 NDCG@3、MRR、Hit Rate@3、Pairwise Accuracy 均为 1.0；这仍然只是合成回归成绩。
- DeepSeek 评测必须同时满足：
  1. 选择 `deepseek` 或 `compare` 模式；
  2. 显式添加 `--allow-network`；
  3. 配置用户自己的有效 Key。
- 远程评测使用严格模式。DeepSeek 失败时不会把本地规则回退结果伪装成 DeepSeek 成绩。

### 3.8 关键提交

```text
beec111  Initial secure project import
83165b8  feat: add product dashboard and quality foundation
3483388  fix: make frontend startup non-interactive
e16b23d  feat: add validated article uploads and offline evaluation baseline
09b493c  feat: add safe migrations and concurrent article deduplication
690fa83  feat: add request tracing and agent runtime metrics
1e77444  feat: add human-labeled evaluation workflow
```

## 4. 当前没有完成 / 卡住的事项

### 4.1 真实人工标签尚未完成

这不是程序故障，而是必须由人做判断的评测步骤。不能让模型用自己的输出给自己打分。

当前本机私有队列：

- `evaluation/private/extraction.jsonl`
  - 9 条记录
  - 已标注 0
  - 待标注 9
  - 指纹：`071b511acc4206b0fb699edb0223b8c255b5d7bd2ff8fde23fd6906054e3c6b2`
- `evaluation/private/ranking.jsonl`
  - 1 组画像
  - 5 个候选机会
  - 已标注 0
  - 待标注 1 组
  - 指纹：`ab6766ff6d4a5e3cf7bf60ec4273469e555b7bbe57ef982e7cde65bad255e8d4`

因此当前不能声称项目已经取得真实准确率，也不能做可信的规则与 DeepSeek 对比。

### 4.2 尚未申请用户自己的外部服务 Key

- 当前不需要 Key 即可运行基础产品和离线评测。
- 完成人工标签后，才值得申请自己的 DeepSeek API Key 做公平对比。
- 联网核验另需自己的博查 Key；微信搜索另需兼容 MCP 服务。
- 任何真实 Key 只能放在本地 `.env` 或操作系统环境变量中，不能写入代码、文档、截图或 CI。

### 4.3 Collector 尚未正式整理

- 当前桌面采集实验仍位于上级目录 `pyautogui/scripts/`。
- 它把第三方 PyAutoGUI 源码、副本、定制脚本、硬编码坐标和可选视觉模型调用混在一起。
- 现有采集脚本不属于基础启动必需部分，也没有进入主项目的 CI。
- 曾尝试开始创建 `opportunity-radar-agent/collector/`，但生成的补丁不完整；相关文件已经全部删除，未暂存、未提交，随后 54 项测试全部通过。当前应从干净状态重新设计，不能假设已有半成品。

### 4.4 仍不适合直接公网部署

- 当前没有登录、用户权限隔离、限流和公网导入目录限制。
- SQLite 适合本地演示，不适合多实例并发部署。
- `/observability/metrics` 未鉴权，只应在本机使用。
- 现有后台线程适合单进程演示，不是可靠任务队列；进程退出后任务可能中断。

## 5. 下一步建议顺序

### 优先级 1：完成人工标注并生成第一份真实报告

1. 打开 <http://127.0.0.1:8502>。
2. 标完 9 篇抽取案例。
3. 把左侧数据集改为 `evaluation/private/ranking.jsonl`，标完 1 组排序案例。
4. 对重要标签进行第二次复查，再标为 `reviewed`。
5. 运行完整性检查和本地规则评测。
6. 扩展到更多来源、负例、一文多机会和不同画像；9 篇文章远不足以支持泛化结论。

完成这一步后再申请 DeepSeek Key，运行相同数据指纹下的规则/DeepSeek 对比。报告必须同时写样本量、类别分布、日期、模型版本和局限。

### 优先级 2：重构独立 Collector 模块

建议分阶段完成，避免直接搬运旧 GUI 脚本：

1. 先在 `opportunity-radar-agent/collector/` 建立纯 Python 数据边界：文章对象、清洗、服务端提交、超时、有限重试、错误分类和 dry-run。
2. 默认只允许向 `127.0.0.1` / `localhost` 发送正文；如允许远程后端，必须显式开启，防止私有公众号正文误传。
3. 为传输层使用假的 HTTP transport 写单元测试，不依赖真实网络、微信客户端或屏幕权限。
4. 再把剪贴板采集做成可选适配器，并把坐标、等待时间和输出目录移到配置中。
5. 视觉定位/OCR 做成独立可选 provider；没有 `VISION_API_KEY` 时应给出明确提示或使用手动选择，不得硬编码旧开发者服务。
6. 旧 `pyautogui/scripts/` 保留为实验参考，确认新模块可替代后再做删除或归档，避免一次大搬迁破坏可追溯性。

### 优先级 3：拆分长事务和任务执行

- 当前采集入库与机会抽取处于同一数据库事务。
- 使用远程模型时，长调用会延长 SQLite 写锁。
- 建议引入持久化任务表，至少记录 `queued/running/succeeded/failed`、尝试次数、错误类型和更新时间。
- 先提交文章，再由 worker 抽取；重启后可恢复未完成任务。
- 必须设计 claim/lease 或唯一约束，避免多 worker 重复抽取。
- 不要只换成 daemon thread 后就宣称“可靠异步任务队列”。

### 优先级 4：部署与权限

1. 增加登录和用户数据隔离。
2. 为敏感 API、指标接口和导入接口增加权限及限流。
3. 将 SQLite 替换为 PostgreSQL，并验证迁移策略。
4. 再增加 Docker/Compose 或云端部署方案、健康检查和持久卷。
5. 最后补产品截图、演示视频和一份真实评测摘要，形成完整面试材料。

## 6. 常用命令

以下命令均在 `opportunity-radar-agent/` 目录执行。

### 启动

```bash
sh run_backend.sh
sh run_frontend.sh
sh run_annotation.sh
```

对应地址：

- 主界面：<http://127.0.0.1:8501>
- API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>
- 标注台：<http://127.0.0.1:8502>

### 测试与回归

```bash
LOG_LEVEL=ERROR .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m evaluation.run --check
.venv/bin/python -m evaluation.real_data evaluate ranking evaluation/ranking_cases.jsonl --mode rules --k 3 --baseline evaluation/ranking_baseline.json
PYTHONPYCACHEPREFIX=/private/tmp/opportunity-radar-pycache .venv/bin/python -m compileall -q app evaluation frontend migrations tests
.venv/bin/python -m pip check
```

### 私有标注进度

```bash
.venv/bin/python -m evaluation.real_data validate evaluation/private/extraction.jsonl
.venv/bin/python -m evaluation.real_data validate evaluation/private/ranking.jsonl
```

标完后增加 `--require-complete`：

```bash
.venv/bin/python -m evaluation.real_data validate evaluation/private/extraction.jsonl --require-complete
.venv/bin/python -m evaluation.real_data validate evaluation/private/ranking.jsonl --require-complete
```

### 本地规则真实数据评测

```bash
.venv/bin/python -m evaluation.real_data evaluate extraction evaluation/private/extraction.jsonl --mode rules --output evaluation/private/reports/extraction-rules.json
.venv/bin/python -m evaluation.real_data evaluate ranking evaluation/private/ranking.jsonl --mode rules --k 3 --output evaluation/private/reports/ranking-rules.json
```

### 未来配置自己的 DeepSeek 后对比

```bash
.venv/bin/python -m evaluation.real_data compare extraction evaluation/private/extraction.jsonl --allow-network --output evaluation/private/reports/extraction-compare.json
.venv/bin/python -m evaluation.real_data compare ranking evaluation/private/ranking.jsonl --allow-network --k 3 --output evaluation/private/reports/ranking-compare.json
```

不要在标注未完成时运行，也不要在未理解数据会发送给第三方及可能产生费用时添加 `--allow-network`。

## 7. 已踩过的坑与操作注意事项

### 7.1 `127.0.0.1:8501` 无法访问通常是服务未启动

- 浏览器显示 `ERR_CONNECTION_REFUSED` 代表对应端口没有可接受连接的进程，不是网页本身 404。
- 先运行后端，再运行前端。
- Streamlit 和 Uvicorn 必须分别保持运行；关闭终端会停止服务。
- `uvicorn --reload` 会出现 reloader 和 worker 两个 PID，这是正常现象，不代表重复启动两个独立后端。

### 7.2 沙箱内 `curl` 失败不一定代表本机服务没启动

- 受限环境中直接访问 localhost 可能被拦截。
- 先用 `lsof -nP -iTCP:8000 -iTCP:8501 -iTCP:8502 -sTCP:LISTEN` 查看监听。
- 需要时再在获准的本机网络环境中执行健康检查。

### 7.3 macOS Python 字节码缓存权限

在受限环境运行 `compileall` 时，Python 可能试图写入 `~/Library/Caches` 并报 `PermissionError`。这不是语法错误。使用：

```bash
PYTHONPYCACHEPREFIX=/private/tmp/opportunity-radar-pycache .venv/bin/python -m compileall -q app evaluation frontend migrations tests
```

### 7.4 测试中的 ERROR 日志可能是预期行为

部分测试故意注入存储失败、500 异常和 LLM 失败来验证回滚与脱敏。只要 unittest 最终是 `OK`，这些 ERROR 日志不表示测试失败。

### 7.5 不要把模型建议当人工标签

- `model_suggestions` 和 `model_order` 只用于辅助查看。
- 数据指纹和指标会忽略这些建议。
- 自动接受建议会造成循环论证，使评测失去意义。

### 7.6 不要随意修改正文哈希规则

- v1 规则会删除全部空白后计算 SHA-256。
- 它可能合并某些仅靠空格区分语义的英文文本，是已知边界。
- 更换规则必须新建迁移/版本，不能直接修改历史迁移或现有数据库语义。

### 7.7 不要在数据库写事务中无限等待远程模型

- 当前长事务问题已经记录但尚未重构。
- DeepSeek 延迟或重试可能导致 SQLite 锁等待。
- 在完成持久化任务队列前，不应提高并发或增加多 worker 后假设问题已解决。

### 7.8 私有仓库 CI 查询

- 本机没有安装 `gh` 时，`gh run list` 会失败。
- 私有仓库对未认证 GitHub API 可能返回 404。
- 如需脚本查询，应安全复用 Git credential helper，确保 token 只留在进程内，不打印、不写文件；更简单的方式是直接打开 GitHub Actions 页面查看。

### 7.9 文件编辑与 Git

- 本地数据库、备份、私有评测文件和 `.env` 属于用户数据，不要暂存或提交。
- 提交前执行 `git diff --check`、敏感信息扫描和 `git status --short --ignored`。
- 不要使用 `git reset --hard`、`git checkout --` 等破坏性命令清理用户修改。
- 新功能先本地测试，再提交、推送并确认 Python 3.9/3.12 CI。

## 8. 重要文档入口

- 项目总览：`README.md`
- 主应用说明：`opportunity-radar-agent/README.md`
- 真实数据评测：`opportunity-radar-agent/docs/EVALUATION.md`
- 导入可靠性与抽取评测：`opportunity-radar-agent/docs/QUALITY.md`
- 可观测性：`opportunity-radar-agent/docs/OBSERVABILITY.md`
- 数据库迁移与恢复：`opportunity-radar-agent/docs/DATABASE.md`
- 面试讲解：`opportunity-radar-agent/docs/INTERVIEW_GUIDE.md`
- 架构设计：`opportunity-radar-agent/docs/design.md`

## 9. 给下一位执行者的简短结论

项目当前是可运行、可测试、可离线演示的本地优先 Agent，安全清理、总览、导入可靠性、迁移、并发去重、可观测性和评测基础设施已经完成。最重要的事实是：真实标签仍为 0，不能宣传真实准确率。下一步先推动人工标注，同时从干净状态重做独立 Collector；不要恢复旧密钥，不要上传私有正文，也不要用模型输出给模型自己打分。
