from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models.entities import Article
from app.schemas.dto import ArticleCreate
from app.services.article_identity import compute_content_hash


MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_IMPORT_ARTICLES = 500
SUPPORTED_SUFFIXES = {".json", ".md", ".markdown", ".txt"}


class ImportService:
    """Validate a whole batch before writing; commit or roll back atomically.

    Sequential imports are idempotent. Concurrent imports still require a
    database unique constraint (see docs/QUALITY.md).
    """

    def import_file(self, db: Session, path: str) -> tuple[list[Article], int]:
        file_path = Path(path)
        if not file_path.is_file():
            raise FileNotFoundError("导入文件不存在或不是普通文件")
        with file_path.open("rb") as stream:
            data = stream.read(MAX_IMPORT_BYTES + 1)
        return self.import_bytes(db, file_path.name, data)

    def import_bytes(self, db: Session, filename: str, data: bytes) -> tuple[list[Article], int]:
        if len(data) > MAX_IMPORT_BYTES:
            raise ValueError("文件不能超过 2 MiB")
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise ValueError("仅支持 JSON / Markdown / TXT 文件")
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("请将文件保存为 UTF-8 编码") from exc
        title = Path(filename).stem or "未命名文章"
        if suffix == ".json":
            try:
                payloads = json.loads(text)
            except (ValueError, RecursionError) as exc:
                raise ValueError("JSON 格式不正确，请检查括号和逗号") from exc
            if isinstance(payloads, dict):
                payloads = payloads.get("articles", [payloads])
            if not isinstance(payloads, list) or not payloads:
                raise ValueError("JSON 应包含非空的文章数组或文章对象")
        else:
            lines = text.lstrip().splitlines()
            if suffix in {".md", ".markdown"} and lines and lines[0].startswith("#"):
                title = lines[0].lstrip("#").strip() or title
            payloads = [{"title": title, "content": text}]
        if len(payloads) > MAX_IMPORT_ARTICLES:
            raise ValueError("单次最多导入 500 篇文章")

        validated = []
        for index, item in enumerate(payloads, 1):
            if not isinstance(item, dict):
                raise ValueError(f"第 {index} 篇文章必须是对象")
            try:
                article = ArticleCreate(**self._normalize_article(item, title))
            except ValidationError as exc:
                raise ValueError(f"第 {index} 篇文章字段类型错误") from exc
            if not article.content.strip():
                raise ValueError(f"第 {index} 篇文章正文不能为空")
            validated.append(article)

        try:
            existing_hashes = {
                compute_content_hash(content or "")
                for (content,) in db.query(Article.content).all()
            }
            articles = []
            skipped = 0
            for article_in in validated:
                content_hash = compute_content_hash(article_in.content)
                if content_hash in existing_hashes:
                    skipped += 1
                    continue
                article = Article(**article_in.model_dump())
                db.add(article)
                articles.append(article)
                existing_hashes.add(content_hash)
            db.commit()
        except Exception:
            db.rollback()
            raise
        for article in articles:
            db.refresh(article)
        return articles, skipped

    def _normalize_article(self, item: dict, fallback_title: str) -> dict:
        return {
            "title": item.get("title") or fallback_title,
            "source": item.get("source") or item.get("account") or "本地导入",
            "author": item.get("author") or "",
            "published_at": item.get("published_at") or item.get("date") or "",
            "content": item.get("content") or item.get("text") or "",
            "url": item.get("url") or item.get("link") or "",
        }
