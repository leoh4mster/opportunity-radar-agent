"""Safe SQLite schema upgrades and consistent, local-only backups."""
import argparse
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect


logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Alembic's environment proxies are process-global, not thread-local. SQLite's
# BEGIN IMMEDIATE handles separate processes; this guards calls within one.
_MIGRATION_LOCK = RLock()


def migration_config() -> Config:
    return Config(str(PROJECT_ROOT / "alembic.ini"))


def backup_sqlite_database(connection):
    """Use SQLite's backup API (includes committed WAL), never copy just .db."""
    database = connection.engine.url.database
    if not database or database == ":memory:":
        return None
    if not set(inspect(connection).get_table_names()) - {"alembic_version"}:
        return None
    source_path = Path(database).resolve()
    directory = source_path.parent / ".backups"
    directory.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = directory / f"{source_path.stem}-{timestamp}-{uuid4().hex[:8]}.db"
    source = sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True, timeout=30)
    destination = sqlite3.connect(str(target))
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    logger.warning("数据库升级前备份：%s", target)
    return target


def upgrade_database(engine, revision="head") -> None:
    with _MIGRATION_LOCK:
        config = migration_config()
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, revision)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["upgrade", "current", "backup"], default="upgrade", nargs="?")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from app.core.database import engine
    if args.action == "upgrade":
        upgrade_database(engine)
        print("数据库已升级到最新版本。")
    elif args.action == "current":
        command.current(migration_config(), verbose=True)
    else:
        with engine.connect() as connection:
            path = backup_sqlite_database(connection)
        print(path or "空数据库，无需备份。")


if __name__ == "__main__":
    main()
