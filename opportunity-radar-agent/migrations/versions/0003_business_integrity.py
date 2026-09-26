"""Separate plan tasks from opportunity todos and retire local verification claims."""
import json

from alembic import op
import sqlalchemy as sa

revision = "0003_business_integrity"
down_revision = "0002_article_identity"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("todos") as batch:
        batch.add_column(sa.Column("task_key", sa.String(120), nullable=False, server_default="opportunity"))
        batch.drop_constraint("uq_todo_user_opportunity", type_="unique")
        batch.create_unique_constraint("uq_todo_identity", ["user_id", "opportunity_id", "task_key"])
    connection = op.get_bind()
    # The old schema could silently map multiple plan items to one todo. Retain
    # every original todo and make these items eligible for explicit re-sync.
    connection.execute(sa.text("UPDATE opportunity_progress_items SET synced_to_todo=0, todo_id=NULL "
                               "WHERE synced_to_todo=1 OR todo_id IS NOT NULL"))
    for row in connection.execute(sa.text(
        "SELECT id, verification_summary, evidence_sources FROM opportunities WHERE verification_status='verified'"
    )).mappings().all():
        try:
            sources = json.loads(row["evidence_sources"] or "[]")
        except (ValueError, TypeError):
            sources = []
        local = str(row["verification_summary"] or "").startswith("本地规则") or (
            isinstance(sources, list) and any(isinstance(source, dict) and
            source.get("url") == "https://example.edu.cn/official-notice" for source in sources))
        if local:
            params = {"id": row["id"]}
            connection.execute(sa.text(
                "UPDATE recommendations SET total_score=MAX(0, total_score-5), "
                "reason=reason || '（历史规则核验加权已撤销，建议刷新推荐。）' "
                "WHERE opportunity_id=:id AND EXISTS (SELECT 1 FROM opportunities "
                "WHERE id=:id AND credibility_score>=80 AND risk_level='low')"), params)
            connection.execute(sa.text(
                "UPDATE opportunities SET verification_status='rule_checked', credibility_score=NULL, "
                "verified_at=NULL, evidence_sources='[]', "
                "verification_summary='历史本地规则检查，尚未联网核验真实性。' WHERE id=:id"), params)
            connection.execute(sa.text("UPDATE opportunity_states SET state='recommended' "
                                       "WHERE opportunity_id=:id AND state='verified'"), params)
            connection.execute(sa.text("UPDATE recommendations SET opportunity_state='recommended' "
                                       "WHERE opportunity_id=:id AND opportunity_state='verified'"), params)



def downgrade():
    # Restoring the old uniqueness would require merging/deleting user tasks.
    raise RuntimeError("此迁移不自动合并待办或恢复旧核验结论；请停止服务并从升级前备份恢复。")
