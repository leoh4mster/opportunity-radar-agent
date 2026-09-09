from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.entities import Article, Opportunity, Recommendation, UserProfile
from app.services.article_identity import compute_content_hash
from app.services.json_utils import dumps
from app.services.llm_service import LLMService
from app.services.matching_service import MatchingService
from evaluation.datasets import DatasetError, load_jsonl, validate_records, write_jsonl
from evaluation.metrics import evaluate_extraction, evaluate_ranking
from evaluation.real_data import (
    check_baseline, evaluator_for_mode, export_extraction_queue, export_ranking_queue,
    rank_record,
)
from evaluation.run import OfflineGateway


class FailingConfiguredGateway:
    def is_configured(self):
        return True

    def chat(self, *args, **kwargs):
        raise RuntimeError("remote failed")


def extraction_record(identifier="article-a", content="正文", status="labeled"):
    return {
        "schema_version": "1.0", "kind": "extraction", "id": identifier,
        "content_hash": compute_content_hash(content), "provenance": {},
        "title": "标题", "content": content, "model_suggestions": [],
        "annotation": {"status": status, "has_opportunity": False,
                       "opportunities": [], "notes": ""},
    }


def ranking_record(status="labeled"):
    return {
        "schema_version": "1.0", "kind": "ranking", "id": "rank-a", "as_of": "2026-01-01",
        "profile": {"major_direction": "人工智能", "current_goals": ["找实习"],
                    "skills": ["Python"], "interested_fields": ["AI"],
                    "disliked_contents": [], "location_preference": "上海",
                    "grade_identity": "大三", "detailed_needs": "AI 实习", "time_preference": ""},
        "candidates": [
            {"id": "intern", "name": "AI 实习", "category": "实习", "summary": "Python AI 项目",
             "location": "上海", "deadline": "2026-12-01", "benefit": 0.9, "cost": 0.3,
             "credibility": 0.9},
            {"id": "lecture", "name": "文学讲座", "category": "讲座", "summary": "古典文学分享",
             "location": "北京", "deadline": "2026-12-01", "benefit": 0.5, "cost": 0.2,
             "credibility": 0.8},
            {"id": "course", "name": "AI 课程", "category": "课程", "summary": "Python 入门",
             "location": "线上", "deadline": "2026-12-01", "benefit": 0.7, "cost": 0.4,
             "credibility": 0.8},
        ],
        "model_order": [],
        "annotation": {"status": status,
                       "relevance": {"intern": 3, "lecture": 0, "course": 2}, "notes": ""},
    }


class DatasetValidationTest(unittest.TestCase):
    def test_round_trip_and_fingerprint_ignore_model_suggestions(self):
        record = extraction_record()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.jsonl"
            write_jsonl(path, [record])
            loaded = load_jsonl(path)
        report = validate_records(loaded, require_complete=True)
        self.assertTrue(report["valid"])
        fingerprint = report["fingerprint"]
        loaded[0]["model_suggestions"] = [{"name": "changed"}]
        self.assertEqual(validate_records(loaded)["fingerprint"], fingerprint)

    def test_invalid_hash_and_incomplete_labels_are_rejected(self):
        record = extraction_record(status="unlabeled")
        record["content_hash"] = "wrong"
        report = validate_records([record], require_complete=True)
        self.assertFalse(report["valid"])
        self.assertTrue(any("content_hash" in error for error in report["errors"]))
        self.assertTrue(any("未完成标注" in error for error in report["errors"]))

    def test_ranking_requires_all_candidate_grades(self):
        record = ranking_record()
        record["annotation"]["relevance"].pop("lecture")
        report = validate_records([record])
        self.assertFalse(report["valid"])
        self.assertTrue(any("完全一致" in error for error in report["errors"]))


