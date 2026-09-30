"""Action contracts and complete deletion graphs, with SQLite FKs enabled."""
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql.dml import Delete
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models import entities as m
from app.services.opportunity_agent import OpportunityAgent
from app.services.opportunity_progress_service import OpportunityProgressService
from app.services.json_utils import dumps


class BusinessIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        event.listen(self.engine, "connect", lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"))
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, autoflush=False)()
        self.overrides = app.dependency_overrides.copy()
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)
        self.guard = patch("app.services.llm_gateway.LLMGateway.chat", side_effect=AssertionError("network forbidden"))
        self.guard.start()
        self.user = m.UserProfile(name="test-user")
        self.article = m.Article(title="test", content="独立测试文章")
        self.db.add_all([self.user, self.article])
        self.db.flush()
        self.opp = m.Opportunity(article_id=self.article.id, name="示例大学科研项目招募通知",
                                 category="科研", organizer="示例大学", link="https://example.invalid/apply",
                                 deadline="2030-12-31")
        self.db.add(self.opp)
        self.db.commit()
        self.uid, self.oid, self.aid = self.user.id, self.opp.id, self.article.id

    def tearDown(self):
        self.guard.stop()
        self.client.close()
        app.dependency_overrides = self.overrides
        self.db.close()
        self.engine.dispose()

    def action(self, action):
        response = self.client.post(f"/opportunities/{self.oid}/actions",
                                    json={"user_id": self.uid, "action": action})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_local_check_does_not_create_verified_state_or_evidence(self):
        result = self.action("verify")
        self.assertEqual(result["result"]["verification_status"], "rule_checked")
        self.assertIsNone(result["result"]["credibility_score"])
        self.assertEqual(result["result"]["evidence_sources"], [])
        self.assertNotEqual(result["opportunity_state"], "verified")
        self.db.refresh(self.opp)
        self.assertIsNone(self.opp.verified_at)

    def test_local_risk_words_remain_suspicious(self):
        self.opp.requirements = "内部名额保录取"
        self.db.commit()
        result = self.action("verify")
        self.assertEqual(result["result"]["verification_status"], "suspicious")
        self.assertNotEqual(result["opportunity_state"], "verified")

    def test_local_enrichment_does_not_promote_article_link_to_official_url(self):
        result = self.action("enrich")
        self.assertEqual(result["result"]["official_url"], "unknown")
        self.assertEqual(result["result"]["registration_url"], "unknown")

    def test_todo_actions_and_legacy_tool_share_one_persisted_todo(self):
        first = self.action("todo")
        second = self.action("todo")
        legacy = self.client.post("/tools/todo", json={"user_id": self.uid, "opportunity_id": self.oid, "payload": {}})
        self.assertEqual(legacy.status_code, 200, legacy.text)
        self.assertEqual(first["result"]["todo_id"], second["result"]["todo_id"])
        self.assertTrue(second["result"]["already_exists"])
        self.assertEqual(self.db.query(m.Todo).count(), 1)
        self.assertEqual(self.db.query(m.UserEvent).filter_by(event_type="create_todo").count(), 1)

    def test_action_failure_rolls_back_todo_state_and_event(self):
        with patch("app.services.opportunity_agent.ToolCallLog", side_effect=RuntimeError("log failure")):
            with self.assertRaises(RuntimeError):
                OpportunityAgent().run_opportunity_action(self.db, self.uid, self.oid, "todo")
        self.db.commit()
        for model in (m.Todo, m.UserEvent, m.OpportunityState):
            self.assertEqual(self.db.query(model).count(), 0)

    def test_unknown_calendar_date_does_not_claim_todo_creation(self):
        self.opp.deadline = "待定"
        self.db.commit()
        result = self.action("calendar")
        self.assertEqual(result["status"], "calendar_skipped_no_date")
        self.assertNotIn("已生成待办", result["result"]["summary"])
        self.assertEqual(self.db.query(m.Todo).count(), 0)
        self.assertEqual(self.db.query(m.CalendarEvent).count(), 0)

    def make_plan(self):
        plan = m.OpportunityProgressPlan(user_id=self.uid, opportunity_id=self.oid)
        self.db.add(plan)
        self.db.flush()
        items = [m.OpportunityProgressItem(plan_id=plan.id, title=title) for title in ("准备简历", "撰写研究计划")]
        self.db.add_all(items)
        self.db.commit()
        return plan, items

    def test_distinct_plan_tasks_keep_identity_and_retry_is_idempotent(self):
        general_id = self.action("todo")["result"]["todo_id"]
        plan, items = self.make_plan()
        ids = [item.id for item in items]
        service = OpportunityProgressService()
        result = service.sync_plan_items_to_todos(self.db, plan.id, ids)
        self.assertEqual(len(result["created"]), 2)
        self.assertEqual(len({item.todo_id for item in items}), 2)
        self.assertNotIn(general_id, [item.todo_id for item in items])
        self.assertEqual({self.db.get(m.Todo, item.todo_id).title for item in items}, {"准备简历", "撰写研究计划"})
        repeated = service.sync_plan_items_to_todos(self.db, plan.id, ids)
        self.assertEqual(len(repeated["existing"]), 2)
        self.assertEqual(self.db.query(m.Todo).count(), 3)

    def test_sync_batch_failure_leaves_no_partial_tasks(self):
        plan, items = self.make_plan()
        service = OpportunityProgressService()
        with patch.object(service, "_todo_description_from_plan_item", side_effect=["first", RuntimeError("failure")]):
            with self.assertRaises(RuntimeError):
                service.sync_plan_items_to_todos(self.db, plan.id, [item.id for item in items])
        self.db.commit()
        self.assertEqual(self.db.query(m.Todo).count(), 0)
        self.assertTrue(all(not item.synced_to_todo for item in self.db.query(m.OpportunityProgressItem)))

    def test_confirmed_plan_changes_update_only_linked_child_todos(self):
        general_id = self.action('todo')['result']['todo_id']
        plan, items = self.make_plan()
        service = OpportunityProgressService()
        service.sync_plan_items_to_todos(self.db, plan.id, [item.id for item in items])
        update = m.OpportunityProgressUpdate(plan_id=plan.id, proposed_changes_json=dumps({
            'task_changes': [{'task_id': items[0].id, 'change_type': 'complete'},
                             {'task_id': items[1].id, 'change_type': 'modify', 'new_title': '修订材料',
                              'new_description': '补充项目评测报告', 'new_priority': 'high'}]}))
        self.db.add(update); self.db.commit()
        self.assertEqual(self.db.get(m.Todo, items[0].todo_id).status, 'pending')
        service.confirm_plan_update(self.db, plan.id, update.id)
        self.assertEqual(self.db.get(m.Todo, items[0].todo_id).status, 'completed')
        changed = self.db.get(m.Todo, items[1].todo_id)
        self.assertEqual(changed.title, '修订材料')
        self.assertIn('补充项目评测报告', changed.description)
        self.assertEqual(changed.priority, 'high')
        self.assertEqual(self.db.get(m.Todo, general_id).status, 'pending')

    def test_plan_confirmation_failure_rolls_back_items_todos_and_version(self):
        plan, items = self.make_plan()
        service = OpportunityProgressService()
        service.sync_plan_items_to_todos(self.db, plan.id, [items[0].id])
        update = m.OpportunityProgressUpdate(plan_id=plan.id, proposed_changes_json=dumps({
            'task_changes': [{'task_id': items[0].id, 'change_type': 'complete'}]}))
        self.db.add(update); self.db.commit()
        with patch.object(service, '_save_plan_version', side_effect=RuntimeError('save failure')):
            with self.assertRaises(RuntimeError):
                service.confirm_plan_update(self.db, plan.id, update.id)
        self.db.commit()
        self.assertEqual(items[0].status, 'pending')
        self.assertEqual(self.db.get(m.Todo, items[0].todo_id).status, 'pending')
        self.assertEqual(plan.version_number, 1)
        self.assertEqual(update.confirmation_status, 'pending')

    def test_invalid_todo_link_cannot_modify_general_or_other_users_task(self):
        general_id = self.action('todo')['result']['todo_id']
        plan, items = self.make_plan()
        items[0].todo_id, items[0].synced_to_todo = general_id, True
        update = m.OpportunityProgressUpdate(plan_id=plan.id, proposed_changes_json=dumps({
            'task_changes': [{'task_id': items[0].id, 'change_type': 'complete'}]}))
        self.db.add(update); self.db.commit()
        with self.assertRaisesRegex(ValueError, '身份不一致'):
            OpportunityProgressService().confirm_plan_update(self.db, plan.id, update.id)
        self.assertEqual(self.db.get(m.Todo, general_id).status, 'pending')
        self.assertEqual(items[0].status, 'pending')

    def populate_graph(self):
        self.action("todo")
        self.action("calendar")
        plan, items = self.make_plan()
        task = m.OpportunityProgressTask(user_id=self.uid, opportunity_id=self.oid)
        self.db.add(task)
        self.db.flush()
        plan.source_task_id = task.id
        update = m.OpportunityProgressUpdate(plan_id=plan.id)
        self.db.add(update)
        self.db.flush()
        self.db.add(m.OpportunityProgressVersion(plan_id=plan.id, update_id=update.id))
        self.db.add(m.OpportunityProgressWebCheck(user_id=self.uid, opportunity_id=self.oid,
                                                 task_id=task.id, plan_id=plan.id))
        for model in (m.EnrichmentResult, m.SimilarOpportunityResult, m.Recommendation):
            self.db.add(model(user_id=self.uid, opportunity_id=self.oid))
        self.db.add(m.ToolCall(user_id=self.uid, opportunity_id=self.oid, tool_name="test"))
        self.db.add(m.MemoryReflection(user_id=self.uid, reflection_type="test", summary="test"))
        self.db.add(m.GrowthMemorySnapshot(user_id=self.uid))
        self.db.commit()

    def assert_graph_removed(self):
        for model in (m.OpportunityProgressVersion, m.OpportunityProgressUpdate, m.OpportunityProgressItem,
                      m.OpportunityProgressPlan, m.OpportunityProgressTask, m.OpportunityProgressWebCheck,
                      m.CalendarEvent, m.Todo, m.EnrichmentResult, m.SimilarOpportunityResult,
                      m.Recommendation, m.ToolCall, m.ToolCallLog, m.OpportunityState):
            self.assertEqual(self.db.query(model).count(), 0, model.__name__)
        self.assertEqual(self.db.execute(text("PRAGMA foreign_key_check")).all(), [])

    def test_delete_article_cleans_full_graph_and_preserves_profile(self):
        self.populate_graph()
        response = self.client.delete(f"/articles/{self.aid}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assert_graph_removed()
        self.assertEqual(self.db.query(m.UserProfile).count(), 1)
        self.assertEqual(self.db.query(m.Article).count(), 0)

    def test_delete_profile_cleans_full_graph_and_preserves_articles(self):
        self.populate_graph()
        other = m.UserProfile(name="unrelated")
        self.db.add(other)
        self.db.commit()
        response = self.client.delete(f"/profiles/{self.uid}")
        self.assertEqual(response.status_code, 200, response.text)
        self.assert_graph_removed()
        self.assertEqual(self.db.query(m.UserProfile).one().name, "unrelated")
        self.assertEqual(self.db.query(m.Article).count(), 1)
        self.assertEqual(self.db.query(m.Opportunity).count(), 1)
        for model in (m.UserEvent, m.MemoryReflection, m.GrowthMemorySnapshot):
            self.assertEqual(self.db.query(model).count(), 0)

    def test_delete_failure_is_atomic(self):
        self.populate_graph()
        execute = self.db.execute

        def fail_after_children(statement, *args, **kwargs):
            if isinstance(statement, Delete) and statement.table.name == "opportunities":
                raise SQLAlchemyError("injected failure after deleting child records")
            return execute(statement, *args, **kwargs)

        with patch.object(self.db, "execute", side_effect=fail_after_children):
            self.assertEqual(self.client.delete(f"/articles/{self.aid}").status_code, 500)
        self.db.commit()
        self.assertEqual(self.db.query(m.Article).count(), 1)
        self.assertEqual(self.db.query(m.CalendarEvent).count(), 1)
        self.assertEqual(self.db.query(m.OpportunityProgressPlan).count(), 1)

    def test_offline_product_flow_import_rank_act_feedback_and_delete(self):
        with patch("app.services.llm_gateway.LLMGateway.is_configured", return_value=False):
            profile = self.client.post("/profiles", json={"name": "端到端用户", "current_goals": ["找实习"]})
            self.assertEqual(profile.status_code, 200, profile.text)
            uid = profile.json()["id"]
            upload = self.client.post("/articles/upload", files={"file": ("实习.txt",
                "实习招募\n欢迎报名\n报名截止：2030-12-31\n地点：上海".encode())})
            self.assertEqual(upload.status_code, 200, upload.text)
            aid = upload.json()["article_ids"][0]
            processed = self.client.post("/pipeline/process")
            self.assertEqual(processed.status_code, 202, processed.text)
            from app.services.job_service import JobService
            queue = JobService(sessionmaker(bind=self.engine))
            self.db.rollback()
            while queue.run_once():
                pass
            ranked = self.client.post(f"/recommendations/generate/{uid}?force=false")
            self.assertEqual(ranked.status_code, 202, ranked.text)
            self.db.rollback()
            queue.run_once()
            self.db.expire_all()
            ranked = self.client.get(f"/recommendations/{uid}")
            rec = next(row for row in ranked.json() if row["opportunity"]["article_id"] == aid)
            oid = rec["opportunity_id"]
            for action in ("todo", "calendar"):
                response = self.client.post(f"/opportunities/{oid}/actions", json={"user_id": uid, "action": action})
                self.assertEqual(response.status_code, 200, response.text)
            calendar = self.client.get(f"/calendar/{uid}")
            self.assertEqual(calendar.status_code, 200, calendar.text)
            self.assertEqual(sum(len(calendar.json()[key]) for key in ("upcoming_7_days", "later_events", "expired_events")), 1)
            feedback = self.client.post(f"/feedback/recommendation/{uid}/{rec['id']}",
                                        json={"event_type": "mark_useful", "opportunity_id": oid})
            self.assertEqual(feedback.status_code, 200, feedback.text)
            self.assertEqual(self.client.delete(f"/articles/{aid}").status_code, 200)
            self.assertEqual(self.db.query(m.Todo).filter_by(user_id=uid).count(), 0)
            self.assertEqual(self.db.execute(text("PRAGMA foreign_key_check")).all(), [])
