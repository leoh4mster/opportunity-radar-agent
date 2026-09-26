# 数据库迁移与数据安全

## 这次变化

- `0001_baseline`：接管未记录版本的旧库，补齐已知历史可选字段，空库创建初始表。使用冻结结构，不引用未来会变化的 ORM 模型。
- `0002_article_identity`：回填去空白正文的 SHA-256，增加 `content_hash NOT NULL` 和命名唯一约束 `uq_articles_content_hash`。
- `0003_business_integrity`：待办身份变为用户、机会和 `task_key` 的组合；机会总待办使用 `opportunity`，计划子任务使用 `plan-item:<ID>`。保留原待办及其 ID，把历史计划项恢复为待同步，防止继续把不同任务视为同一待办。
- 后端、seed 共用 Alembic 启动升级，移除 `create_all + 临时 ALTER TABLE` 的运行时补丁。

第三版迁移同时将有明确本地规则特征或占位证据链接的历史 `verified` 改为 `rule_checked`，清除这些机会的虚假证据、可信度分数和核验时间，并撤销符合旧加权条件的推荐的 5 分奖励。推荐记录及 ID 保留；由于旧评分可能经过封顶或其他调整，迁移后的扣分是保守修正，应在界面重新生成推荐。其他核验记录不受此规则影响。

运行时 SQLite 连接现在开启外键约束。删除文章或用户会在同一事务中按依赖顺序清理日历、待办、推进任务、计划、版本、更新和工具记录。文章删除保留用户行为历史；用户删除会清理该用户的行为与记忆。已有孤立数据仍会阻断升级，不自动删除。

当前迁移仅支持 SQLite；不宣称兼容 PostgreSQL/MySQL。回填必须读取旧正文，不支持 `--sql` 离线脚本。文章表在 SQLite 中通过批量重建修改约束，但所有原列、文章 ID 和关联数据保留；不是清库重新导入。

## 日常使用

在主项目目录、激活虚拟环境后执行：

```bash
python -m pip install -r requirements.txt
python -m app.core.migrations current
python -m app.core.migrations upgrade
```

`DATABASE_URL` 仍从环境变量或本地 `.env` 读取，默认 `sqlite:///./opportunity_radar.db`。请在主项目目录运行，避免相对路径指向另一个数据库。
也支持标准 `python -m alembic current`、`python -m alembic history`、`python -m alembic upgrade head`。
迁移前停止后端及其他写入进程；迁移成功后再启动后端。日常启动会自动确认并升级版本，无需每次手工执行。

## 备份和失败策略

已有非空业务库发生版本变化前，自动通过 SQLite backup API 生成 `.backups/<数据库名>-<UTC时间>-<随机后缀>.db`。它包含 WAL 中已提交的数据，不是只复制主 `.db` 文件。无版本变化或空库不创建备份，备份文件被 Git 忽略，但仍包含个人数据，应妥善保管。

升级用显式 `BEGIN IMMEDIATE` 包住结构变更、回填和版本标记；两次并发启动会依次检查迁移版本。连接级外键检查在批量表重建期间暂时关闭，提交前执行 `foreign_key_check`，结束后恢复原设置。遇到异常回滚，不强行标记为完成。

历史重复正文会列出冲突文章 ID（最多 10 对），并停止升级；不会擅自删除文章、合并推荐或丢弃用户行为。请保留备份，人工决定如何处理冲突后再重试。不要用 `stamp head` 绕过失败，也不要为了启动而删数据库。未知旧结构或外键冲突同样会阻断。

手动创建一致性备份：

```bash
python -m app.core.migrations backup
```

恢复时：

1. 停止后端和全部数据库写入程序。
2. 先把当前数据库及同名 `-wal`、`-shm` 文件移到一个单独的保留目录，不要直接删除。
3. 将选定备份**复制**到 `DATABASE_URL` 指向的位置并恢复原数据库文件名；不要混用旧 WAL 文件。
4. 若要回到升级前版本，还应切回匹配的代码；否则新代码启动会再次迁移。恢复备份会失去备份时点之后的新增数据，操作前确认备份时间。

`0003_business_integrity` 不提供自动 downgrade：恢复旧唯一约束可能需要合并或删除多个待办，也不应恢复虚假的历史核验结论。需要回退时，停止服务并恢复升级前备份及对应代码。仅仍位于 `0002_article_identity` 的受控测试库可以降到 `0001_baseline` 来验证哈希迁移；禁止对运行中的服务执行降级。

## 后续开发规则

修改模型后生成新迁移，不编辑已经发布的历史版本：

```bash
python -m alembic revision --autogenerate -m "describe schema change"
```

自动生成后必须人工审阅，尤其是默认值、历史数据回填、表重建和不可逆操作；再在临时数据库上验证。历史哈希算法已冻结，改变空白规则必须另做数据迁移与冲突处理。

```bash
python -m unittest discover -s tests -v
```

测试不会升级个人数据库。涵盖迁移与模型一致、旧 ID 和关联数据保留、旧可选列补齐、重复阻断且结构回滚、唯一/非空约束、WAL 备份、重复启动与并发启动、哈希版本降级后再升级、真实 HTTP 并发去重，以及后续写入失败时保存点的整批回滚。
