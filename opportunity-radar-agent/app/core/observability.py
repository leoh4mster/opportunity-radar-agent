"""Low-cardinality runtime metrics and privacy-conscious structured logging."""
from __future__ import annotations

import json
import logging
import math
import sys
import threading
import time
import uuid
from collections import Counter, defaultdict
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Callable


request_id_context: ContextVar[str] = ContextVar("request_id", default="-")
_DURATION_BUCKETS_MS = (10, 50, 100, 250, 500, 1000, 2500, 5000)


def current_request_id() -> str:
    value = request_id_context.get()
    return value if value != "-" else uuid.uuid4().hex


def run_with_request_context(request_id: str, callback: Callable[..., Any], *args, **kwargs):
    """Carry request correlation into a new background thread."""
    token = request_id_context.set(request_id)
    try:
        return callback(*args, **kwargs)
    finally:
        request_id_context.reset(token)


class JsonFormatter(logging.Formatter):
    """Emit one JSON object per line without serializing request payloads."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", record.getMessage()),
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id_context.get()),
        }
        for name in (
            "method", "route", "status_code", "duration_ms", "provider", "model",
            "attempt", "outcome", "error_type", "task", "reason",
        ):
            value = getattr(record, name, None)
            if value is not None:
                payload[name] = value
        if record.exc_info and logging.getLogger().isEnabledFor(logging.DEBUG):
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_context.get()
        return True


def configure_logging(level: str = "INFO", log_format: str = "json") -> None:
    """Configure only the root application handler; safe to call repeatedly."""
    root = logging.getLogger()
    normalized_level = getattr(logging, (level or "INFO").upper(), logging.INFO)
    root.setLevel(normalized_level)
    handler = next((item for item in root.handlers if getattr(item, "opportunity_radar", False)), None)
    if handler is None:
        handler = logging.StreamHandler(sys.stdout)
        handler.opportunity_radar = True
        handler.addFilter(ContextFilter())
        root.addHandler(handler)
    if (log_format or "json").lower() == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s %(message)s"
        ))
    # These access loggers include raw URLs (and therefore query parameters).
    # Our middleware emits one bounded route-template event instead.
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _bucket_name(duration_ms: float) -> str:
    for upper in _DURATION_BUCKETS_MS:
        if duration_ms <= upper:
            return f"le_{upper}ms"
    return "gt_5000ms"


class RuntimeMetrics:
    """Thread-safe, process-local counters with bounded label cardinality."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with getattr(self, "_lock", threading.Lock()):
            self.started_at = time.time()
            self.http_total = 0
            self.http_in_flight = 0
            self.http_status = Counter()
            self.http_routes: dict[tuple[str, str], dict[str, Any]] = defaultdict(
                lambda: {"requests": 0, "errors": 0, "duration_sum_ms": 0.0,
                         "duration_max_ms": 0.0, "duration_buckets": Counter()}
            )
            self.llm_calls = Counter()
            self.llm_attempts = Counter()
            self.llm_fallbacks = Counter()
            self.llm_duration_sum = Counter()
            self.llm_duration_max = Counter()
            self.llm_duration_buckets: dict[str, Counter[str]] = defaultdict(Counter)

    def http_started(self) -> None:
        with self._lock:
            self.http_in_flight += 1

    def http_finished(self, method: str, route: str, status_code: int, duration_ms: float) -> None:
        family = f"{status_code // 100}xx"
        with self._lock:
            self.http_in_flight = max(0, self.http_in_flight - 1)
            self.http_total += 1
            self.http_status[family] += 1
            row = self.http_routes[(method, route)]
            row["requests"] += 1
            row["errors"] += int(status_code >= 400)
            row["duration_sum_ms"] += duration_ms
            row["duration_max_ms"] = max(row["duration_max_ms"], duration_ms)
            row["duration_buckets"][_bucket_name(duration_ms)] += 1

    def llm_attempt(self, provider: str, model: str, outcome: str, duration_ms: float,
                    error_type: str = "") -> None:
        key = (provider, model, outcome, error_type or "none")
        with self._lock:
            self.llm_attempts[key] += 1
            self.llm_duration_sum[outcome] += duration_ms
            self.llm_duration_max[outcome] = max(self.llm_duration_max[outcome], duration_ms)
            self.llm_duration_buckets[outcome][_bucket_name(duration_ms)] += 1

    def llm_call(self, provider: str, model: str, outcome: str) -> None:
        with self._lock:
            self.llm_calls[(provider, model, outcome)] += 1

    def llm_fallback(self, task: str, reason: str) -> None:
        with self._lock:
            self.llm_fallbacks[(task, reason)] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            routes = []
            for (method, route), row in sorted(self.http_routes.items()):
                requests = row["requests"]
                routes.append({
                    "method": method,
                    "route": route,
                    "requests": requests,
                    "errors": row["errors"],
                    "duration_ms": {
                        "average": round(row["duration_sum_ms"] / requests, 2) if requests else 0,
                        "maximum": round(row["duration_max_ms"], 2),
                        "buckets": dict(sorted(row["duration_buckets"].items())),
                    },
                })
            attempts = [
                {"provider": provider, "model": model, "outcome": outcome,
                 "error_type": error_type, "count": count}
                for (provider, model, outcome, error_type), count in sorted(self.llm_attempts.items())
            ]
            calls = [
                {"provider": provider, "model": model, "outcome": outcome, "count": count}
                for (provider, model, outcome), count in sorted(self.llm_calls.items())
            ]
            fallbacks = [
                {"task": task, "reason": reason, "count": count}
                for (task, reason), count in sorted(self.llm_fallbacks.items())
            ]
            latency = {
                outcome: {
                    "average_ms": round(self.llm_duration_sum[outcome] / sum(
                        count for (provider, model, result, error), count in self.llm_attempts.items()
                        if result == outcome
                    ), 2),
                    "maximum_ms": round(self.llm_duration_max[outcome], 2),
                    "buckets": dict(sorted(buckets.items())),
                }
                for outcome, buckets in sorted(self.llm_duration_buckets.items())
            }
            return {
                "generated_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
                "uptime_seconds": math.floor(max(0, now - self.started_at)),
                "scope": "single_process",
                "http": {"requests_total": self.http_total, "in_flight": self.http_in_flight,
                         "status_families": dict(sorted(self.http_status.items())), "routes": routes},
                "llm": {"calls_total": sum(self.llm_calls.values()),
                        "attempts_total": sum(self.llm_attempts.values()),
                        "fallbacks_total": sum(self.llm_fallbacks.values()),
                        "calls": calls, "attempts": attempts, "fallbacks": fallbacks,
                        "attempt_latency": latency},
            }


runtime_metrics = RuntimeMetrics()
