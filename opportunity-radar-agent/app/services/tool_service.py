from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.entities import ToolCall
from app.services.json_utils import dumps
from app.services.opportunity_agent import OpportunityAgent


SUPPORTED_TOOLS = {"search", "calendar", "todo"}


class ToolService:
    def call(self, db: Session, tool_name: str, user_id: int | None, opportunity_id: int | None, payload: dict) -> ToolCall:
        try:
            return self._call(db, tool_name, user_id, opportunity_id, payload)
        except Exception:
            db.rollback()
            raise

    def _call(self, db: Session, tool_name: str, user_id: int | None, opportunity_id: int | None, payload: dict) -> ToolCall:
        if tool_name not in SUPPORTED_TOOLS:
            raise ValueError(f"暂不支持工具：{tool_name}")
        if tool_name == "search":
            raise ValueError("旧搜索入口不执行真实检索，请使用机会助理或联网核实接口")
        if user_id is None or opportunity_id is None:
            raise ValueError("创建待办或日历必须指定用户和机会")
        result = OpportunityAgent().run_opportunity_action(
            db, user_id, opportunity_id, tool_name, extra_params=payload, commit=False)
        call = ToolCall(
            user_id=user_id,
            opportunity_id=opportunity_id,
            tool_name=tool_name,
            payload=dumps(payload),
            status=result["status"],
            result=dumps(result),
        )
        db.add(call)
        db.commit()
        db.refresh(call)
        return call