class MetricTest(unittest.TestCase):
    def test_multi_opportunity_extraction_counts_matches_fields_and_extra(self):
        record = extraction_record(content="两个机会")
        record["annotation"] = {
            "status": "reviewed", "has_opportunity": True, "notes": "",
            "opportunities": [
                {"name": "AI 实习", "category": "实习", "match_keywords": ["AI实习"],
                 "fields": {"deadline": "2030-01-01", "location": "上海"}},
                {"name": "数据讲座", "category": "讲座", "match_keywords": ["数据讲座"],
                 "fields": {"location": "线上"}},
            ],
        }
        predictions = [
            {"name": "数据讲座报名", "category": "讲座", "location": "线上"},
            {"name": "AI 实习生", "category": "实习", "deadline": "2030-01-02", "location": "上海"},
            {"name": "额外课程", "category": "课程"},
        ]
        report = evaluate_extraction([record], lambda title, content: predictions)
        self.assertEqual(report["opportunity"]["true_positives"], 2)
        self.assertEqual(report["opportunity"]["false_positives"], 1)
        self.assertEqual(report["opportunity"]["precision"], 0.6667)
        self.assertEqual(report["field_exact_match"], 0.6667)
        self.assertEqual(report["field_stats"]["deadline"]["exact_match"], 0.0)

    def test_graded_ranking_metrics(self):
        record = ranking_record()
        report = evaluate_ranking([record], lambda case: ["course", "intern", "lecture"], k=2)
        self.assertEqual(report["evaluated_cases"], 1)
        self.assertEqual(report["metrics"]["mrr"], 1.0)
        self.assertEqual(report["metrics"]["hit_rate@2"], 1.0)
        self.assertEqual(report["metrics"]["precision@2"], 1.0)
        self.assertGreater(report["metrics"]["ndcg@2"], 0.8)
        self.assertLess(report["metrics"]["ndcg@2"], 1.0)

    def test_offline_ranker_uses_fixed_evaluation_date(self):
        record = ranking_record()
        order = rank_record(record, LLMService(gateway=OfflineGateway()))
        self.assertEqual(set(order), {"intern", "lecture", "course"})
        self.assertEqual(order[0], "intern")
        service = MatchingService(today=date(2026, 11, 30))
        self.assertEqual(service._deadline_info("2026-12-01")[0], "urgent")

    def test_deepseek_requires_explicit_network_consent_before_configuration(self):
        with self.assertRaisesRegex(DatasetError, "--allow-network"):
            evaluator_for_mode("deepseek", allow_network=False)

    def test_strict_evaluation_never_disguises_local_fallback_as_remote_output(self):
        service = LLMService(gateway=FailingConfiguredGateway(), allow_local_fallback=False)
        with self.assertRaisesRegex(RuntimeError, "remote failed"):
            service.extract_opportunities("实习招募", "欢迎报名")

    def test_ranking_report_discloses_local_fallback_execution(self):
        from evaluation.real_data import evaluate_task

        report = evaluate_task("ranking", [ranking_record()], "rules", False, k=3)
        self.assertEqual(report["llm_execution"]["calls_total"], 0)
        self.assertEqual(report["llm_execution"]["fallbacks_total"], 3)

    def test_baseline_checks_fingerprint_and_metric_paths(self):
        report = {"task": "ranking", "dataset_fingerprint": "abc",
                  "metrics": {"ndcg@3": 0.8}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.json"
            path.write_text('{"task":"ranking","dataset_fingerprint":"abc",'
                            '"minimum_metrics":{"metrics.ndcg@3":0.9}}', encoding="utf-8")
            regressions = check_baseline(report, path)
            self.assertEqual(regressions[0]["metric"], "metrics.ndcg@3")
            path.write_text('{"task":"ranking","dataset_fingerprint":"different",'
                            '"minimum_metrics":{}}', encoding="utf-8")
            with self.assertRaisesRegex(DatasetError, "数据指纹"):
                check_baseline(report, path)

    def test_invalid_baseline_is_reported_as_dataset_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.json"
            path.write_text("not-json", encoding="utf-8")
            with self.assertRaisesRegex(DatasetError, "有效 JSON"):
                check_baseline({"task": "ranking"}, path)


class QueueExportTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        profile = UserProfile(name="不应导出的姓名", major_direction="AI", current_goals=dumps(["找实习"]))
        self.db.add(profile)
        article_a = Article(title="真实文章 A", source="来源A", content="实习招募正文")
        article_b = Article(title="真实文章 B", source="来源B", content="讲座报名正文")
        self.db.add_all([article_a, article_b])
        self.db.flush()
        opportunity_a = Opportunity(article_id=article_a.id, name="AI 实习", category="实习")
        opportunity_b = Opportunity(article_id=article_b.id, name="技术讲座", category="讲座")
        self.db.add_all([opportunity_a, opportunity_b])
        self.db.flush()
        self.db.add(Recommendation(user_id=profile.id, opportunity_id=opportunity_a.id, total_score=80))
        self.db.commit()
        self.profile_id = profile.id

    def test_extraction_export_keeps_model_output_separate_and_preserves_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "extraction.jsonl"
            first = export_extraction_queue(self.db, path)
            records = load_jsonl(path)
            self.assertEqual(first["records"], 2)
            self.assertEqual(records[0]["annotation"]["status"], "unlabeled")
            self.assertTrue(records[0]["model_suggestions"])
            records[0]["annotation"] = {"status": "labeled", "has_opportunity": False,
                                         "opportunities": [], "notes": "human decision"}
            write_jsonl(path, records)
            second = export_extraction_queue(self.db, path)
            self.assertEqual(second["preserved_labels"], 1)
            self.assertEqual(load_jsonl(path)[0]["annotation"]["notes"], "human decision")

    def test_ranking_export_omits_profile_name_and_starts_unlabeled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ranking.jsonl"
            report = export_ranking_queue(self.db, path, profile_id=self.profile_id, as_of="2026-01-01")
            record = load_jsonl(path)[0]
        self.assertEqual(report["candidates"], 2)
        self.assertNotIn("name", record["profile"])
        self.assertEqual(record["annotation"]["status"], "unlabeled")
        self.assertTrue(all(value is None for value in record["annotation"]["relevance"].values()))
        self.assertEqual(record["model_order"], ["opportunity-1"])


if __name__ == "__main__":
    unittest.main()
