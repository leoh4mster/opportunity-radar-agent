"""Real SQLite sessions, lease fencing, checkpoint recovery and async HTTP contracts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.database import get_db
from app.core.migrations import upgrade_database
from app.main import app
from app.models import entities as m
from app.services.job_service import JobService, LostLease, lock, public_job
from app.services.llm_gateway import LLMAuthError, LLMTransientError, LLMResponseFormatError


class DurableJobsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "jobs.db"
        self.engine = create_engine(f"sqlite:///{self.path}", connect_args={"check_same_thread": False, "timeout": 5})
        self.addCleanup(self.engine.dispose)
        @event.listens_for(self.engine, "connect")
        def configure(conn, record):
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
        upgrade_database(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False)
        self.queue = JobService(self.sessions)
        previous = app.dependency_overrides.copy()
        self.addCleanup(lambda: setattr(app, "dependency_overrides", previous))
        def isolated():
            with self.sessions() as db:
                yield db
        app.dependency_overrides[get_db] = isolated
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        guard = patch("app.services.llm_gateway.LLMGateway._post_json", side_effect=AssertionError("network forbidden"))
        guard.start()
        self.addCleanup(guard.stop)
        mode = patch("app.services.llm_gateway.LLMGateway.is_configured", return_value=False)
        mode.start()
        self.addCleanup(mode.stop)

    def ingest(self, content="AI 实习招募，欢迎报名。地点：上海。截止：2030-12-31"):
        response = self.client.post("/articles/ingest-clean", json={"content": content})
        self.assertEqual(response.status_code, 202, response.text)
        return response.json()

    def job(self, ident):
        return self.client.get(f"/jobs/{ident}").json()

    def expire(self, ident):
        with self.sessions() as db:
            job = db.get(m.DurableJob, ident)
            job.lease_until = datetime.utcnow() - timedelta(seconds=1)
            job.available_at = datetime.utcnow() - timedelta(seconds=1)
            db.commit()

    def test_competing_claims_and_duplicate_submit(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.ingest(), range(4)))
        ids = {item["job"]["id"] for item in results}
        self.assertEqual(len(ids), 1)
        with ThreadPoolExecutor(max_workers=2) as pool:
            claims = list(pool.map(lambda _: self.queue.claim(), range(2)))
        self.assertEqual(sum(claim is not None for claim in claims), 1)
        self.queue.run_claim(next(c for c in claims if c))
        with self.sessions() as db:
            self.assertEqual(db.query(m.Article).count(), 1)
            self.assertEqual(db.query(m.Opportunity).count(), 1)
        self.assertEqual(self.job(ids.pop())["status"], "succeeded")
        self.assertFalse(self.queue.run_once())

    def test_expired_claim_is_fenced_and_checkpoints_reused(self):
        jid = self.ingest()["job"]["id"]
        first = self.queue.claim()
        self.queue.checkpoint(jid, first[1], "extraction", [], 1)
        self.expire(jid)
        self.assertFalse(self.queue.heartbeat(jid, first[1]))
        second = self.queue.claim()
        with self.assertRaises(LostLease):
            self.queue.checkpoint(jid, first[1], "late", {})
        with patch("app.services.llm_service.LLMService.extract_opportunities", side_effect=AssertionError("must reuse checkpoint")):
            self.queue.run_claim(second)
        self.assertEqual(self.job(jid)["status"], "succeeded")
        self.assertEqual(self.job(jid)["attempts"], 2)

    def test_two_interruptions_fail_and_manual_retry_is_idempotent(self):
        jid = self.ingest()["job"]["id"]
        self.queue.claim()
        self.expire(jid)
        self.queue.claim()
        self.expire(jid)
        self.assertIsNone(self.queue.claim())
        self.assertEqual(self.job(jid)["status"], "failed")
        with ThreadPoolExecutor(max_workers=2) as pool:
            retries = list(pool.map(lambda _: self.client.post(f"/jobs/{jid}/retry").json(), range(2)))
        self.assertEqual(retries[0]["job"]["id"], retries[1]["job"]["id"])
        self.queue.run_once()
        self.assertEqual(self.job(jid)["status"], "failed")
        self.assertEqual(self.job(retries[0]["job"]["id"])["status"], "succeeded")

    def test_slow_model_does_not_lock_database_and_changed_input_rejected(self):
        data = self.ingest()
        entered, release = threading.Event(), threading.Event()
        def slow(*args):
            entered.set()
            self.assertTrue(release.wait(5))
            return []
        with patch("app.services.llm_service.LLMService.extract_opportunities", side_effect=slow):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.queue.run_once)
                self.assertTrue(entered.wait(5))
                try:
                    with self.sessions() as db:
                        article = db.get(m.Article, data["article_id"])
                        article.title = "edited during remote request"
                        db.add(m.UserProfile(name="unrelated write"))
                        db.commit()
                finally:
                    release.set()
                future.result()
        job = self.job(data["job"]["id"])
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["error_code"], "input_changed")
        with self.sessions() as db:
            self.assertFalse(db.get(m.Article, data["article_id"]).processed)

    def test_auth_and_format_fail_without_retry_transient_retries_once(self):
        for error in (LLMAuthError("secret"), LLMResponseFormatError("secret"), LLMTransientError("secret")):
            data = self.ingest(content="unique " + type(error).__name__)
            with patch("app.services.llm_service.LLMService.extract_opportunities", side_effect=error) as model:
                self.queue.run_once()
                job = self.job(data["job"]["id"])
                if isinstance(error, LLMTransientError):
                    self.assertEqual(job["status"], "queued")
                    self.assertFalse(self.queue.run_once())
                    self.expire(job["id"])
                    self.queue.run_once()
                    self.assertEqual(model.call_count, 2)
                else:
                    self.assertEqual(model.call_count, 1)
                final = self.job(job["id"])
                self.assertEqual(final["status"], "failed")
                self.assertNotIn("secret", json.dumps(final))
                self.assertNotIn("snapshot", final)

    def test_deleted_article_revokes_claim_and_scrubs_snapshot(self):
        data = self.ingest()
        claim = self.queue.claim()
        with self.queue.fenced(*claim[:2]) as (db, job):
            job.snapshot = '{"private":"text"}'
        self.assertEqual(self.client.delete(f"/articles/{data['article_id']}").status_code, 200)
        with self.assertRaises(LostLease):
            self.queue.checkpoint(*claim[:2], "result", [])
        with self.sessions() as db:
            job = db.get(m.DurableJob, claim[0])
            self.assertEqual(job.snapshot, "{}")
            self.assertEqual(db.query(m.Opportunity).count(), 0)

    def test_recommendation_retains_previous_on_failure(self):
        self.ingest()
        self.queue.run_once()
        uid = self.client.post("/profiles", json={"name": "虚构用户"}).json()["id"]
        response = self.client.post(f"/recommendations/generate/{uid}")
        self.assertEqual(response.status_code, 202)
        self.queue.run_once()
        self.assertEqual(self.job(response.json()["job"]["id"])["status"], "succeeded")
        previous = self.client.get(f"/recommendations/{uid}").json()
        self.assertTrue(previous)
        jid = self.client.post(f"/recommendations/{uid}/generate").json()["job"]["id"]
        with patch("app.services.matching_service.MatchingService._score", side_effect=LLMAuthError("no")):
            self.queue.run_once()
        self.assertEqual(self.job(jid)["status"], "failed")
        self.assertEqual(previous, self.client.get(f"/recommendations/{uid}").json())

    def test_independent_process_exit_then_resume(self):
        jid = self.ingest()["job"]["id"]
        script = '''from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.services.job_service import JobService
import os
q=JobService(sessionmaker(bind=create_engine(os.environ["DATABASE_URL"])))
c=q.claim()
q.checkpoint(c[0],c[1],"extraction",[],1)
os._exit(17)
'''
        env = dict(os.environ, DATABASE_URL=f"sqlite:///{self.path}", DEEPSEEK_API_KEY="", BOCHA_API_KEY="", PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True)
        self.assertEqual(result.returncode, 17, result.stderr.decode())
        self.expire(jid)
        with patch("app.services.llm_service.LLMService.extract_opportunities", side_effect=AssertionError("duplicate request")):
            self.queue.run_once()
        self.assertEqual(self.job(jid)["status"], "succeeded")

    def setup_opportunity(self):
        self.ingest()
        self.queue.run_once()
        uid = self.client.post("/profiles", json={"name": "虚构用户"}).json()["id"]
        with self.sessions() as db:
            oid = db.query(m.Opportunity).one().id
        return uid, oid

    def test_analysis_checkpoints_confirmation_and_web_search_resume(self):
        from app.services.job_handlers import StrictProgress
        from app.services.external_search_provider import ExternalSearchResponse, ExternalSearchResult
        uid, oid = self.setup_opportunity()
        route = f"/tools/opportunity-progress/{uid}/{oid}/analyze"
        first = self.client.post(route).json()
        self.assertEqual(self.client.post(route).json()["job"]["id"], first["job"]["id"])
        round_value = {"stage": "action_planning", "next_focus": "final_summary", "should_stop": True}
        final_value = {"should_create_todos": True, "suggested_todos": [{"title": "准备材料"}], "overall_judgment": "可以推进"}
        with patch("app.services.llm_gateway.LLMGateway.is_configured", return_value=True), \
             patch.object(StrictProgress, "_run_round", return_value=round_value) as rounds, \
             patch.object(StrictProgress, "_should_stop_rounds", return_value=True), \
             patch.object(StrictProgress, "_run_final", side_effect=LLMTransientError("timeout")):
            self.queue.run_once()
            jid = first["job"]["id"]
            self.assertEqual(self.job(jid)["status"], "queued")
            self.expire(jid)
            with patch.object(StrictProgress, "_run_final", return_value=final_value):
                self.queue.run_once()
            self.assertEqual(rounds.call_count, 1)
        self.assertEqual(self.job(jid)["status"], "succeeded")
        task_id = first["task"]["id"]
        self.assertEqual(self.client.get(f"/tools/opportunity-progress/tasks/{task_id}").json()["task"]["status"], "waiting_confirmation")
        with self.sessions() as db:
            self.assertEqual(db.query(m.Todo).count(), 0)
        check = self.client.post(f"/tools/opportunity-progress/tasks/{task_id}/web-check").json()
        self.assertEqual(self.client.post(f"/tools/opportunity-progress/tasks/{task_id}/web-check").json()["job"]["id"], check["job"]["id"])
        response = ExternalSearchResponse(status="success", provider="fake", query="synthetic",
            results=[ExternalSearchResult(title="虚构来源", url="https://example.invalid", snippet="test")])
        with patch("app.services.llm_gateway.LLMGateway.is_configured", return_value=True), \
             patch("app.services.job_handlers.BochaSearchProvider.search", return_value=response) as search, \
             patch.object(StrictProgress, "_run_web_check_analysis", side_effect=LLMTransientError("timeout")):
            self.queue.run_once()
            self.expire(check["job"]["id"])
            with patch.object(StrictProgress, "_run_web_check_analysis", return_value={"summary": "测试"}):
                self.queue.run_once()
            self.assertEqual(search.call_count, 1)
        self.assertEqual(self.job(check["job"]["id"])["status"], "succeeded")

    def test_gateway_and_json_repair_do_not_multiply_job_retries(self):
        from app.services.llm_gateway import LLMGateway, job_execution
        from app.services.llm_service import LLMService
        with job_execution(), patch.object(LLMGateway, "_post_json", side_effect=LLMTransientError("temporary")) as post:
            gateway = LLMGateway()
            gateway.settings = gateway.settings.model_copy(update={"deepseek_api_key": "fake"})
            with self.assertRaises(LLMTransientError):
                gateway.chat([], max_retries=5)
            self.assertEqual(post.call_count, 1)
        with job_execution(), patch.object(LLMGateway, "is_configured", return_value=True), \
             patch.object(LLMGateway, "chat", return_value="not JSON") as chat:
            with self.assertRaises(LLMResponseFormatError):
                LLMService(allow_local_fallback=False).analyze_recommendation({}, {}, {})
            self.assertEqual(chat.call_count, 1)

    def test_migration_marks_old_work_interrupted_and_can_downgrade_empty_queue(self):
        from alembic import command
        from app.core.migrations import migration_config
        from alembic.migration import MigrationContext
        uid, oid = self.setup_opportunity()
        # Use a separate revision-3 database so no active new jobs are discarded.
        path = Path(self.temp.name) / "legacy.db"
        engine = create_engine(f"sqlite:///{path}")
        self.addCleanup(engine.dispose)
        upgrade_database(engine, "0003_business_integrity")
        legacy_sessions = sessionmaker(bind=engine)
        with legacy_sessions() as db:
            user = m.UserProfile(name="旧画像")
            article = m.Article(title="旧文章", content="旧正文")
            db.add_all([user, article]); db.flush()
            opportunity = m.Opportunity(article_id=article.id, name="旧机会", category="讲座")
            db.add(opportunity); db.flush()
            task = m.OpportunityProgressTask(user_id=user.id, opportunity_id=opportunity.id)
            db.add(task); db.flush()
            check = m.OpportunityProgressWebCheck(user_id=user.id, opportunity_id=opportunity.id,
                                                  task_id=task.id, query="旧查询")
            db.add(check); db.commit()
        upgrade_database(engine)
        with legacy_sessions() as db:
            self.assertEqual(db.query(m.OpportunityProgressTask).one().status, "failed")
            self.assertEqual(db.query(m.OpportunityProgressWebCheck).one().status, "failed")
            self.assertEqual(db.query(m.DurableJob).count(), 0)
            self.assertEqual(db.query(m.Article).one().content, "旧正文")
        with engine.connect() as conn:
            config = migration_config()
            config.attributes["connection"] = conn
            command.downgrade(config, "0003_business_integrity")
            self.assertEqual(MigrationContext.configure(conn).get_current_revision(), "0003_business_integrity")
        upgrade_database(engine)

    def test_exit_after_final_commit_does_not_execute_again(self):
        jid = self.ingest()["job"]["id"]
        script = '''from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.services.job_service import JobService
import os
q=JobService(sessionmaker(bind=create_engine(os.environ["DATABASE_URL"])))
assert q.run_once()
os._exit(17)
'''
        env = dict(os.environ, DATABASE_URL=f"sqlite:///{self.path}", DEEPSEEK_API_KEY="", BOCHA_API_KEY="", PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True)
        self.assertEqual(result.returncode, 17, result.stderr.decode())
        self.assertEqual(self.job(jid)["status"], "succeeded")
        self.assertFalse(self.queue.run_once())
        with self.sessions() as db:
            self.assertEqual(db.query(m.Opportunity).count(), 1)

    def test_final_write_failure_rolls_back_both_results_and_processed_flag(self):
        data = self.ingest()
        def fail_insert(mapper, connection, target):
            raise RuntimeError("injected storage failure")
        event.listen(m.Opportunity, "before_insert", fail_insert)
        try:
            self.queue.run_once()
        finally:
            event.remove(m.Opportunity, "before_insert", fail_insert)
        self.assertEqual(self.job(data["job"]["id"])["status"], "failed")
        with self.sessions() as db:
            self.assertEqual(db.query(m.Opportunity).count(), 0)
            self.assertFalse(db.get(m.Article, data["article_id"]).processed)

    def test_live_jobs_check_requires_opt_in_before_app_access(self):
        from evaluation.check_jobs_live import run_check
        with self.assertRaisesRegex(ValueError, "allow-network"):
            run_check(False)
