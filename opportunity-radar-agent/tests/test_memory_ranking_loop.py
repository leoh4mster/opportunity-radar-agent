import unittest
import json
import warnings
from unittest.mock import Mock

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.exc import SAWarning

from app.core.database import Base
from app.models.entities import Article, Opportunity, UserProfile, GrowthMemorySnapshot, UserEvent, OpportunityProgressPlan
from app.services.growth_memory.snapshot_service import GrowthMemorySnapshotService, REQUIRED_FIELDS
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

    def test_refresh_with_loaded_recommendation_has_no_identity_collision(self):
        matcher = MatchingService(llm=LLMService(gateway=OfflineGateway()))
        old = matcher.generate_for_user(self.db, self.user.id)[0]
        with warnings.catch_warnings():
            warnings.simplefilter('error', SAWarning)
            new = matcher.generate_for_user(self.db, self.user.id)[0]
        self.assertIsNot(new, old)
        self.assertEqual(new.opportunity_id, self.opp.id)

    def test_memory_gets_plan_risks_and_regenerates_when_prompt_version_changes(self):
        gateway = Mock()
        gateway.settings.llm_model = 'test-model'
        gateway.chat.return_value = json.dumps({field: '先核验来源并确认可投入时间' for field in REQUIRED_FIELDS})
        service = GrowthMemorySnapshotService(gateway=gateway)
        other = UserProfile(name='other')
        self.db.add(other); self.db.flush()
        self.db.add_all([
            UserEvent(user_id=self.user.id, event_type='mark_useful', event_target=str(self.opp.id)),
            OpportunityProgressPlan(user_id=self.user.id, opportunity_id=self.opp.id,
                                    overall_judgment='建议观察', risks_json=dumps(['来源尚未核验'])),
            OpportunityProgressPlan(user_id=other.id, opportunity_id=self.opp.id,
                                    overall_judgment='不应泄漏', risks_json=dumps(['其他用户的风险'])),
        ])
        self.db.commit()
        first = service.generate(self.db, self.user.id)
        payload = json.loads(gateway.chat.call_args.kwargs['messages'][1]['content'])
        self.assertEqual(len(payload['current_plans']), 1)
        self.assertEqual(payload['current_plans'][0]['risks'], ['来源尚未核验'])
        self.assertFalse(service.generate(self.db, self.user.id)['updated'])
        first['data'].prompt_version = 'old-prompt'
        self.db.commit()
        self.assertTrue(service.generate(self.db, self.user.id)['updated'])
        self.assertEqual(gateway.chat.call_count, 2)
