"""SQLite-backed queue. Every write is fenced by an unexpired claim token."""
from contextlib import contextmanager
from datetime import datetime, timedelta
import json
import logging
import threading
from uuid import uuid4

from sqlalchemy import text, update

from app.models.entities import DurableJob
from app.core.observability import run_with_request_context
from app.services.llm_gateway import LLMTransientError

logger = logging.getLogger(__name__)
ACTIVE = ("queued", "running")


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def lock(db):
    # Routes call this before reads. Workers use fresh sessions for each write.
    if db.bind.dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))


class LostLease(RuntimeError):
    pass


class JobFailure(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def public_job(job):
    return {key: getattr(job, key) for key in (
        "id", "kind", "object_id", "user_id", "status", "attempts", "retry_of",
        "request_id", "stage", "completed", "total", "mode", "error_code",
        "error_message", "created_at", "updated_at")} | {
            "result": json.loads(job.result), "status_url": f"/jobs/{job.id}"}


class JobService:
    def __init__(self, sessions):
        self.sessions = sessions

    @staticmethod
    def enqueue(db, kind, object_id, user_id=None, request_id="", retry_of=None):
        key = f"{kind}:{object_id}"
        existing = db.query(DurableJob).filter_by(active_key=key).first()
        if existing:
            return existing
        job = DurableJob(kind=kind, object_id=object_id, user_id=user_id,
                         active_key=key, request_id=request_id, retry_of=retry_of)
        db.add(job)
        db.flush()
        return job

    @staticmethod
    def submit(db, kind, object_id, request_id="", retry_of=None, user_id=None):
        from app.services.job_handlers import prepare
        # Caller owns the transaction, including creation of business task rows.
        existing = db.query(DurableJob).filter_by(active_key=f"{kind}:{object_id}").first()
        if existing:
            return existing
        user_id = prepare(db, kind, object_id, user_id, request_id)
        return JobService.enqueue(db, kind, object_id, user_id, request_id, retry_of)

    def claim(self):
        from app.services.job_handlers import mark_failed
        now = datetime.utcnow()
        with self.sessions() as db:
            lock(db)
            expired = db.query(DurableJob).filter(
                DurableJob.status == "running", DurableJob.lease_until <= now).all()
            for job in expired:
                job.token = None
                job.lease_until = None
                if job.attempts >= 2:
                    job.status, job.active_key = "failed", None
                    job.error_code, job.error_message = "interrupted", "执行中断，自动恢复次数已用完，请手动重试"
                    mark_failed(db, job)
                else:
                    job.status, job.stage, job.available_at = "queued", "recovering", now
                job.updated_at = now
            db.flush()
            job = db.query(DurableJob).filter(
                DurableJob.status == "queued", DurableJob.available_at <= now
            ).order_by(DurableJob.available_at, DurableJob.id).first()
            if not job:
                db.commit()
                return None
            job.status, job.token = "running", uuid4().hex
            job.attempts += 1
            job.lease_until = now + timedelta(seconds=60)
            job.updated_at = now
            claim = (job.id, job.token, job.request_id)
            db.commit()
            return claim

    @contextmanager
    def fenced(self, job_id, token):
        with self.sessions() as db:
            lock(db)
            job = db.get(DurableJob, job_id)
            if not job or job.status != "running" or job.token != token or job.lease_until <= datetime.utcnow():
                raise LostLease()
            try:
                yield db, job
                job.updated_at = datetime.utcnow()
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def heartbeat(self, job_id, token):
        now = datetime.utcnow()
        with self.sessions() as db:
            result = db.execute(update(DurableJob).where(
                DurableJob.id == job_id, DurableJob.token == token,
                DurableJob.status == "running", DurableJob.lease_until > now
            ).values(lease_until=now + timedelta(seconds=60)))
            db.commit()
            return result.rowcount == 1

    def checkpoint(self, job_id, token, key, value, total=0):
        with self.fenced(job_id, token) as (db, job):
            checkpoints = json.loads(job.checkpoints)
            checkpoints[key] = value
            job.checkpoints = encode(checkpoints)
            job.stage, job.completed = key, len(checkpoints)
            if total:
                job.total = total

    def run_claim(self, claim):
        from app.services.job_handlers import execute, mark_failed
        from app.services.llm_gateway import job_execution
        job_id, token, request_id = claim
        finished = threading.Event()

        def renew():
            while not finished.wait(10):
                try:
                    if not self.heartbeat(job_id, token):
                        return
                except Exception:
                    logger.warning("job heartbeat failed job_id=%s", job_id)

        heartbeat = threading.Thread(target=renew, name="job-lease", daemon=True)
        heartbeat.start()
        try:
            with job_execution():
                run_with_request_context(request_id, execute, self, job_id, token)
        except LostLease:
            logger.info("job lease lost job_id=%s", job_id)
        except Exception as exc:
            try:
                with self.fenced(job_id, token) as (db, job):
                    job.error_code = getattr(exc, "code", getattr(exc, "error_code", "execution_failed"))
                    job.error_message = {
                        "input_changed": "输入已修改或删除，请重新提交任务",
                        "llm_auth_error": "模型鉴权失败，请检查配置后手动重试",
                        "llm_response_format_error": "模型返回格式无效，请手动重试",
                        "search_unavailable": "未配置联网搜索服务",
                        "model_unavailable": "此任务需要配置模型服务",
                        "search_empty": "搜索未返回可用来源，未完成核验",
                    }.get(job.error_code, "处理失败，请检查服务配置或稍后重试")
                    job.token, job.lease_until = None, None
                    if isinstance(exc, LLMTransientError) and job.attempts < 2:
                        job.status, job.stage = "queued", "retrying"
                        job.available_at = datetime.utcnow() + timedelta(seconds=5)
                    else:
                        job.status, job.active_key = "failed", None
                        mark_failed(db, job)
            except LostLease:
                pass
            logger.warning("job execution failed job_id=%s error_type=%s", job_id, type(exc).__name__)
        finally:
            finished.set()
            heartbeat.join(timeout=2)

    def run_once(self):
        claim = self.claim()
        if claim:
            self.run_claim(claim)
        return claim is not None


class JobWorker:
    def __init__(self, sessions):
        self.service = JobService(sessions)
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, name="durable-worker", daemon=True)

    def start(self):
        self.thread.start()

    def run(self):
        while not self.stop_event.is_set():
            try:
                if self.service.run_once():
                    continue
            except Exception:
                logger.exception("job worker iteration failed")
            self.stop_event.wait(1)

    def stop(self):
        self.stop_event.set()
        self.thread.join(timeout=5)
