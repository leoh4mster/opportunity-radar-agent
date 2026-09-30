"""Durable, fenced execution without replaying historical private inputs."""
from alembic import op
import sqlalchemy as sa

revision = "0004_durable_jobs"
down_revision = "0003_business_integrity"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("durable_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("object_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("active_key", sa.String(160), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("retry_of", sa.Integer(), nullable=True),
        sa.Column("request_id", sa.String(80), nullable=False),
        sa.Column("token", sa.String(64), nullable=True),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("available_at", sa.DateTime(), nullable=False),
        sa.Column("input_version", sa.String(64), nullable=False),
        sa.Column("snapshot", sa.Text(), nullable=False),
        sa.Column("checkpoints", sa.Text(), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("stage", sa.String(80), nullable=False),
        sa.Column("completed", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("error_code", sa.String(80), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("active_key"))
    for name in ("kind", "object_id", "user_id", "status"):
        op.create_index("ix_durable_jobs_" + name, "durable_jobs", [name])
    for table, status in (("opportunity_progress_tasks", "analyzing"),
                          ("opportunity_progress_web_checks", "searching")):
        op.execute(sa.text(f"UPDATE {table} SET status='failed', "
                           "error_message='升级前中断，请手动重试', updated_at=CURRENT_TIMESTAMP "
                           "WHERE status=:status").bindparams(status=status))


def downgrade():
    count = op.get_bind().execute(sa.text(
        "SELECT COUNT(*) FROM durable_jobs WHERE status IN ('queued','running')")).scalar()
    if count:
        raise RuntimeError("存在活动任务；请停写并恢复升级前备份，而不是丢弃任务。")
    op.drop_table("durable_jobs")
