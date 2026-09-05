from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import (
    Article,
    CalendarEvent,
    Opportunity,
    Recommendation,
    Todo,
    UserEvent,
    UserProfile,
)
from app.services.llm_gateway import LLMGateway


class DashboardService:
    """Build the product overview from persisted data and capability config."""

    def build_summary(self, db: Session, user_id: int | None = None) -> dict:
        if user_id is not None and db.get(UserProfile, user_id) is None:
            raise ValueError("用户画像不存在")

        article_count = self._count(db, Article.id)
        processed_article_count = self._count(db, Article.id, Article.processed.is_(True))
        opportunity_count = self._count(db, Opportunity.id)
        verified_opportunity_count = self._count(
            db,
            Opportunity.id,
            Opportunity.verification_status == "verified",
        )
        missing_deadline_count = self._count(
            db,
            Opportunity.id,
            or_(Opportunity.deadline.is_(None), func.trim(Opportunity.deadline) == ""),
        )

        recommendation_filters = []
        todo_filters = [Todo.status == "pending"]
        calendar_filters = [CalendarEvent.start_time >= datetime.utcnow()]
        event_filters = []
        if user_id is not None:
            recommendation_filters.append(Recommendation.user_id == user_id)
            todo_filters.append(Todo.user_id == user_id)
            calendar_filters.append(CalendarEvent.user_id == user_id)
            event_filters.append(UserEvent.user_id == user_id)

        settings = get_settings()
        category_rows = (
            db.query(Opportunity.category, func.count(Opportunity.id))
            .group_by(Opportunity.category)
            .order_by(func.count(Opportunity.id).desc(), Opportunity.category.asc())
            .all()
        )
        recent_opportunities = (
            db.query(Opportunity)
            .order_by(Opportunity.created_at.desc(), Opportunity.id.desc())
            .limit(5)
            .all()
        )

        return {
            "selected_user_id": user_id,
            "counts": {
                "profiles": self._count(db, UserProfile.id),
                "articles": article_count,
                "processed_articles": processed_article_count,
                "opportunities": opportunity_count,
                "recommendations": self._count(db, Recommendation.id, *recommendation_filters),
                "pending_todos": self._count(db, Todo.id, *todo_filters),
                "upcoming_events": self._count(db, CalendarEvent.id, *calendar_filters),
                "interaction_events": self._count(db, UserEvent.id, *event_filters),
            },
            "pipeline": {
                "status": self._pipeline_status(article_count, processed_article_count, opportunity_count),
                "unprocessed_articles": max(article_count - processed_article_count, 0),
                "verified_opportunities": verified_opportunity_count,
                "unverified_opportunities": max(opportunity_count - verified_opportunity_count, 0),
                "opportunities_without_deadline": missing_deadline_count,
            },
            "capabilities": {
                "local_rules": True,
                "llm": LLMGateway().is_configured(),
                "web_search": bool(settings.bocha_api_key.strip()),
                "weixin_search": bool(
                    settings.weixin_search_mcp_url.strip() or settings.weixin_search_mcp_config.strip()
                ),
            },
            "category_distribution": {str(category or "其他"): int(count) for category, count in category_rows},
            "recent_opportunities": [
                {
                    "id": item.id,
                    "name": item.name,
                    "category": item.category,
                    "deadline": item.deadline,
                    "location": item.location,
                    "verification_status": item.verification_status,
                }
                for item in recent_opportunities
            ],
            "generated_at": datetime.utcnow(),
        }

    def _count(self, db: Session, column, *filters) -> int:
        query = db.query(func.count(column))
        if filters:
            query = query.filter(*filters)
        return int(query.scalar() or 0)

    def _pipeline_status(self, articles: int, processed: int, opportunities: int) -> str:
        if articles == 0:
            return "empty"
        if processed < articles:
            return "needs_processing"
        if opportunities == 0:
            return "no_opportunities"
        return "ready"
