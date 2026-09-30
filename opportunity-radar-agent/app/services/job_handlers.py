"""Snapshot / compute / fenced commit adapters for the four durable workflows."""
from datetime import date, datetime
import hashlib
import json

from sqlalchemy.orm import joinedload

from app.models import entities as m
from app.services.job_service import JobFailure, encode
from app.services.llm_gateway import LLMGateway, LLMTransientError, LLMResponseFormatError
from app.services.llm_service import LLMService
from app.services.extraction_service import ExtractionService
from app.services.matching_service import MatchingService
from app.services.feedback_service import FeedbackService
from app.services.growth_memory.memory_manager import GrowthMemoryManager
from app.services.opportunity_state_service import OpportunityStateService
from app.services.opportunity_progress_service import OpportunityProgressService, MAX_ROUNDS
from app.services.external_search_provider import BochaSearchProvider


def row(obj):
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns if getattr(obj, c.name) is not None}


def required(db, model, ident):
    obj = db.get(model, ident)
    if obj is None:
        raise JobFailure("input_changed", "输入不存在")
    return obj


def prepare(db, kind, object_id, user_id, request_id):
    model = {"extraction": m.Article, "recommendation": m.UserProfile,
             "analysis": m.OpportunityProgressTask, "web_check": m.OpportunityProgressWebCheck}.get(kind)
    if model is None:
        raise ValueError("未知任务类型")
    obj = required(db, model, object_id)
    if kind == "recommendation":
        return obj.id
    if kind in ("analysis", "web_check"):
        return obj.user_id
    return None


def snapshot(db, job):
    """Read only: never materialize missing OpportunityState rows here."""
    service = OpportunityProgressService()
    if job.kind == "extraction":
        article = required(db, m.Article, job.object_id)
        return {"id": article.id, "title": article.title, "content": article.content}
    if job.kind == "recommendation":
        user = required(db, m.UserProfile, job.object_id)
        memory = GrowthMemoryManager().recommendation_context(db, user.id)
        feedback, matching = FeedbackService(), MatchingService()
        opportunities = db.query(m.Opportunity).options(joinedload(m.Opportunity.article)).order_by(m.Opportunity.id).all()
        candidates = []
        for opportunity in opportunities:
            state = db.query(m.OpportunityState).filter_by(user_id=user.id, opportunity_id=opportunity.id).first()
            candidates.append({"opportunity": row(opportunity),
                "article": row(opportunity.article) if opportunity.article else None,
                "state": state.state if state and state.state != "new" else "recommended",
                "negative": matching._recent_negative_feedback_count(db, user.id, opportunity),
                "bias": feedback.get_user_feedback_bias(db, user.id, opportunity)})
        return {"user": row(user), "memory": memory, "candidates": candidates}
    if job.kind == "analysis":
        task = required(db, m.OpportunityProgressTask, job.object_id)
        return service._build_context(db, required(db, m.UserProfile, task.user_id),
                                      required(db, m.Opportunity, task.opportunity_id))
    check = required(db, m.OpportunityProgressWebCheck, job.object_id)
    opportunity = required(db, m.Opportunity, check.opportunity_id)
    user = required(db, m.UserProfile, check.user_id)
    task = required(db, m.OpportunityProgressTask, check.task_id) if check.task_id else None
    plan = required(db, m.OpportunityProgressPlan, check.plan_id) if check.plan_id else None
    return {"query": check.query, "has_plan": bool(plan), "context": {
        "user_profile": service._profile_dict(user), "opportunity": service._opportunity_dict(opportunity),
        "task": service.serialize_task(task) if task else {},
        "plan": service.serialize_plan(db, plan, include_pending_update=False) if plan else {}}}


def version(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def mark_failed(db, job):
    model = {"analysis": m.OpportunityProgressTask, "web_check": m.OpportunityProgressWebCheck}.get(job.kind)
    obj = db.get(model, job.object_id) if model else None
    if obj:
        obj.status, obj.error_message, obj.updated_at = "failed", job.error_message, datetime.utcnow()


class StrictProgress(OpportunityProgressService):
    def _parse_json_object(self, text, repair=False):
        # Durable jobs own retries. Do not issue hidden JSON repair requests.
        try:
            value = json.loads(text)
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, TypeError) as exc:
            raise LLMResponseFormatError("Invalid structured output") from exc


