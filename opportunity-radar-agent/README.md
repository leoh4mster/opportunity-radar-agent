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

## 可选：配置你自己的 DeepSeek

基础演示不需要执行这一步。准备使用大模型时，在 DeepSeek 官方平台创建 API Key，然后编辑本项目的 `.env`：

```text
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
DEEPSEEK_API_KEY=你自己的密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

`.env` 已被 Git 忽略。不要把真实密钥写进 Python 文件、README、截图或提交记录。

配置后可以调用 `POST /llm/test` 检查连接。

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
