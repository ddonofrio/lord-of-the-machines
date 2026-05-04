from __future__ import annotations

import copy
import re
import threading
import time
from collections.abc import Callable
from typing import Any

from lord_of_the_machines.llm.config import BaseAgentConfig
from lord_of_the_machines.llm.errors import AgentContextBudgetError
from lord_of_the_machines.llm.rate_limit import TokenRateLimiter, TokenRateLimitReservation
from lord_of_the_machines.llm.tokens import TokenCounter, estimate_response_tokens


RATE_LIMIT_WAIT_RE = re.compile(r"try again in\s+([0-9]+(?:\.[0-9]+)?)s", re.IGNORECASE)
RATE_LIMIT_BUDGET_RE = re.compile(
    r"limit\s+([0-9]+)\s*,\s*used\s+([0-9]+)\s*,\s*requested\s+([0-9]+)",
    re.IGNORECASE,
)
UNSUPPORTED_VERBOSITY_RE = re.compile(
    r"Unsupported value:\s*'(?P<current>[^']+)'\s+is not supported with the\s+'(?P<model>[^']+)'\s+model\.\s+Supported values are:\s+'(?P<supported>[^']+)'",
    re.IGNORECASE,
)

DEFAULT_RATE_LIMITER = object()
_SHARED_RATE_LIMITERS: dict[tuple[str, int, float, int], TokenRateLimiter] = {}
_SHARED_RATE_LIMITERS_LOCK = threading.Lock()


def resolve_rate_limiter(
    config: BaseAgentConfig,
    rate_limiter: TokenRateLimiter | None | object,
) -> TokenRateLimiter | None:
    if rate_limiter is not DEFAULT_RATE_LIMITER:
        return rate_limiter

    tokens_per_minute = config.transport.rate_limit_tokens_per_minute
    if tokens_per_minute is None or tokens_per_minute <= 0:
        return None

    key = (
        config.model.effective_name(),
        int(tokens_per_minute),
        float(config.transport.rate_limit_window_seconds),
        int(config.transport.rate_limit_safety_margin_tokens),
    )
    with _SHARED_RATE_LIMITERS_LOCK:
        limiter = _SHARED_RATE_LIMITERS.get(key)
        if limiter is None:
            limiter = TokenRateLimiter(
                tokens_per_window=int(tokens_per_minute),
                window_seconds=float(config.transport.rate_limit_window_seconds),
                safety_margin_tokens=int(config.transport.rate_limit_safety_margin_tokens),
            )
            _SHARED_RATE_LIMITERS[key] = limiter
        return limiter


