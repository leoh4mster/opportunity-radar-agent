from __future__ import annotations

import io
import json
import logging
import re
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.observability import (
    JsonFormatter, request_id_context, run_with_request_context, runtime_metrics,
)
from app.main import app
from app.services.llm_gateway import LLMAuthError, LLMGateway, LLMTransientError
from app.services.llm_service import LLMService


class FakeUnconfiguredGateway:
    def is_configured(self):
        return False


class ObservabilityTest(unittest.TestCase):
    def setUp(self):
        runtime_metrics.reset()
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_request_id_is_echoed_or_safely_replaced(self):
        supplied = self.client.get("/health", headers={"X-Request-ID": "collector:job-42"})
        self.assertEqual(supplied.headers["X-Request-ID"], "collector:job-42")
        invalid = self.client.get("/health", headers={"X-Request-ID": "bad id\nsecret"})
        generated = invalid.headers["X-Request-ID"]
        self.assertRegex(generated, r"^[0-9a-f]{32}$")

    def test_http_metrics_use_route_templates_and_exclude_scrapes(self):
        def test_endpoint(item_id: int):
            return {"item_id": item_id}

        before = list(app.router.routes)
        app.add_api_route("/__metrics_test__/{item_id}", test_endpoint, methods=["GET"])
        self.addCleanup(lambda: setattr(app.router, "routes", before))
        self.client.get("/__metrics_test__/999999")
        self.client.get("/health?token=must-not-be-a-label")
        snapshot = self.client.get("/observability/metrics").json()
        self.assertEqual(snapshot["scope"], "single_process")
        self.assertEqual(snapshot["http"]["requests_total"], 2)
        self.assertEqual(snapshot["http"]["in_flight"], 0)
        routes = {(row["method"], row["route"]): row for row in snapshot["http"]["routes"]}
        self.assertIn(("GET", "/__metrics_test__/{item_id}"), routes)
        self.assertIn(("GET", "/health"), routes)
        self.assertNotIn("must-not-be-a-label", json.dumps(snapshot))
        again = self.client.get("/observability/metrics").json()
        self.assertEqual(again["http"]["requests_total"], 2)

    def test_json_formatter_adds_context_without_secrets_or_request_data(self):
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        handler.setFormatter(JsonFormatter())
        logger = logging.getLogger("test.structured")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        token = request_id_context.set("req-safe")
        try:
            logger.info("request completed", extra={"event": "http_request_completed",
                        "method": "GET", "route": "/health", "status_code": 200,
                        "duration_ms": 12.5})
        finally:
            request_id_context.reset(token)
            logger.removeHandler(handler)
            logger.propagate = True
        row = json.loads(output.getvalue())
        self.assertEqual(row["request_id"], "req-safe")
        self.assertEqual(row["route"], "/health")
        self.assertNotIn("query", row)
        self.assertNotIn("body", row)

    def test_background_work_inherits_then_releases_request_context(self):
        seen = run_with_request_context("background-42", request_id_context.get)
        self.assertEqual(seen, "background-42")
        self.assertEqual(request_id_context.get(), "-")

    def test_exception_details_are_hidden_at_normal_log_level(self):
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        handler.setFormatter(JsonFormatter())
        logger = logging.getLogger("test.private_error")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        try:
            try:
                raise RuntimeError("sensitive user value")
            except RuntimeError:
                logger.exception("operation failed")
        finally:
            logger.removeHandler(handler)
            logger.propagate = True
        row = json.loads(output.getvalue())
        self.assertNotIn("exception", row)
        self.assertNotIn("sensitive user value", json.dumps(row))

    def test_unhandled_error_returns_the_same_trace_id(self):
        def explode():
            raise RuntimeError("boom")

        before = list(app.router.routes)
        app.add_api_route("/__metrics_test__/explode", explode, methods=["GET"])
        self.addCleanup(lambda: setattr(app.router, "routes", before))
        client = TestClient(app, raise_server_exceptions=False)
        self.addCleanup(client.close)
        response = client.get("/__metrics_test__/explode", headers={"X-Request-ID": "trace-500"})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers["X-Request-ID"], "trace-500")
        self.assertEqual(response.json()["detail"]["request_id"], "trace-500")
        self.assertEqual(runtime_metrics.snapshot()["http"]["status_families"]["5xx"], 1)

    def configured_gateway(self):
        gateway = LLMGateway()
        gateway.settings = SimpleNamespace(
            llm_provider="deepseek", llm_model="deepseek-chat",
            deepseek_api_key="never-log-this-key", deepseek_base_url="https://api.deepseek.com",
        )
        return gateway

    def test_llm_success_and_retry_are_counted_without_calling_network(self):
        gateway = self.configured_gateway()
        with patch.object(gateway, "_post_json", side_effect=[
            LLMTransientError("temporary"), {"choices": [{"message": {"content": "ok"}}]},
        ]), patch("app.services.llm_gateway.time.sleep"):
            self.assertEqual(gateway.chat([{"role": "user", "content": "private prompt"}]), "ok")
        llm = runtime_metrics.snapshot()["llm"]
        self.assertEqual(llm["calls_total"], 1)
        self.assertEqual(llm["attempts_total"], 2)
        self.assertEqual({row["outcome"] for row in llm["attempts"]}, {"failure", "success"})
        serialized = json.dumps(llm)
        self.assertNotIn("never-log-this-key", serialized)
        self.assertNotIn("private prompt", serialized)

    def test_terminal_llm_error_keeps_classification(self):
        gateway = self.configured_gateway()
        with patch.object(gateway, "_post_json", side_effect=LLMAuthError("denied")):
            with self.assertRaises(LLMAuthError):
                gateway.chat([{"role": "user", "content": "hello"}])
        snapshot = runtime_metrics.snapshot()["llm"]
        self.assertEqual(snapshot["calls"][0]["outcome"], "failure")
        self.assertEqual(snapshot["attempts"][0]["error_type"], "LLMAuthError")

    def test_unexpected_llm_client_failure_is_counted_and_sanitized(self):
        gateway = self.configured_gateway()
        with patch.object(gateway, "_post_json", side_effect=TypeError("private implementation detail")):
            with self.assertRaisesRegex(RuntimeError, "Unexpected LLM client failure"):
                gateway.chat([{"role": "user", "content": "secret content"}], max_retries=0)
        snapshot = runtime_metrics.snapshot()["llm"]
        self.assertEqual(snapshot["calls_total"], 1)
        self.assertEqual(snapshot["attempts"][0]["error_type"], "TypeError")
        self.assertNotIn("private implementation detail", json.dumps(snapshot))

    def test_local_rule_fallback_is_visible_without_remote_call(self):
        result = LLMService(FakeUnconfiguredGateway()).extract_opportunities(
            "实习招募", "欢迎报名 AI 实习，地点：上海"
        )
        self.assertTrue(result)
        llm = runtime_metrics.snapshot()["llm"]
        self.assertEqual(llm["calls_total"], 0)
        self.assertEqual(llm["fallbacks"], [{
            "task": "extract_opportunities", "reason": "not_configured", "count": 1,
        }])


if __name__ == "__main__":
    unittest.main()
