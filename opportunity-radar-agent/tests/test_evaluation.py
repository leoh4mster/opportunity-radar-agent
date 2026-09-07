import unittest
from evaluation.run import evaluate, OfflineGateway
from app.services.llm_service import LLMService


class EvaluationTest(unittest.TestCase):
    def test_false_positive_missing_prediction_and_field_error(self):
        cases = [
            {"id": "a", "title": "a", "content": "", "expected": {"category": "实习", "deadline": ""}},
            {"id": "b", "title": "b", "content": "", "expected": None},
            {"id": "c", "title": "c", "content": "", "expected": {"category": "讲座", "deadline": ""}},
        ]
        outputs = {"a": [{"category": "实习", "deadline": "wrong"}], "b": [{"category": "讲座"}], "c": []}
        report = evaluate(cases, lambda title, content: outputs[title])
        self.assertEqual(report["precision"], 0.5)
        self.assertEqual(report["recall"], 0.5)
        self.assertEqual(report["f1"], 0.5)
        self.assertEqual(report["field_exact_match"], 0.25)
        self.assertEqual(len(report["failures"]), 3)

    def test_offline_gateway_cannot_use_real_credentials(self):
        service = LLMService(gateway=OfflineGateway())
        self.assertEqual(service.extract_opportunities("日记", "日记正文"), [])
