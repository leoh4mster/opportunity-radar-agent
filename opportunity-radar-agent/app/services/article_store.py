"""Shared insert-or-find primitive. The caller owns the outer transaction."""
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.entities import Article
from app.services.article_identity import compute_content_hash


def insert_article_once(db: Session, article: Article) -> tuple[Article, bool]:
    content_hash = compute_content_hash(article.content)
    article.content_hash = content_hash
    connection = db.connection()
    if connection.dialect.name == "sqlite":
        # Python sqlite3 legacy transaction mode does not BEGIN for SAVEPOINT.
        # Without a real outer BEGIN, RELEASE would commit a partial batch.
        driver = connection.connection.driver_connection
        if not driver.in_transaction:
            connection.exec_driver_sql("BEGIN")
    try:
        # Insert first: a SELECT-before-INSERT can race (or upgrade a stale
        # SQLite read snapshot). Only a unique constraint arbitrates writers.
        with db.begin_nested():
            db.add(article)
            db.flush()
        return article, True
    except IntegrityError as exc:
        # Do not disguise unrelated storage/constraint failures as duplicates.
        sqlite_conflict = "UNIQUE constraint failed: articles.content_hash" in str(exc.orig)
        diagnostic = getattr(exc.orig, "diag", None)
        named_conflict = getattr(diagnostic, "constraint_name", None) == "uq_articles_content_hash"
        if not (sqlite_conflict or named_conflict):
            raise
        existing = db.query(Article).filter(Article.content_hash == content_hash).one_or_none()
        if existing is None:
            raise
        return existing, False
