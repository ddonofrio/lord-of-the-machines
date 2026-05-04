from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

from lord_of_the_machines.llm.config import BaseAgentConfig
from lord_of_the_machines.llm.errors import AgentContextBudgetError, AgentProtocolError, MissingApiKeyError
from lord_of_the_machines.llm.history import HistoryManager
from lord_of_the_machines.llm.log_views import (
    config_for_log,
    payload_for_log,
    rate_limit_reservation_for_log,
    reply_for_log,
    response_for_log,
    summarize_for_log,
    tool_call_for_log,
    tool_result_for_log,
)
from lord_of_the_machines.llm.memory import forget, recall, remember
from lord_of_the_machines.llm.payload import AgentPayloadBuilder
from lord_of_the_machines.llm.parser import AgentOutputParser
from lord_of_the_machines.llm.prompt_cache import PromptCacheManager
from lord_of_the_machines.llm.protocol_messages import build_repair_message, build_tool_results_message
from lord_of_the_machines.llm.providers import get_provider_adapter
from lord_of_the_machines.llm.rate_limit import TokenRateLimiter
from lord_of_the_machines.llm.replies import AgentReply, AgentToolCall, AgentToolResult
from lord_of_the_machines.llm.tool_definitions import ToolDefinition
from lord_of_the_machines.llm.tokens import TokenCounter, estimate_response_tokens
from lord_of_the_machines.llm.tools import (
    ToolExecutor,
    ToolHandler,
    should_return_after_tool_results,
    single_round_tool_names,
    validate_tool_definition,
)
from lord_of_the_machines.llm.transport import (
    DEFAULT_RATE_LIMITER,
    ResponseTransport,
    resolve_rate_limiter,
)
from lord_of_the_machines.runtime.logging import get_logger, log_json


