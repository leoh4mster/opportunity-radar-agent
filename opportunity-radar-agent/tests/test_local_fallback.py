from __future__ import annotations

import unittest

from app.services.llm_service import LLMService


class LocalFallbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.service = LLMService()
        self.service.gateway.is_configured = lambda: False

    def test_extracts_structured_opportunity_without_api_key(self) -> None:
        result = self.service.extract_opportunities(
            "AI 实习生招募",
            """
            某高校实验室现招募 AI 实习生，欢迎报名申请。
            报名截止：2030-12-31
            地点：上海
            职位要求：熟悉 Python 和机器学习
            报名链接：https://example.com/apply
            """,
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["category"], "实习")
        self.assertEqual(result[0]["deadline"], "2030-12-31")
        self.assertEqual(result[0]["location"], "上海")
        self.assertEqual(result[0]["link"], "https://example.com/apply")

    def test_ignores_article_without_actionable_opportunity(self) -> None:
        result = self.service.extract_opportunities(
            "校园生活随笔",
            "今天分享校园风景和读书感受，没有活动或招募信息。",
        )

        self.assertEqual(result, [])

    def test_local_recommendation_explanation_is_actionable(self) -> None:
        result = self.service.analyze_recommendation(
            profile={"current_goals": ["找实习"], "skills": ["Python"]},
            opportunity={"name": "数据实习", "category": "实习", "summary": "参与数据分析项目。"},
            base_scores={"relevance_score": 82, "benefit_score": 76},
        )

        self.assertEqual(result["relevance_score"], 82)
        self.assertIn("找实习", result["relevance_explanation"])
        self.assertTrue(result["content_overview"])


if __name__ == "__main__":
    unittest.main()
