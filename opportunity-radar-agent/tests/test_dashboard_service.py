from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.entities import (
    Article,
    CalendarEvent,
    Opportunity,
    Recommendation,
    Todo,
    UserEvent,
    UserProfile,
)
from app.schemas.dto import DashboardSummaryOut
from app.services.dashboard_service import DashboardService


class DashboardServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.session = sessionmaker(bind=engine)()

    def tearDown(self) -> None:
        self.session.close()

    def test_summary_aggregates_global_and_user_metrics(self) -> None:
        user = UserProfile(name="测试用户", current_goals='["找实习"]')
        self.session.add(user)
        self.session.flush()

        processed = Article(title="已处理文章", content="正文", processed=True)
        waiting = Article(title="待处理文章", content="待处理正文", processed=False)
        self.session.add_all([processed, waiting])
        self.session.flush()

        verified = Opportunity(
            article_id=processed.id,
            name="AI 实习",
            category="实习",
            deadline="2030-12-31",
            verification_status="verified",
        )
        missing_deadline = Opportunity(
            article_id=processed.id,
            name="科研招募",
            category="科研",
            deadline="",
        )
        self.session.add_all([verified, missing_deadline])
        self.session.flush()

        self.session.add_all(
            [
                Recommendation(user_id=user.id, opportunity_id=verified.id, total_score=88),
                Todo(user_id=user.id, opportunity_id=verified.id, title="准备简历", status="pending"),
                CalendarEvent(
                    user_id=user.id,
                    opportunity_id=verified.id,
                    title="实习截止",
                    start_time=datetime.utcnow() + timedelta(days=3),
                ),
                UserEvent(user_id=user.id, event_type="view_opportunity", event_target=str(verified.id)),
            ]
        )
        self.session.commit()

        summary = DashboardService().build_summary(self.session, user.id)
        validated = DashboardSummaryOut.model_validate(summary)

        self.assertEqual(validated.counts.profiles, 1)
        self.assertEqual(validated.counts.articles, 2)
        self.assertEqual(validated.counts.processed_articles, 1)
        self.assertEqual(validated.counts.opportunities, 2)
        self.assertEqual(validated.counts.recommendations, 1)
        self.assertEqual(validated.counts.pending_todos, 1)
        self.assertEqual(validated.counts.upcoming_events, 1)
        self.assertEqual(validated.counts.interaction_events, 1)
        self.assertEqual(validated.pipeline.status, "needs_processing")
        self.assertEqual(validated.pipeline.verified_opportunities, 1)
        self.assertEqual(validated.pipeline.opportunities_without_deadline, 1)
        self.assertEqual(validated.category_distribution, {"实习": 1, "科研": 1})
        self.assertEqual(len(validated.recent_opportunities), 2)

    def test_unknown_user_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "用户画像不存在"):
            DashboardService().build_summary(self.session, user_id=404)

    def test_pipeline_status_covers_empty_and_ready_states(self) -> None:
        service = DashboardService()
        self.assertEqual(service._pipeline_status(0, 0, 0), "empty")
        self.assertEqual(service._pipeline_status(2, 1, 1), "needs_processing")
        self.assertEqual(service._pipeline_status(2, 2, 0), "no_opportunities")
        self.assertEqual(service._pipeline_status(2, 2, 1), "ready")


if __name__ == "__main__":
    unittest.main()
