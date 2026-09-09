from alembic import context
from sqlalchemy import create_engine

from app.core.config import get_settings
from app.core.migrations import backup_sqlite_database
from app.core.database import Base
from app.models import entities  # noqa: F401


def run_online(connection):
    if connection.dialect.name != "sqlite":
        raise RuntimeError("当前迁移仅验证并支持 SQLite；其他数据库需要独立适配与测试。")
    # SQLite batch ALTER rebuilds a table. Disable FK enforcement only on this
    # migration connection, then check all references before committing.
    foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar()
    connection.commit()
    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    connection.commit()
    try:
        with connection.begin():
            # sqlite3 legacy mode otherwise auto-commits DDL. This also
            # serializes competing startup migrations and their version checks.
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            context.configure(connection=connection, target_metadata=Base.metadata,
                              render_as_batch=True, transactional_ddl=True)
            migration = context.get_context()
            destination = migration.opts.get("destination_rev")
            if destination is not None:
                target = {revision.revision for revision in context.script.get_revisions(destination)}
                if set(migration.get_current_heads()) != target:
                    backup_sqlite_database(connection)
            with context.begin_transaction():
                context.run_migrations()
            violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchmany(5)
            if violations:
                raise RuntimeError(f"数据库存在外键冲突，迁移已回滚（前 5 条）：{violations}")
    finally:
        connection.exec_driver_sql(f"PRAGMA foreign_keys={int(foreign_keys)}")
        connection.commit()


if context.is_offline_mode():
    raise RuntimeError("此迁移需要读取旧正文并回填哈希，请使用在线 upgrade，不支持 --sql。")

supplied = context.config.attributes.get("connection")
if supplied is not None:
    run_online(supplied)
else:
    engine = create_engine(get_settings().database_url, connect_args={"timeout": 30})
    try:
        with engine.connect() as connection:
            run_online(connection)
    finally:
        engine.dispose()
