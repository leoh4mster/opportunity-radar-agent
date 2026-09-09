"""Persist v1 text identity and enforce uniqueness at the database boundary."""
import hashlib
import re

from alembic import op
import sqlalchemy as sa

revision = "0002_article_identity"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    # Freeze the algorithm here: future application normalization must not
    # change the meaning of a historical migration.
    seen = {}
    hashes = []
    conflicts = []
    for article_id, content in connection.execute(sa.text("SELECT id, content FROM articles ORDER BY id")):
        digest = hashlib.sha256(re.sub(r"\s+", "", content or "").encode("utf-8")).hexdigest()
        if digest in seen:
            if len(conflicts) < 10:
                conflicts.append((seen[digest], article_id))
        else:
            seen[digest] = article_id
        hashes.append({"article_id": article_id, "digest": digest})
    if conflicts:
        # No DELETE/merge: recommendations and user actions may reference both.
        raise RuntimeError(f"旧文章存在重复正文，冲突 ID 对（最多 10 对）：{conflicts}。"
                           "迁移已回滚，未删除任何记录。请先备份并人工决定保留/合并方案，勿 stamp head。")
    op.add_column("articles", sa.Column("content_hash", sa.String(64), nullable=True))
    if hashes:
        connection.execute(sa.text("UPDATE articles SET content_hash=:digest WHERE id=:article_id"), hashes)
    with op.batch_alter_table("articles") as batch:
        batch.alter_column("content_hash", existing_type=sa.String(64), nullable=False)
        batch.create_unique_constraint("uq_articles_content_hash", ["content_hash"])


def downgrade():
    with op.batch_alter_table("articles") as batch:
        batch.drop_constraint("uq_articles_content_hash", type_="unique")
        batch.drop_column("content_hash")
