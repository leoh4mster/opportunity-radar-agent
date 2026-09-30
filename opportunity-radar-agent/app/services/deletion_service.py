"""Delete an owned graph in dependency order; the caller owns the transaction."""
from sqlalchemy import delete, select, or_
from sqlalchemy.orm import Session

from app.models import entities as models


def delete_related_data(db: Session, *, opportunity_ids=(), user_id=None) -> int:
    def scope(model):
        return model.user_id == user_id if user_id is not None else model.opportunity_id.in_(opportunity_ids)

    plan_ids = select(models.OpportunityProgressPlan.id).where(scope(models.OpportunityProgressPlan))
    task_ids = select(models.OpportunityProgressTask.id).where(scope(models.OpportunityProgressTask))
    from app.services.job_service import ACTIVE
    job_scope = models.DurableJob.user_id == user_id if user_id is not None else or_(
        models.DurableJob.kind == "recommendation",
        (models.DurableJob.kind == "analysis") & models.DurableJob.object_id.in_(task_ids),
        (models.DurableJob.kind == "web_check") & models.DurableJob.object_id.in_(
            select(models.OpportunityProgressWebCheck.id).where(scope(models.OpportunityProgressWebCheck))))
    for job in db.query(models.DurableJob).filter(job_scope).all():
        job.snapshot, job.checkpoints = "{}", "{}"
        if job.status in ACTIVE:
            job.status, job.active_key, job.token, job.lease_until = "failed", None, None, None
            job.error_code, job.error_message = "input_changed", "输入已删除，请重新提交任务"
    db.flush()
    # Remove referencing rows before plans, tasks and todos. Bulk deletes avoid
    # ORM relationship loading accidentally setting non-null foreign keys to NULL.
    db.execute(delete(models.OpportunityProgressWebCheck).where(or_(
        scope(models.OpportunityProgressWebCheck),
        models.OpportunityProgressWebCheck.plan_id.in_(plan_ids),
        models.OpportunityProgressWebCheck.task_id.in_(task_ids),
    )).execution_options(synchronize_session=False))
    for model in (models.OpportunityProgressVersion, models.OpportunityProgressItem,
                  models.OpportunityProgressUpdate):
        db.execute(delete(model).where(model.plan_id.in_(plan_ids)).execution_options(synchronize_session=False))
    for model in (models.OpportunityProgressPlan, models.OpportunityProgressTask,
                  models.CalendarEvent, models.EnrichmentResult, models.SimilarOpportunityResult,
                  models.OpportunityState, models.ToolCallLog, models.ToolCall, models.Todo):
        db.execute(delete(model).where(scope(model)).execution_options(synchronize_session=False))
    result = db.execute(delete(models.Recommendation).where(scope(models.Recommendation))
                        .execution_options(synchronize_session=False))
    if user_id is not None:
        for model in (models.UserEvent, models.MemoryReflection, models.GrowthMemorySnapshot):
            db.execute(delete(model).where(model.user_id == user_id).execution_options(synchronize_session=False))
    return result.rowcount
