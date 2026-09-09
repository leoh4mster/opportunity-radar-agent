"""Upgrade real temporary SQLite files, including legacy data and WAL backups."""
import sqlite3
import os
import subprocess
import sys
import tempfile
import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.core.database import Base
from app.core.migrations import PROJECT_ROOT, migration_config, upgrade_database
from app.models.entities import Article  # noqa: F401
from app.services.article_identity import compute_content_hash
from migrations.schema_v1 import metadata as legacy_metadata


def legacy_row(table_name, **overrides):
    """Populate frozen NOT NULL fields without depending on today's models."""
    values = {}
    for column in legacy_metadata.tables[table_name].c:
        if column.nullable:
            values[column.name] = None
        elif isinstance(column.type, sa.DateTime):
            values[column.name] = datetime(2026, 1, 1)
        elif isinstance(column.type, sa.Boolean):
            values[column.name] = False
        elif isinstance(column.type, (sa.Integer, sa.Float)):
            values[column.name] = 0
        else:
            values[column.name] = ""
    values.update(overrides)
    return values


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "test.db"
        self.engine = sa.create_engine(f"sqlite:///{self.path}")
        self.addCleanup(self.engine.dispose)

        @sa.event.listens_for(self.engine, "connect")
        def configure(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")

    def legacy(self):
        legacy_metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            for name, values in [
                ("user_profiles", legacy_row("user_profiles", id=4, name="保留用户")),
                ("articles", legacy_row("articles", id=7, title="保留原文", content="AI 实习\n招募")),
                ("opportunities", legacy_row("opportunities", id=11, article_id=7, name="保留机会")),
                ("recommendations", legacy_row("recommendations", id=13, user_id=4, opportunity_id=11)),
            ]:
                connection.execute(legacy_metadata.tables[name].insert(), values)

    def snapshot(self):
        with self.engine.connect() as connection:
            return {name: connection.exec_driver_sql(f'SELECT * FROM "{name}" ORDER BY id').fetchall()
                    for name in legacy_metadata.tables}

    def test_empty_upgrade_matches_models_and_repeat_is_noop(self):
        upgrade_database(self.engine)
        upgrade_database(self.engine)
        with self.engine.connect() as connection:
            context = MigrationContext.configure(connection)
            self.assertEqual(context.get_current_revision(), "0002_article_identity")
            self.assertEqual(compare_metadata(context, Base.metadata), [])
            self.assertEqual(connection.exec_driver_sql("PRAGMA foreign_keys").scalar(), 1)
        self.assertFalse((self.path.parent / ".backups").exists())

    def test_legacy_rows_ids_references_and_wal_backup_preserved(self):
        self.legacy()
        before = self.snapshot()
        upgrade_database(self.engine)
        with self.engine.connect() as connection:
            for name, rows in before.items():
                columns = ", ".join(f'"{col.name}"' for col in legacy_metadata.tables[name].c)
                after = connection.exec_driver_sql(f'SELECT {columns} FROM "{name}" ORDER BY id').fetchall()
                self.assertEqual(after, rows, name)
            self.assertEqual(connection.exec_driver_sql("SELECT content_hash FROM articles WHERE id=7").scalar(),
                             compute_content_hash("AI 实习\n招募"))
            self.assertEqual(connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall(), [])
        backups = list((self.path.parent / ".backups").glob("*.db"))
        self.assertEqual(len(backups), 1)
        backup = sqlite3.connect(str(backups[0]))
        try:
            self.assertEqual(backup.execute("SELECT id FROM articles").fetchall(), [(7,)])
            self.assertNotIn("content_hash", [r[1] for r in backup.execute("PRAGMA table_info(articles)")])
            self.assertEqual(backup.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        finally:
            backup.close()
        upgrade_database(self.engine)
        self.assertEqual(len(list((self.path.parent / ".backups").glob("*.db"))), 1)

    def test_legacy_optional_columns_are_added_without_losing_profile(self):
        self.legacy()
        with self.engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE user_profiles DROP COLUMN detailed_needs")
            connection.exec_driver_sql("ALTER TABLE opportunities DROP COLUMN risk_flags")
        upgrade_database(self.engine)
        with self.engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql("SELECT name, detailed_needs FROM user_profiles").one(),
                             ("保留用户", ""))
            self.assertEqual(connection.exec_driver_sql("SELECT risk_flags FROM opportunities").scalar(), "[]")

    def test_duplicate_legacy_rows_block_and_roll_back_all_schema_changes(self):
        self.legacy()
        with self.engine.begin() as connection:
            connection.execute(legacy_metadata.tables["articles"].insert(),
                               legacy_row("articles", id=8, content="AI实习招募"))
        before = self.snapshot()
        with self.assertRaisesRegex(RuntimeError, r"重复正文.*7, 8"):
            upgrade_database(self.engine)
        self.assertEqual(self.snapshot(), before)
        inspector = sa.inspect(self.engine)
        self.assertNotIn("alembic_version", inspector.get_table_names())
        self.assertNotIn("content_hash", {c["name"] for c in inspector.get_columns("articles")})

    def test_db_rejects_duplicate_or_null_hash_even_for_raw_sql(self):
        self.legacy()
        upgrade_database(self.engine)
        with self.assertRaises(sa.exc.IntegrityError):
            with self.engine.begin() as connection:
                connection.exec_driver_sql("UPDATE articles SET content_hash=NULL WHERE id=7")
        with self.assertRaises(sa.exc.IntegrityError):
            with self.engine.begin() as connection:
                columns = [c["name"] for c in sa.inspect(connection).get_columns("articles") if c["name"] != "id"]
                names = ", ".join(columns)
                connection.exec_driver_sql(f"INSERT INTO articles ({names}) SELECT {names} FROM articles WHERE id=7")

    def test_hash_revision_downgrade_and_reupgrade_preserve_data(self):
        self.legacy()
        before = self.snapshot()
        upgrade_database(self.engine)
        with self.engine.connect() as connection:
            config = migration_config()
            config.attributes["connection"] = connection
            command.downgrade(config, "0001_baseline")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(list((self.path.parent / ".backups").glob("*.db"))), 2)
        upgrade_database(self.engine)
        with self.engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql("SELECT content_hash FROM articles").scalar(),
                             compute_content_hash("AI 实习\n招募"))

    def test_current_does_not_create_backup_or_stamp_unversioned_db(self):
        self.legacy()
        with self.engine.connect() as connection:
            config = migration_config()
            config.attributes["connection"] = connection
            command.current(config)
        self.assertNotIn("alembic_version", sa.inspect(self.engine).get_table_names())
        self.assertFalse((self.path.parent / ".backups").exists())

    def test_simultaneous_startup_migrations_are_serialized(self):
        self.legacy()
        barrier = threading.Barrier(2, timeout=10)

        def migrate(_):
            barrier.wait()
            upgrade_database(self.engine)

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(migrate, range(2)))
        with self.engine.connect() as connection:
            self.assertEqual(MigrationContext.configure(connection).get_current_revision(), "0002_article_identity")
            self.assertEqual(connection.exec_driver_sql("SELECT id FROM articles").fetchall(), [(7,)])
        self.assertEqual(len(list((self.path.parent / ".backups").glob("*.db"))), 1)

    def test_unknown_legacy_schema_fails_without_creating_new_tables(self):
        with self.engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE articles (id INTEGER PRIMARY KEY, content TEXT)")
            connection.exec_driver_sql("INSERT INTO articles VALUES (7, 'keep me')")
        with self.assertRaisesRegex(RuntimeError, "不支持的旧表结构"):
            upgrade_database(self.engine)
        self.assertEqual(sa.inspect(self.engine).get_table_names(), ["articles"])
        with self.engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql("SELECT * FROM articles").one(), (7, "keep me"))

    def test_separate_startup_processes_upgrade_only_once(self):
        self.legacy()
        env = dict(os.environ, DATABASE_URL=f"sqlite:///{self.path}")
        processes = []
        try:
            for _ in range(2):
                processes.append(subprocess.Popen(
                    [sys.executable, "-m", "app.core.migrations", "upgrade"],
                    cwd=PROJECT_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                ))
            for process in processes:
                stdout, stderr = process.communicate(timeout=20)
                self.assertEqual(process.returncode, 0, stdout + stderr)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
        self.assertEqual(len(list((self.path.parent / ".backups").glob("*.db"))), 1)
        with self.engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql("SELECT id FROM articles").fetchall(), [(7,)])
