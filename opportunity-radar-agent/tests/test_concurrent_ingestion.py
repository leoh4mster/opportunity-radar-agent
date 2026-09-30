"""Real file DB + independent sessions/HTTP requests, not a shared memory mock."""
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.database import get_db
from app.core.migrations import upgrade_database
from app.main import app
from app.models.entities import Article, Opportunity
from app.services.article_identity import compute_content_hash
from app.services.article_store import insert_article_once
from app.services.import_service import ImportService


class ConcurrentIngestionTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = create_engine(f"sqlite:///{Path(self.temp.name) / 'parallel.db'}",
                                    connect_args={"timeout": 10, "check_same_thread": False})
        self.addCleanup(self.engine.dispose)

        @event.listens_for(self.engine, "connect")
        def configure(connection, record):
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")

        upgrade_database(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False)
        previous = app.dependency_overrides.copy()
        self.addCleanup(lambda: setattr(app, "dependency_overrides", previous))

        def isolated_db():
            with self.sessions() as db:
                yield db

        app.dependency_overrides[get_db] = isolated_db
        for target, kwargs in [
            ("app.services.llm_gateway.LLMGateway.is_configured", {"return_value": False}),
            ("app.services.llm_gateway.LLMGateway.chat", {"side_effect": AssertionError("network forbidden")}),
        ]:
            guard = patch(target, **kwargs)
            guard.start()
            self.addCleanup(guard.stop)

    def parallel_requests(self, collectors_only=False):
        barrier = threading.Barrier(8, timeout=10)
        content = "AI 实习招募，欢迎报名。\n地点：上海\n截止：2030-12-31"

        def request(index):
            client = TestClient(app)  # No production lifespan.
            try:
                barrier.wait()
                if collectors_only or index % 2:
                    response = client.post("/articles/ingest-clean", json={
                        "content": content, "content_hash": f"untrusted-{index}",
                    })
                else:
                    response = client.post("/articles/upload", files={"file": ("article.txt", content.encode())})
                self.assertEqual(response.status_code, 202 if collectors_only or index % 2 else 200, response.text)
                return response.json()
            finally:
                client.close()

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(request, range(8)))
        created = sum(result.get("imported", int(result.get("created", False))) for result in results)
        self.assertEqual(created, 1)
        self.assertEqual(sum(result.get("skipped_duplicates", int(result.get("duplicate", False)))
                             for result in results), 7)
        with self.sessions() as db:
            article = db.query(Article).one()
            self.assertEqual(article.content_hash, compute_content_hash(content))
            ids = [result["article_id"] for result in results if "article_id" in result]
            ids += [value for result in results for value in result.get("article_ids", [])]
            self.assertEqual(set(ids), {article.id})
            # Upload intentionally defers extraction to /pipeline/process.
            self.assertEqual(db.query(Opportunity).count(), int(article.processed))

    def test_eight_simultaneous_upload_and_collector_requests(self):
        self.parallel_requests()

    def test_eight_collectors_extract_only_once(self):
        self.parallel_requests(collectors_only=True)
        from app.services.job_service import JobService
        JobService(self.sessions).run_once()
        with self.sessions() as db:
            self.assertEqual(db.query(Opportunity).count(), 1)

    def test_later_storage_failure_rolls_back_released_savepoints(self):
        with self.sessions() as db:
            ImportService().import_bytes(db, "old.txt", b"previously committed")
            count = 0

            def fail_later(session, article):
                nonlocal count
                count += 1
                if count == 3:
                    raise RuntimeError("disk failure after duplicate and new insert")
                return insert_article_once(session, article)

            payload = json.dumps([{"content": content} for content in
                                  ["previously committed", "new article", "fails here"]]).encode()
            with patch("app.services.import_service.insert_article_once", side_effect=fail_later):
                with self.assertRaisesRegex(RuntimeError, "disk failure"):
                    ImportService().import_bytes(db, "batch.json", payload)
            db.commit()  # A later operation must not revive partial inserts.
            self.assertEqual(db.query(Article).one().content, "previously committed")
        with self.sessions() as independent:
            self.assertEqual(independent.query(Article).count(), 1)

    def test_unrelated_integrity_failure_is_not_reported_as_duplicate(self):
        with self.sessions() as db:
            with self.assertRaises(IntegrityError):
                insert_article_once(db, Article(title=None, content="nonempty"))
            db.rollback()
            self.assertEqual(db.query(Article).count(), 0)

    def test_orm_content_updates_refresh_hash_and_still_enforce_uniqueness(self):
        with self.sessions() as db:
            first, _ = insert_article_once(db, Article(title="a", content="first"))
            second, _ = insert_article_once(db, Article(title="b", content="second"))
            db.commit()
            first.content = "changed"
            db.commit()
            self.assertEqual(first.content_hash, compute_content_hash("changed"))
            second.content = "c h a n g e d"
            with self.assertRaises(IntegrityError):
                db.commit()
            db.rollback()
            self.assertEqual(second.content, "second")
