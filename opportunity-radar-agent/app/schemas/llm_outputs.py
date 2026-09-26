"""Business validation for untrusted remote model output."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ModelOutput(BaseModel):
    model_config = ConfigDict(strict=True, str_strip_whitespace=True, allow_inf_nan=False)


class ExtractedOpportunity(ModelOutput):
    name: str = Field(min_length=1, max_length=255)
    category: Literal["竞赛", "实习", "科研", "实验室招募", "讲座", "夏令营", "奖学金", "课程", "出国", "保研", "其他"]
    organizer: str = ""
    event_time: str = ""
    deadline: str = ""
    location: str = ""
    target_audience: str = ""
    link: str = ""
    requirements: str = ""
    summary: str = ""
    benefit: float = Field(ge=0, le=1)
    cost: float = Field(ge=0, le=1)
    credibility: float = Field(ge=0, le=1)


class RecommendationAnalysis(ModelOutput):
    relevance_score: float = Field(ge=0, le=100)
    benefit_score: float = Field(ge=0, le=100)
    content_overview: str = Field(min_length=80, max_length=500)
    relevance_explanation: str = Field(min_length=1)
