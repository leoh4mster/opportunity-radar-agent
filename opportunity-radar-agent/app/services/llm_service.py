"""Structured LLM tasks built on the unified LLMGateway."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.services.llm_gateway import LLMGateway
from app.core.observability import runtime_metrics


CATEGORIES = ["竞赛", "实习", "科研", "实验室招募", "讲座", "夏令营", "奖学金", "课程", "出国", "保研", "其他"]
logger = logging.getLogger(__name__)


class LLMService:
    def __init__(self, gateway: LLMGateway | None = None) -> None:
        self.gateway = gateway if gateway is not None else LLMGateway()

    def extract_opportunities(self, article_title: str, article_content: str) -> list[dict[str, Any]]:
        if not self.gateway.is_configured():
            runtime_metrics.llm_fallback("extract_opportunities", "not_configured")
            return self._rule_extract(article_title, article_content)
        system = "你是信息抽取助手。只输出 JSON 数组，不要 Markdown，不要额外解释。"
        user = f"""
请从公众号文章中抽取对大学生发展有价值的机会。
字段：
name, category, organizer, event_time, deadline, location, target_audience,
link, requirements, summary, benefit, cost, credibility
category 只能是：{", ".join(CATEGORIES)}
benefit/cost/credibility 是 0 到 1 的数字。
如果没有机会，输出 []。

标题：{article_title}
正文：
{article_content[:8000]}
"""
        try:
            text = self.gateway.chat(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.2,
            )
            return self._parse_json_array(text)
        except Exception as exc:
            runtime_metrics.llm_fallback("extract_opportunities", "remote_error")
            logger.warning("remote extraction unavailable; using local rules error_type=%s", type(exc).__name__)
            return self._rule_extract(article_title, article_content)

    def summarize_recommendations(self, profile: dict[str, Any], recommendations: list[dict[str, Any]]) -> str:
        if not recommendations:
            return "本期没有发现可推荐的机会。可以继续导入文章，或调整用户画像。"
        if not self.gateway.is_configured():
            runtime_metrics.llm_fallback("summarize_recommendations", "not_configured")
            return self._rule_summary(profile, recommendations)
        system = "你是个性化机会雷达 Agent。请输出简洁中文摘要。"
        user = f"""
请基于用户画像和推荐结果生成摘要。
输出结构：
1. 本期最值得关注
2. 为什么匹配
3. 下一步行动
4. 需要留意的截止时间

用户画像：{json.dumps(profile, ensure_ascii=False)}
推荐结果：{json.dumps(recommendations[:8], ensure_ascii=False)}
"""
        return self.gateway.chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.4,
        )

    def analyze_recommendation(
        self,
        profile: dict[str, Any],
        opportunity: dict[str, Any],
        base_scores: dict[str, float],
    ) -> dict[str, Any]:
        if not self.gateway.is_configured():
            runtime_metrics.llm_fallback("analyze_recommendation", "not_configured")
            return self._rule_recommendation_analysis(profile, opportunity, base_scores)
        system = "你是机会推荐排序助手。只输出 JSON 对象，不要 Markdown，不要额外解释。"
        user = f"""
请基于用户画像、机会内容和基础规则分数，输出推荐排序辅助信息。
必须输出 JSON：
{{
  "relevance_score": 0,
  "benefit_score": 0,
  "content_overview": "",
  "relevance_explanation": ""
}}
relevance_score 和 benefit_score 取值 0 到 100。
content_overview 请用 150 到 500 个中文字符，基于 article_content_excerpt 和机会字段改写出自然完整摘要。
要求：不要只写标题，不要重复标题，不要直接复制 opportunity.summary，不要在半句话中断。

