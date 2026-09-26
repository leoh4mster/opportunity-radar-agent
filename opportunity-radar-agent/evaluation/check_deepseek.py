"""One bounded request with fictional data; never falls back to local rules."""
from __future__ import annotations

import argparse
import json
import time

from app.core.observability import runtime_metrics
from app.services.llm_gateway import LLMGateway, LLMGatewayError


def check_connection(allow_network: bool = False) -> dict:
    if not allow_network:
        raise ValueError("此检查会调用 DeepSeek 并可能计费；请显式添加 --allow-network。")
    gateway = LLMGateway()
    if not gateway.is_configured():
        raise ValueError("请在本机 .env 配置自己的 DEEPSEEK_API_KEY。")
    runtime_metrics.reset()
    started = time.monotonic()
    raw = gateway.chat(
        messages=[
            {"role": "system", "content": "从虚构通知提取地点，只输出 JSON 对象，字段 location。"},
            {"role": "user", "content": "虚构测试：星河数据讲座开放报名。地点：线上。"},
        ],
        temperature=0, max_retries=0, response_format={"type": "json_object"},
    )
    if json.loads(raw) != {"location": "线上"}:
        raise ValueError("API 已返回，但结构化结果不符合检查预期。")
    return {"ok": True, "scope": "single_synthetic_structured_request",
            "model": gateway.debug_config()['active_model'],
            "duration_ms": round((time.monotonic() - started) * 1000),
            "llm_execution": runtime_metrics.snapshot()['llm'],
            "note": "仅验证连通和一次 JSON 输出，不代表真实抽取、排序或 Agent 闭环已验收。"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-network', action='store_true')
    args = parser.parse_args()
    try:
        result = check_connection(args.allow_network)
    except (ValueError, LLMGatewayError) as exc:
        # Provider errors can contain response bodies; don't expose credentials
        # or request details in the terminal by printing arbitrary exceptions.
        message = str(exc) if type(exc) is ValueError else '远程检查失败，请核对账户、模型和网络；没有使用本地规则回退。'
        print(json.dumps({'ok': False, 'error_type': type(exc).__name__, 'message': message}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