def execute(queue, job_id, token):
    gateway = LLMGateway()
    with queue.fenced(job_id, token) as (db, job):
        current = snapshot(db, job)
        fingerprint = version(current)
        if job.input_version and job.input_version != fingerprint:
            raise JobFailure("input_changed", "输入已变化")
        if not job.input_version:
            job.snapshot, job.input_version = encode(current), fingerprint
            job.mode = "deepseek" if gateway.is_configured() else "rules"
            # Freeze ranking date for resume across midnight.
            job.result = encode({"as_of": date.today().isoformat()})
        data, done, kind = json.loads(job.snapshot), json.loads(job.checkpoints), job.kind
        mode, metadata = job.mode, json.loads(job.result)
    if mode == "deepseek" and not gateway.is_configured():
        raise JobFailure("model_unavailable", "模型未配置")
    if kind in ("analysis", "web_check") and mode != "deepseek":
        raise JobFailure("model_unavailable", "模型未配置")
    # A rule-mode job stays offline even if a key is added between attempts.
    if mode == "rules":
        gateway.is_configured = lambda: False
    llm = LLMService(gateway=gateway, allow_local_fallback=(mode == "rules"))
    progress = StrictProgress(gateway=gateway)

    def stage(key, compute, total):
        if key not in done:
            value = compute()  # No session or write transaction is open here.
            queue.checkpoint(job_id, token, key, value, total)
            done[key] = value
        return done[key]

    if kind == "extraction":
        result = stage("extraction", lambda: llm.extract_opportunities(data["title"], data["content"]), 1)
    elif kind == "recommendation":
        matching = MatchingService(llm=llm, today=date.fromisoformat(metadata["as_of"]), strict_llm=True)
        user = m.UserProfile(**data["user"])
        result = []
        for candidate in data["candidates"]:
            opportunity = m.Opportunity(**candidate["opportunity"])
            if candidate["article"]:
                opportunity.article = m.Article(**candidate["article"])
            def score():
                rec = matching._score(user, opportunity, candidate["state"],
                    [data["memory"]["recent_focus"]] if data["memory"].get("recent_focus") else [],
                    candidate["negative"], candidate["bias"], memory_context=data["memory"])
                return row(rec)
            result.append(stage(f"candidate:{opportunity.id}", score, len(data["candidates"])))
    elif kind == "analysis":
        rounds = []
        focus = "initial_analysis"
        for index in range(MAX_ROUNDS):
            item = stage(f"round:{index + 1}", lambda: progress._run_round(data, rounds, focus, index + 1), MAX_ROUNDS + 1)
            rounds.append(item)
            if progress._should_stop_rounds(rounds):
                break
            focus = item.get("next_focus") or "action_planning"
        result = stage("final_summary", lambda: progress._run_final(data, rounds), len(rounds) + 1)
    else:
        def search():
            response = BochaSearchProvider().search(data["query"], count=7)
            if response.status == "unavailable":
                raise JobFailure("search_unavailable", "搜索未配置")
            if response.status != "success":
                message = response.error_message.lower()
                if any(code in message for code in ("429", "500", "502", "503", "504", "timeout", "timed out", "urlopen")):
                    raise LLMTransientError("Search temporarily unavailable")
                raise JobFailure("search_failed", "搜索失败")
            if not response.results:
                raise JobFailure("search_empty", "无搜索结果")
            return [progress._web_source_dict(item) for item in response.results]
        sources = stage("search", search, 2)
        result = stage("web_analysis", lambda: progress._run_web_check_analysis(data["context"], sources, data["has_plan"]), 2)

    with queue.fenced(job_id, token) as (db, job):
        if version(snapshot(db, job)) != job.input_version:
            raise JobFailure("input_changed", "输入已变化")
        if kind == "extraction":
            article = required(db, m.Article, job.object_id)
            count = 0
            if not article.processed and not db.query(m.Opportunity).filter_by(article_id=article.id).count():
                for item in result:
                    db.add(ExtractionService()._to_opportunity(article.id, item))
                    count += 1
            article.processed = True
            output = {"article_id": article.id, "created_opportunities": count}
        elif kind == "recommendation":
            db.query(m.Recommendation).filter_by(user_id=job.object_id).delete(synchronize_session="fetch")
            for item in result:
                db.add(m.Recommendation(**item))
                OpportunityStateService().advance_state(db, job.object_id, item["opportunity_id"], "recommended")
            output = {"user_id": job.object_id, "recommendations": len(result), "as_of": metadata["as_of"]}
        elif kind == "analysis":
            task = required(db, m.OpportunityProgressTask, job.object_id)
            task.rounds, task.final_result = encode(rounds), encode(result)
            task.suggested_todos = encode(result.get("suggested_todos") or [])
            task.status = "waiting_confirmation" if result.get("should_create_todos") else "stopped"
            task.current_stage, task.error_message = "final_summary", ""
            task.updated_at = datetime.utcnow()
            output = {"task_id": task.id}
        else:
            check = required(db, m.OpportunityProgressWebCheck, job.object_id)
            check.sources_json, check.analysis_json = encode(sources), encode(result)
            check.status, check.error_message, check.updated_at = "completed", "", datetime.utcnow()
            output = {"web_check_id": check.id}
        job.result = encode(output)
        job.status, job.stage, job.active_key = "succeeded", "completed", None
        job.completed = job.total
        job.token, job.lease_until = None, None
        job.error_code, job.error_message = "", ""
