"""API regressions use an isolated in-memory DB; never call external models."""
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.entities import Article, Opportunity
from app.services.article_identity import compute_content_hash
from app.services.import_service import ImportService, MAX_IMPORT_BYTES


class IngestionAPITest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, autoflush=False)()
        self.previous_overrides = app.dependency_overrides.copy()
        app.dependency_overrides[get_db] = lambda: self.db
        # Do not enter production lifespan: it creates the real on-disk database.
        self.client = TestClient(app)
        self.guard = patch("app.services.llm_gateway.LLMGateway.chat", side_effect=AssertionError("network forbidden"))
        self.guard.start()
        self.addCleanup(self.guard.stop)
        self.local_mode = patch("app.services.llm_gateway.LLMGateway.is_configured", return_value=False)
        self.local_mode.start()
        self.addCleanup(self.local_mode.stop)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides = self.previous_overrides
        self.db.close()
        self.engine.dispose()

    def upload(self, data, name="articles.json"):
        return self.client.post("/articles/upload", files={"file": (name, data)})

    def test_upload_then_collector_share_server_computed_identity(self):
        content = "AI 实习招募，欢迎报名。\n地点：上海\n截止：2030-12-31"
        response = self.upload(json.dumps({"title": "实习", "content": content}).encode())
        self.assertEqual(response.status_code, 200)
        first_id = response.json()["article_ids"][0]
        duplicate = self.client.post("/articles/ingest-clean", json={
            "content": content, "content_hash": "incorrect-client-hash",
        })
        self.assertEqual(duplicate.status_code, 200)
        self.assertTrue(duplicate.json()["duplicate"])
        self.assertEqual(duplicate.json()["article_id"], first_id)
        self.assertEqual(duplicate.json()["content_hash"], compute_content_hash(content))
        self.assertEqual(self.db.query(Article).count(), 1)

    def test_collector_then_upload_is_also_idempotent(self):
        content = "AI 实习招募，欢迎报名。\n地点：上海"
        response = self.client.post("/articles/ingest-clean", json={"content": content})
        self.assertTrue(response.json()["created"])
        duplicate = self.upload(content.encode(), "article.txt")
        self.assertEqual(duplicate.json()["skipped_duplicates"], 1)
        self.assertEqual(self.db.query(Opportunity).count(), 1)

    def test_bad_second_row_does_not_leave_pending_first_row(self):
        payload = [{"title": "valid", "content": "some text"}, {"content": "  "}]
        response = self.upload(json.dumps(payload).encode())
        self.assertEqual(response.status_code, 400)
        self.assertIn("第 2 篇", response.json()["detail"])
        self.db.commit()  # Even a later commit must not accidentally persist row 1.
        self.assertEqual(self.db.query(Article).count(), 0)
        self.assertEqual(self.upload(b"valid text", "ok.txt").status_code, 200)

    def test_input_boundaries(self):
        cases = [(b"[null]", "a.json", 400), (b"{", "a.json", 400),
                 (b"[]", "a.json", 400), (b"hello", "a.exe", 400),
                 (b"\xff", "a.txt", 400), (b" \n", "a.txt", 400),
                 (b"a" * (MAX_IMPORT_BYTES + 1), "a.txt", 413),
                 (json.dumps([{"content": "x"}] * 501).encode(), "a.json", 400)]
        for data, filename, status in cases:
            with self.subTest(filename=filename, size=len(data)):
                self.assertEqual(self.upload(data, filename).status_code, status)
        self.assertEqual(self.db.query(Article).count(), 0)

    def test_markdown_bom_and_title(self):
        response = self.upload("\ufeff# 讲座通知\n地点：线上".encode(), "article.md")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.db.query(Article).one().title, "讲座通知")

    def test_flush_failure_rolls_back_batch_and_session_recovers(self):
        with patch.object(self.db, "flush", side_effect=RuntimeError("simulated storage failure")):
            with self.assertRaises(RuntimeError):
                ImportService().import_bytes(self.db, "a.txt", b"new article")
        self.db.commit()
        self.assertEqual(self.db.query(Article).count(), 0)

    def test_extraction_failure_rolls_back_collector_article(self):
        with patch("app.services.extraction_service.ExtractionService.process_article", side_effect=RuntimeError("failed")):
            response = self.client.post("/articles/ingest-clean", json={"content": "article"})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.db.query(Article).count(), 0)