class BaseAgent:
    def __init__(
        self,
        config: BaseAgentConfig | None = None,
        *,
        client: Any | None = None,
        rate_limiter: TokenRateLimiter | None | object = DEFAULT_RATE_LIMITER,
    ):
        self.config = config or BaseAgentConfig.from_file()
        self.last_response_id: str | None = None
        self._logger = get_logger("agents.base_agent")
        self._provider = get_provider_adapter(self.config.model.provider)
        if not self._provider.supports_tool_calling_mode(self.config.tool_calling.mode):
            raise ValueError(
                f"Provider '{self.config.model.provider}' does not support tool_calling.mode='{self.config.tool_calling.mode}'."
            )
        self._token_counter = TokenCounter(
            model=self.config.model.effective_name(),
            encoding_name=self.config.context.token_counter_encoding,
            fallback_chars_per_token=self.config.context.fallback_chars_per_token,
        )
        self._client = client or self._make_provider_client()
        self._rate_limiter = resolve_rate_limiter(self.config, rate_limiter)
        self._history = HistoryManager(
            config=self.config,
            token_counter=self._token_counter,
            logger=self._logger,
            log_id=self._log_id,
            summarize_for_log=self._message_for_log,
            log_json=log_json,
        )
        self._prompt_cache = PromptCacheManager(self.config)
        self._payloads = AgentPayloadBuilder(
            config=self.config,
            provider=self._provider,
            history=self._history,
            prompt_cache=self._prompt_cache,
        )
        self._tools = ToolExecutor(
            logger=self._logger,
            log_id=self._log_id,
            tool_call_for_log=tool_call_for_log,
            tool_result_for_log=tool_result_for_log,
            log_json=log_json,
        )
        self._transport = ResponseTransport(
            config=self.config,
            client=self._client,
            token_counter=self._token_counter,
            rate_limiter=self._rate_limiter,
            logger=self._logger,
            log_id=self._log_id,
            payload_for_log=payload_for_log,
            response_for_log=lambda response: response_for_log(response, extract_text_fn=self._provider.extract_text),
            rate_limit_reservation_for_log=rate_limit_reservation_for_log,
            log_json=log_json,
            provider=self._provider,
        )
        log_json(
            self._logger,
            "base_agent.init",
            {
                "agent_id": self._log_id(),
                "config": config_for_log(self.config),
                "client_type": type(self._client).__name__,
            },
        )
        self._install_builtin_tool_handlers()

    @classmethod
    def new(cls, config_path: str | Path | None = None, **kwargs: Any) -> BaseAgent:
        client = kwargs.pop("client", None)
        rate_limiter = kwargs.pop("rate_limiter", DEFAULT_RATE_LIMITER)
        return cls(BaseAgentConfig.from_file(config_path, **kwargs), client=client, rate_limiter=rate_limiter)

    @property
    def system_prompt(self) -> str | None:
        return self.config.system_prompt

    @system_prompt.setter
    def system_prompt(self, value: str | None) -> None:
        self.set_system_prompt(value)

    def get_system_prompt(self) -> str | None:
        return self.config.system_prompt

    def set_system_prompt(self, value: str | None) -> None:
        self.config.system_prompt = value.strip() if isinstance(value, str) and value.strip() else None

    @property
    def output_language(self) -> str:
        return self.config.reply.output_language

    @output_language.setter
    def output_language(self, value: str) -> None:
        self.set_output_language(value)

    def get_output_language(self) -> str:
        return self.config.reply.output_language

    def set_output_language(self, value: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("output_language must be a non-empty string.")
        self.config.reply.output_language = value.strip()

    def list_tools(self) -> list[ToolDefinition]:
        return copy.deepcopy(self.config.agent_tools)

    def add_tool(self, tool: ToolDefinition, handlers: dict[str, ToolHandler] | None = None) -> None:
        tool_definition = validate_tool_definition(tool)
        tool_name = tool_definition.name
        self.remove_tool(tool_name)
        self.config.agent_tools.append(tool_definition)
        log_json(
            self._logger,
            "base_agent.add_tool",
            {
                "agent_id": self._log_id(),
                "tool": tool_definition,
                "handler_methods": sorted((handlers or {}).keys()),
            },
        )
        for method_name, handler in (handlers or {}).items():
            self.register_tool_handler(tool_name, method_name, handler)

    def remove_tool(self, tool_name: str) -> None:
        self.config.agent_tools = [tool for tool in self.config.agent_tools if tool.name != tool_name]
        self._tools.remove_tool(tool_name)

    def register_tool_handler(self, tool_name: str, method_name: str, handler: ToolHandler) -> None:
        self._tools.register(tool_name, method_name, handler)

    def get_history(self) -> list[dict[str, Any]]:
        return self._history.get()

    def clear_history(self) -> None:
        self._history.clear()

    def add_history(self, role: str, content: Any) -> None:
        self._history.add(role, content)

    def query(
        self,
        message: str | list[dict[str, Any]] | dict[str, Any],
        *,
        continue_previous: bool = False,
        repair_attempts: int | None = None,
        max_tool_rounds: int | None = None,
        return_after_tool_results: bool = False,
        return_after_tool_names: set[str] | list[str] | tuple[str, ...] | None = None,
        disabled_tools: set[str] | list[str] | tuple[str, ...] | None = None,
        **overrides: Any,
    ) -> AgentReply:
        log_json(
            self._logger,
            "base_agent.query.start",
            {
                "agent_id": self._log_id(),
                "message": self._message_for_log(message),
                "continue_previous": continue_previous,
                "repair_attempts": repair_attempts,
                "max_tool_rounds": max_tool_rounds,
                "return_after_tool_results": return_after_tool_results,
                "return_after_tool_names": list(return_after_tool_names or []),
                "disabled_tools": list(disabled_tools or []),
                "overrides": self._overrides_for_log(overrides),
                "history_size": len(self._history.get()),
            },
        )
        remaining_tool_rounds = self.config.max_tool_rounds if max_tool_rounds is None else max_tool_rounds
        if remaining_tool_rounds < 0:
            raise ValueError("max_tool_rounds cannot be negative.")

        disabled_tool_names = set(disabled_tools or ())
        return_tool_names = set(return_after_tool_names) if return_after_tool_names is not None else None
        payload = self._build_payload(
            message,
            continue_previous=continue_previous,
            overrides=overrides,
            disabled_tools=disabled_tool_names,
        )
        reply = self._send_reply(
            payload,
            current_message=message,
            original_message=message,
            repair_attempts=repair_attempts,
            overrides=overrides,
            disabled_tools=disabled_tool_names,
        )

        all_tool_results: list[AgentToolResult] = []
        while True:
            tool_results = self._tools.execute(reply.tool_calls)
            all_tool_results.extend(tool_results)
            reply.tool_results = list(all_tool_results)
            disabled_tool_names.update(single_round_tool_names(self.config.agent_tools, reply.tool_calls))

            if tool_results and return_after_tool_results and should_return_after_tool_results(tool_results, return_tool_names):
                log_json(
                    self._logger,
                    "base_agent.query.return_after_tool_results",
                    {"agent_id": self._log_id(), "reply": reply_for_log(reply)},
                )
                return reply

            if reply.messages or not tool_results:
                self._history.record_turn(message, reply)
                log_json(
                    self._logger,
                    "base_agent.query.finish",
                    {"agent_id": self._log_id(), "reply": reply_for_log(reply), "history_size": len(self._history.get())},
                )
                return reply

            if remaining_tool_rounds <= 0:
                raise AgentProtocolError(
                    "Maximum tool rounds reached before the agent produced a reply.",
                    last_output=reply.text,
                    last_response=reply.raw_response,
                )

            remaining_tool_rounds -= 1
            if self._provider.uses_native_tool_calling(self.config):
                payload = self._build_native_tool_results_payload(
                    tool_results,
                    previous_response_id=reply.response_id,
                    overrides=overrides,
                    disabled_tools=disabled_tool_names,
                )
                reply = self._request_native_tool_reply(payload)
            else:
                tool_results_message = self._build_tool_results_message(
                    original_message=message,
                    tool_results=tool_results,
                )
                payload = self._build_payload(
                    tool_results_message,
                    continue_previous=False,
                    overrides=overrides,
                    disabled_tools=disabled_tool_names,
                )
                reply = self._send_with_protocol_repair(
                    payload,
                    current_message=tool_results_message,
                    original_message=message,
                    repair_attempts=repair_attempts,
                    overrides=overrides,
                    disabled_tools=disabled_tool_names,
                )

    def _send_reply(
        self,
        payload: dict[str, Any],
        *,
        current_message: str | list[dict[str, Any]] | dict[str, Any],
        original_message: str | list[dict[str, Any]] | dict[str, Any],
        repair_attempts: int | None,
        overrides: dict[str, Any],
        disabled_tools: set[str] | None = None,
    ) -> AgentReply:
        if self._provider.uses_native_tool_calling(self.config):
            return self._request_reply(payload, current_message, overrides, disabled_tools)
        return self._send_with_protocol_repair(
            payload,
            current_message=current_message,
            original_message=original_message,
            repair_attempts=repair_attempts,
            overrides=overrides,
            disabled_tools=disabled_tools,
        )

    def _send_with_protocol_repair(
        self,
        payload: dict[str, Any],
        *,
        current_message: str | list[dict[str, Any]] | dict[str, Any],
        original_message: str | list[dict[str, Any]] | dict[str, Any],
        repair_attempts: int | None,
        overrides: dict[str, Any],
        disabled_tools: set[str] | None = None,
    ) -> AgentReply:
        remaining_repairs = self.config.output_repair_attempts if repair_attempts is None else repair_attempts
        if remaining_repairs < 0:
            raise ValueError("repair_attempts cannot be negative.")

        reply = self._request_reply(payload, current_message, overrides, disabled_tools)
        while self.config.envelope.enabled and reply.parse_error and remaining_repairs > 0:
            remaining_repairs -= 1
            log_json(
                self._logger,
                "base_agent.protocol_repair",
                {
                    "agent_id": self._log_id(),
                    "remaining_repairs": remaining_repairs,
                    "parse_error": reply.parse_error,
                    "invalid_output": reply.text,
                },
            )
            repair_message = self._build_repair_message(
                original_message=original_message,
                invalid_output=reply.text,
                parsing_error=reply.parse_error,
                disabled_tools=disabled_tools,
            )
            repair_payload = self._build_payload(
                repair_message,
                continue_previous=False,
                overrides=overrides,
                disabled_tools=disabled_tools,
            )
            reply = self._request_reply(repair_payload, repair_message, overrides, disabled_tools)

        if self.config.envelope.enabled and reply.parse_error:
            raise AgentProtocolError(reply.parse_error, last_output=reply.text, last_response=reply.raw_response)
        return reply

    def _request_reply(
        self,
        payload: dict[str, Any],
        message: str | list[dict[str, Any]] | dict[str, Any],
        overrides: dict[str, Any],
        disabled_tools: set[str] | None,
    ) -> AgentReply:
        response = self._transport.create_with_context_retry(
            payload,
            message=message,
            continue_previous=False,
            overrides=overrides,
            disabled_tools=disabled_tools,
            build_payload=self._build_payload,
        )
        reply = self._make_reply(response)
        if reply.response_id:
            self.last_response_id = reply.response_id
        return reply

    def _build_payload(
        self,
        message: str | list[dict[str, Any]] | dict[str, Any],
        *,
        continue_previous: bool,
        overrides: dict[str, Any],
        history_token_budget: int | None = None,
        disabled_tools: set[str] | None = None,
    ) -> dict[str, Any]:
        return self._payloads.build(
            message,
            continue_previous=continue_previous,
            overrides=overrides,
            last_response_id=self.last_response_id,
            history_token_budget=history_token_budget,
            disabled_tools=disabled_tools,
        )

    def _build_native_tool_results_payload(
        self,
        tool_results: list[AgentToolResult],
        *,
        previous_response_id: str | None,
        overrides: dict[str, Any],
        disabled_tools: set[str] | None = None,
    ) -> dict[str, Any]:
        if not previous_response_id:
            raise AgentProtocolError("Native tool calling requires a previous response id for tool result continuation.")
        return self._payloads.build_native_tool_result_payload(
            tool_results,
            previous_response_id=previous_response_id,
            overrides=overrides,
            disabled_tools=disabled_tools,
        )

    def _build_repair_message(
        self,
        *,
        original_message: str | list[dict[str, Any]] | dict[str, Any],
        invalid_output: str,
        parsing_error: str,
        disabled_tools: set[str] | None = None,
    ) -> dict[str, Any]:
        return build_repair_message(
            config=self.config,
            original_message=original_message,
            invalid_output=invalid_output,
            parsing_error=parsing_error,
            available_tools=self._tools_for_prompt(disabled_tools=disabled_tools),
        )

    def _build_tool_results_message(
        self,
        *,
        original_message: str | list[dict[str, Any]] | dict[str, Any],
        tool_results: list[AgentToolResult],
    ) -> dict[str, Any]:
        return build_tool_results_message(
            config=self.config,
            original_message=original_message,
            tool_results=tool_results,
        )

    def _tools_for_prompt(self, *, disabled_tools: set[str] | None = None) -> list[dict[str, Any]]:
        return self._payloads.tools_for_prompt(disabled_tools=disabled_tools)

    def _make_reply(self, response: Any) -> AgentReply:
        text = self._provider.extract_text(response)
        tool_calls: list[AgentToolCall] = []
        parse_error: str | None = None
        if self._provider.uses_native_tool_calling(self.config):
            tool_calls, parse_error = self._provider.parse_native_tool_calls(
                response,
                agent_tools=self.config.agent_tools,
                config=self.config,
            )
        elif self.config.envelope.enabled:
            parser = AgentOutputParser(output_spec=self.config.envelope.output, agent_tools=self.config.agent_tools)
            tool_calls, parse_error = parser.parse_text(text)
        reply = AgentReply(
            text=text,
            tool_calls=tool_calls,
            parse_error=parse_error,
            response_id=getattr(response, "id", None),
            status=getattr(response, "status", None),
            usage=getattr(response, "usage", None),
            raw_response=response,
            reply_tool=self.config.reply.tool,
            reply_method=self.config.reply.method,
            reply_message_argument=self.config.reply.message_argument,
        )
        log_json(self._logger, "base_agent.reply.parsed", {"agent_id": self._log_id(), "reply": reply_for_log(reply)})
        return reply

    def _request_native_tool_reply(self, payload: dict[str, Any]) -> AgentReply:
        event_prefix = f"{self.config.model.provider}.responses.create.native_tool_results"
        response = self._transport.create_with_request_retries(
            payload,
            request_event=f"{event_prefix}.request",
            response_event=f"{event_prefix}.response",
            error_event=f"{event_prefix}.error",
            rate_limit_event=f"{event_prefix}.rate_limit_retry",
            verbosity_event=f"{event_prefix}.verbosity_retry",
        )
        reply = self._make_reply(response)
        if reply.response_id:
            self.last_response_id = reply.response_id
        return reply

    def _install_builtin_tool_handlers(self) -> None:
        self.register_tool_handler("memory", "remember", self._memory_remember)
        self.register_tool_handler("memory", "recall", self._memory_recall)
        self.register_tool_handler("memory", "forget", self._memory_forget)

    def _memory_remember(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.config.memory, result = remember(self.config.memory, arguments)
        return result

    def _memory_recall(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return recall(self.config.memory, arguments)

    def _memory_forget(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.config.memory, result = forget(self.config.memory, arguments)
        return result

    def _request_token_estimate(self, payload: dict[str, Any]) -> dict[str, Any]:
        return estimate_response_tokens(payload, self._token_counter)

    def _message_for_log(self, value: Any) -> Any:
        return summarize_for_log(value, long_text=220)

    def _overrides_for_log(self, value: Any) -> Any:
        return summarize_for_log(value, long_text=120)

    def _log_id(self) -> str:
        return hex(id(self))

    def _make_provider_client(self) -> Any:
        api_key = os.getenv(self.config.model.api_key_env)
        if not api_key:
            raise MissingApiKeyError(f"Missing {self.config.model.api_key_env}.")
        return self._provider.build_client(api_key=api_key)


__all__ = [
    "AgentContextBudgetError",
    "AgentProtocolError",
    "AgentReply",
    "AgentToolCall",
    "AgentToolResult",
    "BaseAgent",
    "BaseAgentConfig",
    "MissingApiKeyError",
    "TokenRateLimiter",
]
