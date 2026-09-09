"""Adopt the legacy schema without dropping tables or changing row IDs."""
from alembic import op
import sqlalchemy as sa

from migrations.schema_v1 import metadata

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

# The only historically optional columns added by the former startup patcher.
LEGACY_COLUMNS = {
    "user_profiles": {"detailed_needs": ""},
    "opportunities": {
        "official_url": "", "registration_url": "", "verification_status": "",
        "credibility_score": None, "risk_level": "", "risk_flags": "[]",
        "verification_summary": "", "evidence_sources": "[]",
        "enriched_at": None, "verified_at": None,
    },
    "recommendations": {
        "content_overview": "", "relevance_explanation": "", "risk_notes": "[]",
        "anti_recommendation_reason": "", "opportunity_state": "recommended",
        "deadline": "", "deadline_urgency": "unknown", "deadline_note": "",
    },
    "tool_calls": {"query": "", "provider": "", "result_summary": "", "error_message": ""},
    "tool_call_logs": {"query": "", "provider": "", "result_summary": "", "error_message": ""},
}


def upgrade():
    connection = op.get_bind()
    # Frozen snapshot, not today's ORM metadata. checkfirst adopts existing
    # tables; new databases get exactly the same starting revision.
    metadata.create_all(connection)
    for name, defaults in LEGACY_COLUMNS.items():
        existing = {c["name"] for c in sa.inspect(connection).get_columns(name)}
        for column_name, default in defaults.items():
            if column_name not in existing:
                frozen = metadata.tables[name].c[column_name]
                op.add_column(name, sa.Column(column_name, frozen.type,
                                              nullable=True, server_default=default))
    for table in metadata.sorted_tables:
        existing = {c["name"] for c in sa.inspect(connection).get_columns(table.name)}
        missing = set(table.c.keys()) - existing
        if missing:
            raise RuntimeError(f"不支持的旧表结构 {table.name}，缺失字段：{sorted(missing)}；升级已回滚。")


def downgrade():
    raise RuntimeError("基线迁移不自动删除业务表；请停止服务并从升级前备份恢复。")
