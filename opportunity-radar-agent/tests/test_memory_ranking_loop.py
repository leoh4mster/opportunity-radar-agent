import unittest
from unittest.mock import Mock

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.entities import Article, Opportunity, UserProfile, GrowthMemorySnapshot, UserEvent
from app.services.growth_memory.snapshot_service import GrowthMemorySnapshotService
from app.services.json_utils import dumps
from app.services.matching_service import MatchingService
from app.services.llm_service import LLMService
from evaluation.run import OfflineGateway


class MemoryRankingLoopTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.user = UserProfile(name="test")
        article = Article(title="test", content="isolated memory test")
        self.db.add_all([self.user, article])
        self.db.flush()
        self.opp = Opportunity(article_id=article.id, name="科研机会", category="科研")
        self.db.add(self.opp)
        self.db.commit()

    def test_new_snapshot_reaches_ranker_and_other_users_memory_is_excluded(self):
        seen = []
        llm = Mock()

        def analyze(profile, opportunity, base_scores):
            context = profile["growth_memory"]
            seen.append(context)
            return {"relevance_score": 90 if context.get("recent_focus") == "关注科研" else 20,
                    "benefit_score": 50, "content_overview": "test", "relevance_explanation": "test"}

        llm.analyze_recommendation.side_effect = analyze
        matcher = MatchingService(llm=llm)
        baseline = matcher.generate_for_user(self.db, self.user.id)[0].total_score
        self.db.add(GrowthMemorySnapshot(user_id=self.user.id, recent_focus="关注科研", prompt_version="test-v1"))
        other = UserProfile(name="other")
        self.db.add(other)
        self.db.flush()
        self.db.add(GrowthMemorySnapshot(user_id=other.id, recent_focus="不应传入"))
        self.db.commit()
        updated = matcher.generate_for_user(self.db, self.user.id)[0].total_score
        self.assertGreater(updated, baseline)
        self.assertEqual(seen[0], {})
        self.assertEqual(seen[1]["recent_focus"], "关注科研")
        self.assertIn("snapshot_id", seen[1])

    def test_negative_feedback_reduces_rule_score_without_network(self):
        matcher = MatchingService(llm=LLMService(gateway=OfflineGateway()))
        before = matcher.generate_for_user(self.db, self.user.id)[0].total_score
        self.db.add(UserEvent(user_id=self.user.id, event_type="mark_not_interested",
                              event_metadata=dumps({"opportunity_category": "科研"})))
        self.db.commit()
        after = matcher.generate_for_user(self.db, self.user.id)[0].total_score
        self.assertLess(after, before)

    def test_memory_input_preserves_explicit_feedback_text(self):
        event = UserEvent(user_id=self.user.id, event_type="assistant_feedback", event_target=str(self.opp.id),
                          event_metadata=dumps({"opportunity_id": self.opp.id, "feedback_text": "我更希望做科研，不想转销售"}))
        self.db.add(event)
        self.db.commit()
        payload = GrowthMemorySnapshotService()._build_model_input(self.user, [event], {self.opp.id: self.opp}, [])
        self.assertEqual(payload["behavior_summary"]["recent_representative_events"][0]["feedback_text"],
                         "我更希望做科研，不想转销售")