class ResponseTransport:
    def __init__(
        self,
        *,
        config: BaseAgentConfig,
        client: Any,
        token_counter: TokenCounter,
        rate_limiter: TokenRateLimiter | None,
        logger: Any,
        log_id: Callable[[], str],
        payload_for_log: Callable[[dict[str, Any]], dict[str, Any]],
        response_for_log: Callable[[Any], dict[str, Any]],
        rate_limit_reservation_for_log: Callable[[TokenRateLimitReservation | None], dict[str, Any] | None],
        log_json: Callable[..., None],
    ):
        self.config = config
        self.client = client
        self.token_counter = token_counter
        self.rate_limiter = rate_limiter
        self._logger = logger
        self._log_id = log_id
        self._payload_for_log = payload_for_log
        self._response_for_log = response_for_log
        self._rate_limit_reservation_for_log = rate_limit_reservation_for_log
        self._log_json = log_json

    def create_with_context_retry(
        self,
        payload: dict[str, Any],
        *,
        message: str | list[dict[str, Any]] | dict[str, Any],
        continue_previous: bool,
        overrides: dict[str, Any],
        disabled_tools: set[str] | None,
        build_payload: Callable[..., dict[str, Any]],
    ) -> Any:
        try:
            return self.create_with_request_retries(
                payload,
                request_event="openai.responses.create.request",
                response_event="openai.responses.create.response",
                error_event="openai.responses.create.error",
                rate_limit_event="openai.responses.create.rate_limit_retry",
                verbosity_event="openai.responses.create.verbosity_retry",
            )
        except Exception as exc:
            if self.config.context.context_overflow_retries <= 0 or not self._is_context_window_error(exc):
                raise

            retry_payload = build_payload(
                message,
                continue_previous=continue_previous,
                overrides=overrides,
                history_token_budget=0,
                disabled_tools=disabled_tools,
            )
            try:
                return self.create_with_request_retries(
                    retry_payload,
                    request_event="openai.responses.create.context_retry.request",
                    response_event="openai.responses.create.context_retry.response",
                    error_event="openai.responses.create.context_retry.error",
                    rate_limit_event="openai.responses.create.context_retry.rate_limit_retry",
                    verbosity_event="openai.responses.create.context_retry.verbosity_retry",
                )
            except Exception as retry_exc:
                if self._is_context_window_error(retry_exc):
                    raise AgentContextBudgetError(
                        "The non-history prompt parts exceed the model context window. "
                        "Reduce the system prompt, memory, tools, current message, or max_output_tokens."
                    ) from retry_exc
                raise

    def create_with_request_retries(
        self,
        payload: dict[str, Any],
        *,
        request_event: str,
        response_event: str,
        error_event: str,
        rate_limit_event: str,
        verbosity_event: str,
    ) -> Any:
        current_payload = copy.deepcopy(payload)
        rate_limit_attempt = 0
        verbosity_attempt = 0

        while True:
            try:
                token_estimate = estimate_response_tokens(current_payload, self.token_counter)
                rate_limit_reservation = self._reserve_rate_limit_tokens(token_estimate)
                self._log_json(
                    self._logger,
                    request_event,
                    {
                        "agent_id": self._log_id(),
                        "rate_limit_attempt": rate_limit_attempt,
                        "verbosity_attempt": verbosity_attempt,
                        "token_estimate": token_estimate,
                        "rate_limit": self._rate_limit_reservation_for_log(rate_limit_reservation),
                        "payload": self._payload_for_log(current_payload),
                    },
                )
                response = self.client.responses.create(**current_payload)
                self._log_json(
                    self._logger,
                    response_event,
                    {"agent_id": self._log_id(), "response": self._response_for_log(response)},
                )
                return response
            except Exception as exc:
                adjusted_payload, supported_verbosity = self._payload_with_supported_verbosity(current_payload, exc)
                if adjusted_payload is not None:
                    previous_text = current_payload.get("text") or {}
                    current_text = adjusted_payload.get("text") or {}
                    verbosity_attempt += 1
                    self._log_json(
                        self._logger,
                        verbosity_event,
                        {
                            "agent_id": self._log_id(),
                            "attempt": verbosity_attempt,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                            "previous_verbosity": previous_text.get("verbosity"),
                            "new_verbosity": current_text.get("verbosity"),
                            "supported_verbosity": supported_verbosity,
                        },
                    )
                    current_payload = adjusted_payload
                    continue

                if self._is_rate_limit_error(exc) and rate_limit_attempt < self.config.transport.rate_limit_retries:
                    wait_seconds = self._rate_limit_wait_seconds(exc, attempt=rate_limit_attempt)
                    if wait_seconds <= self.config.transport.rate_limit_max_wait_seconds:
                        rate_limit_attempt += 1
                        budget = self._rate_limit_budget(exc)
                        self._log_json(
                            self._logger,
                            rate_limit_event,
                            {
                                "agent_id": self._log_id(),
                                "attempt": rate_limit_attempt,
                                "wait_seconds": wait_seconds,
                                "error_type": type(exc).__name__,
                                "error": str(exc),
                                "budget": budget,
                            },
                        )
                        time.sleep(wait_seconds)
                        continue

                self._log_json(
                    self._logger,
                    error_event,
                    {"agent_id": self._log_id(), "error_type": type(exc).__name__, "error": str(exc)},
                )
                raise

    def _reserve_rate_limit_tokens(self, token_estimate: dict[str, Any]) -> TokenRateLimitReservation | None:
        if self.rate_limiter is None:
            return None
        reservation = self.rate_limiter.reserve(int(token_estimate["total_tokens"]))
        if reservation is None:
            return None
        if reservation.wait_seconds > 0 or reservation.oversized:
            self._log_json(
                self._logger,
                "base_agent.rate_limit.preflight",
                {
                    "agent_id": self._log_id(),
                    "model": self.config.model.effective_name(),
                    "token_estimate": token_estimate,
                    "reservation": self._rate_limit_reservation_for_log(reservation),
                },
            )
        return reservation

    def _is_context_window_error(self, exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        message = str(exc).lower()
        if status_code is not None and status_code != 400:
            return False
        return "context" in message and ("token" in message or "length" in message or "window" in message)

    def _is_rate_limit_error(self, exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        if status_code == 429:
            return True
        message = str(exc).lower()
        return "rate limit" in message or "rate_limit_exceeded" in message or "tokens per min" in message

    def _rate_limit_wait_seconds(self, exc: Exception, *, attempt: int) -> float:
        header_wait = self._retry_after_header_seconds(exc)
        if header_wait is not None:
            return max(0.0, header_wait)
        match = RATE_LIMIT_WAIT_RE.search(str(exc))
        if match:
            return max(0.0, float(match.group(1)) + 0.1)
        return float(self.config.transport.rate_limit_backoff_seconds) * (2**attempt)

    @staticmethod
    def _retry_after_header_seconds(exc: Exception) -> float | None:
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
        if headers is None:
            return None
        for key in ("retry-after", "Retry-After"):
            value = headers.get(key) if hasattr(headers, "get") else None
            if value is None:
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
        return None

    @staticmethod
    def _rate_limit_budget(exc: Exception) -> dict[str, int] | None:
        match = RATE_LIMIT_BUDGET_RE.search(str(exc))
        if not match:
            return None
        limit, used, requested = (int(match.group(index)) for index in range(1, 4))
        return {
            "limit": limit,
            "used": used,
            "requested": requested,
            "remaining": max(0, limit - used),
            "excess": max(0, requested - max(0, limit - used)),
        }

    def _payload_with_supported_verbosity(
        self,
        payload: dict[str, Any],
        exc: Exception,
    ) -> tuple[dict[str, Any] | None, str | None]:
        text_config = payload.get("text")
        if not isinstance(text_config, dict):
            return None, None
        current_verbosity = text_config.get("verbosity")
        if not isinstance(current_verbosity, str):
            return None, None
        match = UNSUPPORTED_VERBOSITY_RE.search(str(exc))
        if not match:
            return None, None
        supported_verbosity = match.group("supported").strip()
        if not supported_verbosity or supported_verbosity == current_verbosity:
            return None, None
        adjusted_payload = copy.deepcopy(payload)
        adjusted_payload["text"] = copy.deepcopy(text_config)
        adjusted_payload["text"]["verbosity"] = supported_verbosity
        return adjusted_payload, supported_verbosity
