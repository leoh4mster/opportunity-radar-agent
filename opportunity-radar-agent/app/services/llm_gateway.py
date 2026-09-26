"""Unified LLM Gateway.

All production LLM calls must go through LLMGateway.chat().
Supported providers:
    - deepseek
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any
import socket
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import get_settings
from app.core.observability import runtime_metrics


logger = logging.getLogger(__name__)

DEFAULT_MODELS = {
    "deepseek": "deepseek-flash",
}


class LLMGatewayError(RuntimeError):
    error_code = "llm_error"
    retryable = False


class LLMTransientError(LLMGatewayError):
    error_code = "llm_transient"
    retryable = True


class LLMAuthError(LLMGatewayError):
    error_code = "llm_auth_error"


class LLMBadRequestError(LLMGatewayError):
    error_code = "llm_bad_request"


class LLMResponseFormatError(LLMGatewayError):
    error_code = "llm_response_format_error"


class LLMGateway:
    def __init__(self) -> None:
        self.settings = get_settings()

    def is_configured(self) -> bool:
        """Return whether the selected remote provider has usable credentials."""
        provider = (self.settings.llm_provider or "").lower().strip()
        if provider != "deepseek":
            return False
        api_key, _, _ = self._provider_config(provider)
        return bool(api_key.strip())

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_retries: int = 2,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        provider = (self.settings.llm_provider or "").lower().strip()
        if provider == "mock":
            runtime_metrics.llm_call(provider, "", "rejected")
            raise LLMBadRequestError("LLM_PROVIDER=mock is not allowed in production.")
        if provider != "deepseek":
            runtime_metrics.llm_call(provider or "unset", "", "rejected")
            raise LLMBadRequestError("Unsupported LLM_PROVIDER: {}".format(provider))

        api_key, endpoint, model = self._provider_config(provider)
        if not api_key:
            runtime_metrics.llm_call(provider, model, "rejected")
            raise LLMAuthError("{} API key is missing.".format(provider))
        self._log_config(provider, endpoint, model, bool(api_key))

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "thinking": {"type": self.settings.llm_thinking},
            "max_tokens": self.settings.llm_max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            attempt_started = time.perf_counter()
            try:
                logger.info("llm request", extra={"event": "llm_attempt_started", "provider": provider,
                            "model": model, "attempt": attempt + 1})
                data = self._post_json(endpoint, api_key, payload)
                content = self._extract_content(data)
                duration_ms = (time.perf_counter() - attempt_started) * 1000
                runtime_metrics.llm_attempt(provider, model, "success", duration_ms)
                runtime_metrics.llm_call(provider, model, "success")
                logger.info("llm response", extra={"event": "llm_attempt_completed", "provider": provider,
                            "model": model, "attempt": attempt + 1, "outcome": "success",
                            "duration_ms": round(duration_ms, 2)})
                return content
            except LLMGatewayError as exc:
                last_error = exc
                duration_ms = (time.perf_counter() - attempt_started) * 1000
                error_type = type(exc).__name__
                runtime_metrics.llm_attempt(provider, model, "failure", duration_ms, error_type)
                logger.warning("llm request failed", extra={"event": "llm_attempt_completed",
                               "provider": provider, "model": model, "attempt": attempt + 1,
                               "outcome": "failure", "error_type": error_type,
                               "duration_ms": round(duration_ms, 2)})
                if exc.retryable and attempt < max_retries:
                    time.sleep(0.8 * (attempt + 1))
                    continue
                break
            except Exception as exc:
                duration_ms = (time.perf_counter() - attempt_started) * 1000
                error_type = type(exc).__name__
                runtime_metrics.llm_attempt(provider, model, "failure", duration_ms, error_type)
                runtime_metrics.llm_call(provider, model, "failure")
                logger.warning("unexpected llm failure", extra={"event": "llm_attempt_completed",
                               "provider": provider, "model": model, "attempt": attempt + 1,
                               "outcome": "failure", "error_type": error_type,
                               "duration_ms": round(duration_ms, 2)})
                raise LLMGatewayError("Unexpected LLM client failure") from exc

        runtime_metrics.llm_call(provider, model, "failure")
        if last_error is not None:
            raise last_error
        raise LLMGatewayError("LLM request failed without a provider error")

    def _provider_config(self, provider: str) -> tuple[str, str, str]:
        return (
            self.settings.deepseek_api_key,
            self._chat_completions_url(self.settings.deepseek_base_url),
            self.settings.llm_model or DEFAULT_MODELS["deepseek"],
        )

    def _chat_completions_url(self, base_url: str) -> str:
        base_url = base_url.rstrip("/")
        if base_url.endswith("/chat/completions"):
            return base_url
        return base_url + "/chat/completions"

    def debug_config(self) -> dict[str, Any]:
        provider = (self.settings.llm_provider or "").lower().strip()
        endpoint = ""
        model = ""
        api_key_exists = False
        if provider == "deepseek":
            api_key, endpoint, model = self._provider_config(provider)
            api_key_exists = bool(api_key)
        return {
            "llm_provider": provider,
            "llm_model": self.settings.llm_model,
            "active_endpoint": endpoint,
            "active_model": model,
            "api_key_exists": api_key_exists,
        }

    def _log_config(self, provider: str, endpoint: str, model: str, api_key_exists: bool) -> None:
        logger.info("llm config loaded", extra={"event": "llm_config_loaded", "provider": provider,
                    "model": model, "outcome": "configured" if api_key_exists else "missing_key"})

    def _post_json(self, endpoint: str, api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": "Bearer {}".format(api_key),
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise LLMResponseFormatError("LLM response is not valid JSON") from exc
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            message = "LLM {} (HTTP {}): {}".format(self._http_error_reason(exc.code), exc.code, detail[:1000])
            if exc.code in {400}:
                raise LLMBadRequestError(message) from exc
            if exc.code in {401, 403}:
                raise LLMAuthError(message) from exc
            if exc.code in {429, 502, 503, 504}:
                raise LLMTransientError(message) from exc
            if exc.code >= 500:
                raise LLMTransientError(message) from exc
            raise LLMGatewayError(message) from exc
        except URLError as exc:
            raise LLMTransientError("LLM url error: {}".format(exc.reason)) from exc
        except TimeoutError as exc:
            raise LLMTransientError("LLM request timeout") from exc
        except socket.timeout as exc:
            raise LLMTransientError("LLM request timeout") from exc

    def _http_error_reason(self, status_code: int) -> str:
        if status_code in {401, 403}:
            return "unauthorized"
        if status_code == 404:
            return "url error or model not found"
        if status_code == 429:
            return "rate limited"
        if status_code >= 500:
            return "provider server error"
        return "http error"

    def _extract_content(self, data: dict[str, Any]) -> str:
        if not isinstance(data, dict):
            raise LLMResponseFormatError("LLM response format error: expected object")
        choices = data.get("choices") or []
        if not choices or not isinstance(choices[0], dict):
            raise LLMResponseFormatError("LLM response format error: no choices")
        if choices[0].get("finish_reason") == "length":
            raise LLMResponseFormatError("LLM output truncated at token limit")
        content = choices[0].get("message", {}).get("content", "")
        if isinstance(content, list):
            return "\n".join(str(item.get("text", item)) for item in content)
        content_text = str(content or "")
        if not content_text:
            raise LLMResponseFormatError("LLM response format error: empty message content")
        return content_text
