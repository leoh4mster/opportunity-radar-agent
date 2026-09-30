"""Direct clean-article ingestion service.

This service receives cleaned article text from the GUI collector, writes it
into the existing Article table, and creates an extraction job in the same
short transaction. A worker performs model calls after that transaction ends.
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.entities import Article
from app.schemas.dto import CleanArticleIngestRequest
from app.services.article_identity import compute_content_hash
from app.services.article_store import insert_article_once
from app.services.job_service import JobService, public_job, lock
from app.core.observability import current_request_id


logger = logging.getLogger(__name__)


def guess_title_from_content(content: str, fallback: str = "未命名文章") -> str:
    for line in (content or "").splitlines():
        line = line.strip()
        if line:
            return line[:255]
    return fallback


class ArticleIngestService:
    def ingest_clean_article(self, db: Session, payload: CleanArticleIngestRequest) -> dict:
        try:
            return self._ingest_clean_article(db, payload)
        except ValueError:
            db.rollback()
            raise
        except SQLAlchemyError:
            db.rollback()
            logger.exception("ingest_clean_article db failure")
            raise RuntimeError("文章入库失败")
        except Exception:
            db.rollback()
            logger.exception("ingest_clean_article failed")
            raise

    def _ingest_clean_article(self, db: Session, payload: CleanArticleIngestRequest) -> dict:
        content = (payload.content or "").strip()

        if not content:
            raise ValueError("content 不能为空")

        # Client metadata is not authoritative: derive identity from the text.
        content_hash = compute_content_hash(content)

        title = (payload.title or "").strip()
        if not title:
            title = guess_title_from_content(content)

        article = Article(
            title=title[:255],
            source=(payload.source or "公众号自动采集")[:120],
            author=(payload.author or "")[:120],
            published_at=payload.published_at or "",
            content=content,
            url=payload.url or "",
            processed=False,
        )

        lock(db)
        article, created = insert_article_once(db, article)
        job = None
        if not article.processed:
            job = JobService.submit(db, "extraction", article.id, current_request_id())
        db.commit()
        db.refresh(article)
        return {
            "created": created,
            "duplicate": not created,
            "article_id": article.id,
            "content_hash": content_hash,
            "message": "saved_and_queued" if job else "already_processed",
            "job": public_job(job) if job else None,
        }