用户画像：{json.dumps(profile, ensure_ascii=False)}
机会：{json.dumps(opportunity, ensure_ascii=False)}
基础分数：{json.dumps(base_scores, ensure_ascii=False)}
"""
        parsed: dict[str, Any] | None = None
        last_error: Exception | None = None
        for attempt in range(2):
            prompt = user
            if attempt:
                prompt += "\n\n重要：上一次输出不是合法 JSON 或摘要质量不合格。请只返回一个合法 JSON 对象，字符串内部不要使用未转义的双引号。"
            try:
                text = self.gateway.chat(
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.2,
                )
                parsed = self._parse_json_object(text)
                content_overview = str(parsed.get("content_overview", "")).strip()
                source_summary = str(opportunity.get("summary") or "").strip()
                title = str(opportunity.get("name") or "").strip()
                self._validate_content_overview(content_overview, source_summary, title)
                break
            except RuntimeError as exc:
                last_error = exc
        if parsed is None:
            raise RuntimeError("LLM validation failed: {}".format(last_error))
        content_overview = str(parsed.get("content_overview", "")).strip()
        return {
            "relevance_score": float(parsed.get("relevance_score", base_scores.get("relevance_score", 50))),
            "benefit_score": float(parsed.get("benefit_score", base_scores.get("benefit_score", 50))),
            "content_overview": content_overview,
            "relevance_explanation": str(parsed.get("relevance_explanation", "")),
        }

    def _validate_content_overview(self, overview: str, source_summary: str, title: str) -> None:
        if len(overview) < 80:
            raise RuntimeError("LLM content_overview is too short")
        if source_summary and overview == source_summary:
            raise RuntimeError("LLM content_overview copied opportunity.summary")
        if title and overview.startswith(f"{title} {title}"):
            raise RuntimeError("LLM content_overview repeats title")
        if overview.endswith(("，", "、", "；", "：", "和", "与", "的", "在", "为", "对")):
            raise RuntimeError("LLM content_overview appears truncated")

    def _parse_json_array(self, text: str) -> list[dict[str, Any]]:
        cleaned = text.strip()
        match = re.search(r"\[[\s\S]*\]", cleaned)
        if match:
            cleaned = match.group(0)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            fixed = self._repair_json(cleaned, "array")
            try:
                parsed = json.loads(fixed)
            except json.JSONDecodeError as exc:
                raise RuntimeError("LLM output is not valid JSON array") from exc
        if not isinstance(parsed, list):
            raise RuntimeError("LLM output is not a JSON array")
        return [item for item in parsed if isinstance(item, dict)]

    def _parse_json_object(self, text: str) -> dict[str, Any]:
        cleaned = text.strip()
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            cleaned = match.group(0)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            fixed = self._repair_json(cleaned, "object")
            try:
                parsed = json.loads(fixed)
            except json.JSONDecodeError as exc:
                raise RuntimeError("LLM output is not valid JSON object") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("LLM output is not a JSON object")
        return parsed

    def _repair_json(self, text: str, expected: str) -> str:
        system = "你是 JSON 格式修复器。只输出修复后的 JSON，不要 Markdown，不要解释。"
        user = f"请把下面内容修复为合法 JSON {expected}。不要改变字段含义：\n{text[:4000]}"
        return self.gateway.chat(
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.0,
            max_retries=1,
            response_format={"type": "json_object"} if expected == "object" else None,
        )

    def _rule_extract(self, title: str, content: str) -> list[dict[str, Any]]:
        """Best-effort local extractor used when no remote LLM is configured."""
        text = (content or "").strip()
        if not text:
            return []
        combined = f"{title}\n{text}"
        category = self._detect_category(combined)
        if category == "其他" or not self._looks_like_opportunity(combined):
            return []
        return [
            {
                "name": self._detect_name(combined, title, category),
                "category": category,
                "organizer": self._match_after(combined, ["主办方", "组织方", "单位", "实验室"]) or "未注明",
                "event_time": self._match_after(combined, ["活动时间", "项目时间", "实习时间", "时间"]),
                "deadline": self._match_after(combined, ["报名截止日期", "报名截止", "申请截止", "截止", "DDL"]),
                "location": self._match_after(combined, ["工作城市", "地点", "城市", "校区"]) or ("线上" if "线上" in combined else ""),
                "target_audience": self._match_after(combined, ["适合人群", "面向对象", "招募对象", "申请对象"]),
                "link": self._detect_link(combined),
                "requirements": self._match_after(combined, ["职位要求", "申请条件", "报名条件", "要求"]),
                "summary": re.sub(r"\s+", " ", text)[:500],
                "benefit": self._estimate_benefit(category, combined),
                "cost": self._estimate_cost(combined),
                "credibility": 0.85 if self._detect_link(combined) or any(word in combined for word in ["大学", "学院", "实验室"]) else 0.65,
            }
        ]

    def _detect_category(self, text: str) -> str:
        mapping = {
            "竞赛": ["竞赛", "比赛", "挑战赛", "大赛", "hackathon"],
            "实习": ["实习", "intern", "招聘", "岗位"],
            "实验室招募": ["实验室招募", "课题组招募", "助研招募"],
            "科研": ["科研", "课题", "论文", "研究项目", "助研"],
            "讲座": ["讲座", "沙龙", "论坛", "分享会", "经验分享", "校园行", "讲台", "报告"],
            "夏令营": ["夏令营", "暑期学校", "summer school"],
            "奖学金": ["奖学金", "资助", "助学金"],
            "课程": ["课程", "训练营", "workshop", "工作坊"],
            "出国": ["留学", "交换项目", "海外交流"],
            "保研": ["保研", "推免", "预推免"],
        }
        lines = text.splitlines()
        title = (lines[0] if lines else "").lower()
        body = "\n".join(lines[1:]).lower()
        scores = {}
        for category, keywords in mapping.items():
            title_hits = sum(1 for keyword in keywords if keyword.lower() in title)
            body_hits = sum(min(body.count(keyword.lower()), 3) for keyword in keywords)
            scores[category] = title_hits * 5 + body_hits
        category, score = max(scores.items(), key=lambda item: item[1])
        return category if score > 0 else "其他"

    def _looks_like_opportunity(self, text: str) -> bool:
        keywords = ["报名", "申请", "截止", "招募", "招收", "时间", "地点", "要求", "联系方式"]
        return sum(1 for keyword in keywords if keyword in text) >= 2

    def _detect_name(self, text: str, title: str, category: str) -> str:
        if title.strip():
            return title.strip()[:255]
        for line in text.splitlines():
            candidate = line.strip(" #*-\t")
            lower = candidate.lower()
            if 4 <= len(candidate) <= 80 and any(word in lower for word in ["招募", "竞赛", "实习", "讲座", "夏令营", "项目", "课程", "报名"]):
                return candidate
        return title or f"未命名{category}机会"

    def _match_after(self, text: str, labels: list[str]) -> str:
        for label in labels:
            match = re.search(rf"{re.escape(label)}\s*[:：]\s*([^\n]+)", text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()[:255]
        return ""

    def _detect_link(self, text: str) -> str:
        match = re.search(r"https?://[^\s)）]+", text)
        return match.group(0) if match else ""

    def _estimate_benefit(self, category: str, text: str) -> float:
        base = {
            "实习": 0.9,
            "科研": 0.85,
            "实验室招募": 0.82,
            "竞赛": 0.78,
            "夏令营": 0.86,
            "奖学金": 0.75,
            "课程": 0.65,
            "讲座": 0.55,
            "出国": 0.72,
            "保研": 0.82,
            "其他": 0.5,
        }[category]
        if any(word in text for word in ["名校", "国家级", "顶会", "保研", "转正", "推荐信"]):
            base += 0.08
        return min(base, 1.0)

    def _estimate_cost(self, text: str) -> float:
        cost = 0.4
        if "线下" in text or "异地" in text:
            cost += 0.2
        if "每周" in text or "长期" in text:
            cost += 0.15
        if any(word in text for word in ["简历", "面试", "作品集", "论文"]):
            cost += 0.1
        return min(cost, 1.0)

    def _rule_recommendation_analysis(
        self,
        profile: dict[str, Any],
        opportunity: dict[str, Any],
        base_scores: dict[str, float],
    ) -> dict[str, Any]:
        overview = re.sub(r"\s+", " ", str(opportunity.get("summary") or opportunity.get("name") or "")).strip()
        goals = "、".join(profile.get("current_goals") or []) or "当前目标"
        category = str(opportunity.get("category") or "机会")
        return {
            "content_overview": overview[:500],
            "relevance_explanation": f"这是一个{category}类机会，可结合你的{goals}目标、现有技能以及时间地点偏好判断优先级；报名入口或截止时间不明确时，应先查看原文确认。",
            "relevance_score": self._bounded_score(base_scores.get("relevance_score"), 50),
            "benefit_score": self._bounded_score(base_scores.get("benefit_score"), 50),
        }

    def _rule_summary(self, profile: dict[str, Any], recommendations: list[dict[str, Any]]) -> str:
        name = profile.get("name") or "你"
        titles = "、".join(str(item.get("name") or "未命名机会") for item in recommendations[:3])
        return f"{name}，本期共找到 {len(recommendations)} 个机会，建议优先查看：{titles}。请先核对原文中的截止时间和报名入口。"

    def _bounded_score(self, value: Any, fallback: float) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            score = fallback
        return max(0.0, min(100.0, score))
