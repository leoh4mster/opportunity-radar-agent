import json
import unittest
from unittest.mock import Mock

from pydantic import ValidationError

from app.services.extraction_service import ExtractionService
from app.services.llm_gateway import LLMAuthError
from app.services.llm_service import LLMService


class ModelOutputValidationTest(unittest.TestCase):
    def service(self, outputs, fallback=False):
        gateway = Mock()
        gateway.is_configured.return_value = True
        gateway.chat.side_effect = [json.dumps(output, ensure_ascii=False) for output in outputs]
        return LLMService(gateway=gateway, allow_local_fallback=fallback)

    def valid_analysis(self):
        return {"relevance_score": 80, "benefit_score": 75,
                "content_overview": "这项机会提供科研实践和项目协作，申请前应核对原文中的资格、地点和时间要求。" * 3,
                "relevance_explanation": "符合科研入门目标。"}

    def test_repeated_invalid_overview_is_rejected(self):
        bad = dict(self.valid_analysis(), content_overview="太短")
        service = self.service([bad, bad])
        with self.assertRaisesRegex(RuntimeError, "validation failed"):
            service.analyze_recommendation({}, {}, {})
        self.assertEqual(service.gateway.chat.call_count, 2)

    def test_invalid_score_and_types_cannot_escape_validation(self):
        for value in (999, -4, float("nan"), float("inf"), "80", True, None):
            with self.subTest(value=value):
                bad = dict(self.valid_analysis(), relevance_score=value)
                with self.assertRaises(RuntimeError):
                    self.service([bad, bad]).analyze_recommendation({}, {}, {})

    def test_retry_can_return_valid_second_response(self):
        valid = self.valid_analysis()
        service = self.service([dict(valid, content_overview="短"), valid])
        self.assertEqual(service.analyze_recommendation({}, {}, {})["relevance_score"], 80)

    def test_missing_fields_are_not_silently_filled_with_model_defaults(self):
        bad = self.valid_analysis()
        del bad["relevance_explanation"]
        with self.assertRaises(RuntimeError):
            self.service([bad, bad]).analyze_recommendation({}, {}, {})

    def test_bad_extraction_is_rejected_in_strict_mode_and_falls_back_in_product(self):
        for bad in ([{"name": "招募", "category": "实习", "benefit": "高"}], ["invalid"],
                    [{"name": "招募", "category": "非法分类", "benefit": .6, "cost": .4, "credibility": .7}]):
            with self.subTest(bad=bad):
                with self.assertRaises((ValidationError, RuntimeError)):
                    self.service([bad]).extract_opportunities("实习招募", "欢迎报名，地点：上海")
                result = self.service([bad], fallback=True).extract_opportunities("实习招募", "欢迎报名，地点：上海")
                self.assertEqual(result[0]["category"], "实习")

    def test_zero_is_a_valid_extraction_score_and_survives_storage_conversion(self):
        item = {"name": "实习机会", "category": "实习", "benefit": 0, "cost": 0, "credibility": 0}
        output = self.service([[item]]).extract_opportunities("实习", "报名")
        row = ExtractionService()._to_opportunity(1, output[0])
        self.assertEqual((row.benefit, row.cost, row.credibility), (0, 0, 0))

    def test_strict_mode_rejects_missing_credentials_instead_of_using_rules(self):
        gateway = Mock()
        gateway.is_configured.return_value = False
        service = LLMService(gateway=gateway, allow_local_fallback=False)
        with self.assertRaises(LLMAuthError):
            service.extract_opportunities("实习", "报名")
        with self.assertRaises(LLMAuthError):
            service.analyze_recommendation({}, {}, {})
        gateway.chat.assert_not_called()
