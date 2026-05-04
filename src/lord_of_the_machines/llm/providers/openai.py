from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

from lord_of_the_machines.llm.config import BaseAgentConfig
from lord_of_the_machines.llm.replies import AgentToolCall, AgentToolResult
from lord_of_the_machines.llm.schema import normalize_strict_json_schema
from lord_of_the_machines.llm.tool_definitions import ToolDefinition


NATIVE_TOOL_CALLING_MODE = "openai_native"
PROTOCOL_TOOL_CALLING_MODE = "protocol"
FUNCTION_NAME_LIMIT = 64
FUNCTION_NAME_SAFE_RE = re.compile(r"[^a-zA-Z0-9_-]+")
RATE_LIMIT_WAIT_RE = re.compile(r"try again in\s+([0-9]+(?:\.[0-9]+)?)s", re.IGNORECASE)
RATE_LIMIT_BUDGET_RE = re.compile(
    r"limit\s+([0-9]+)\s*,\s*used\s+([0-9]+)\s*,\s*requested\s+([0-9]+)",
    re.IGNORECASE,
)
UNSUPPORTED_VERBOSITY_RE = re.compile(
    r"Unsupported value:\s*'(?P<current>[^']+)'\s+is not supported with the\s+'(?P<model>[^']+)'\s+model\.\s+Supported values are:\s+'(?P<supported>[^']+)'",
    re.IGNORECASE,
)


class OpenAIProviderAdapter:
    provider_name = "openai"

    def supports_tool_calling_mode(self, mode: str) -> bool:
        return mode in {PROTOCOL_TOOL_CALLING_MODE, NATIVE_TOOL_CALLING_MODE}

    def build_client(self, *, api_key: str) -> Any:
        try:
            from openai import OpenAI
        except ModuleNotFoundError as exc:
            raise RuntimeError("Missing openai package. Run: python -m pip install -r requirements.txt") from exc
        return OpenAI(api_key=api_key)

    def create_response(self, client: Any, payload: dict[str, Any]) -> Any:
        return client.responses.create(**payload)

    def extract_text(self, response: Any) -> str:
        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        output = getattr(response, "output", None)
        if not isinstance(output, list):
            return ""

        parts: list[str] = []
        for item in output:
            item_type = item.get("type") if isinstance(item, dict) else getattr(item, "type", None)
            if item_type != "message":
                continue
            content = item.get("content") if isinstance(item, dict) else getattr(item, "content", None)
            if not isinstance(content, list):
                continue
            for block in content:
                block_type = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
                if block_type == "output_text":
                    text = block.get("text") if isinstance(block, dict) else getattr(block, "text", None)
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
        return "\n".join(parts).strip()

    def uses_native_tool_calling(self, config: BaseAgentConfig) -> bool:
        return config.tool_calling.mode == NATIVE_TOOL_CALLING_MODE

    def build_native_tools(self, agent_tools: list[ToolDefinition], *, config: BaseAgentConfig) -> list[dict[str, Any]]:
        mappings = self._build_function_name_map(agent_tools, name_separator=config.tool_calling.native_name_separator)
        native_tools = []
        for tool in agent_tools:
            tool_name = tool.name
            if not tool_name:
                continue
            tool_description = str(tool.description or "").strip()
            for method in tool.methods:
                method_name = method.name
                if not method_name:
                    continue
                arguments_schema = normalize_strict_json_schema(
                    method.arguments_schema
                    or {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {},
                        "required": [],
                    }
                )
                function_name = mappings[(str(tool_name), str(method_name))]
                description_parts = [part for part in [tool_description, method.description] if isinstance(part, str) and part.strip()]
                native_tools.append(
                    {
                        "type": "function",
                        "name": function_name,
                        "description": " ".join(part.strip() for part in description_parts),
                        "parameters": arguments_schema,
                        "strict": True,
                    }
                )
        return native_tools

    def parse_native_tool_calls(
        self,
        response: Any,
        *,
        agent_tools: list[ToolDefinition],
        config: BaseAgentConfig,
    ) -> tuple[list[AgentToolCall], str | None]:
        output_items = self._response_output_items(response)
        if not output_items:
            return [], None

        reverse_map = {
            function_name: tool_method
            for tool_method, function_name in self._build_function_name_map(
                agent_tools,
                name_separator=config.tool_calling.native_name_separator,
            ).items()
        }
        tool_calls: list[AgentToolCall] = []
        for index, item in enumerate(output_items):
            if self._item_value(item, "type") != "function_call":
                continue

            function_name = self._item_value(item, "name")
            if not isinstance(function_name, str) or not function_name:
                return [], f"Native tool call #{index + 1} is missing a function name."
            tool_method = reverse_map.get(function_name)
            if tool_method is None:
                return [], f"Native tool call #{index + 1} uses unknown function '{function_name}'."

            raw_arguments = self._item_value(item, "arguments")
            if isinstance(raw_arguments, str):
                try:
                    arguments = json.loads(raw_arguments)
                except json.JSONDecodeError as exc:
                    return [], f"Invalid native tool arguments for '{function_name}' at line {exc.lineno}, column {exc.colno}: {exc.msg}."
            elif isinstance(raw_arguments, dict):
                arguments = copy.deepcopy(raw_arguments)
            elif raw_arguments is None:
                arguments = {}
            else:
                return [], f"Native tool call '{function_name}' returned unsupported arguments type {type(raw_arguments).__name__}."

            if not isinstance(arguments, dict):
                return [], f"Native tool call '{function_name}' arguments must decode to an object."

            tool_name, method_name = tool_method
            tool_calls.append(
                AgentToolCall(
                    tool=tool_name,
                    method=method_name,
                    arguments=arguments,
                    raw={
                        "type": "function_call",
                        "name": function_name,
                        "arguments": copy.deepcopy(arguments),
                        "call_id": self._item_value(item, "call_id"),
                        "id": self._item_value(item, "id"),
                    },
                    call_id=self._item_value(item, "call_id"),
                )
            )

        return tool_calls, None

    def build_tool_result_items(self, tool_results: list[AgentToolResult], *, config: BaseAgentConfig) -> list[dict[str, Any]]:
        del config
        items = []
        for tool_result in tool_results:
            if not tool_result.call_id:
                continue
            output_payload = {
                "ok": tool_result.ok,
                "tool": tool_result.tool,
                "method": tool_result.method,
                "result": tool_result.result,
                "error": tool_result.error,
            }
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": tool_result.call_id,
                    "output": json.dumps(output_payload, ensure_ascii=False, default=repr),
                }
            )
        return items

    def build_native_tool_instructions(self, config: BaseAgentConfig) -> str:
        lines = []
        if config.envelope.enabled:
            lines.append(
                "Tool calling mode:\n"
                "Provider-native function calling is enabled. You will receive the current request context in a JSON protocol envelope."
            )
        else:
            lines.append(
                "Tool calling mode:\n"
                "Provider-native function calling is enabled."
            )
        lines.append(
            "When you need a tool, call it using native function calling instead of returning a JSON tool-call object."
        )
        lines.append(
            f"When you have enough information for the caller, you may either call {config.reply.tool}.{config.reply.method} "
            "or return plain text directly."
        )
        return "\n\n".join(lines)

    def adapt_envelope(self, envelope: dict[str, Any], *, config: BaseAgentConfig) -> None:
        runtime_context_field = self._field_name_for_source(config, "runtime_context")
        output_contract_field = self._field_name_for_source(config, "output_contract")

        if not config.tool_calling.include_tools_in_envelope and runtime_context_field:
            runtime_context = envelope.get(runtime_context_field)
            if isinstance(runtime_context, dict):
                runtime_context.pop("available_tools", None)
                runtime_context["tool_calling"] = {"mode": config.tool_calling.mode}

        if not config.tool_calling.include_output_contract_in_envelope and output_contract_field:
            envelope.pop(output_contract_field, None)

    def is_context_window_error(self, exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        message = str(exc).lower()
        if status_code is not None and status_code != 400:
            return False
        return "context" in message and ("token" in message or "length" in message or "window" in message)

    def is_rate_limit_error(self, exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        if status_code == 429:
            return True
        message = str(exc).lower()
        return "rate limit" in message or "rate_limit_exceeded" in message or "tokens per min" in message

    def rate_limit_wait_seconds(self, exc: Exception, *, attempt: int, config: BaseAgentConfig) -> float:
        header_wait = self._retry_after_header_seconds(exc)
        if header_wait is not None:
            return max(0.0, header_wait)
        match = RATE_LIMIT_WAIT_RE.search(str(exc))
        if match:
            return max(0.0, float(match.group(1)) + 0.1)
        return float(config.transport.rate_limit_backoff_seconds) * (2**attempt)

    def rate_limit_budget(self, exc: Exception) -> dict[str, int] | None:
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

    def payload_with_supported_verbosity(
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

    def _build_function_name_map(
        self,
        agent_tools: list[ToolDefinition],
        *,
        name_separator: str,
    ) -> dict[tuple[str, str], str]:
        result: dict[tuple[str, str], str] = {}
        used_names: dict[str, tuple[str, str]] = {}
        for tool in agent_tools:
            tool_name = tool.name
            if not isinstance(tool_name, str) or not tool_name:
                continue
            for method in tool.methods:
                method_name = method.name
                if not isinstance(method_name, str) or not method_name:
                    continue
                raw_name = f"{tool_name}{name_separator}{method_name}"
                function_name = self._normalize_function_name(raw_name)
                if function_name in used_names and used_names[function_name] != (tool_name, method_name):
                    raise ValueError(
                        f"Native tool name collision for '{tool_name}.{method_name}' and "
                        f"'{used_names[function_name][0]}.{used_names[function_name][1]}'."
                    )
                used_names[function_name] = (tool_name, method_name)
                result[(tool_name, method_name)] = function_name
        return result

    @staticmethod
    def _normalize_function_name(value: str) -> str:
        safe = FUNCTION_NAME_SAFE_RE.sub("_", value).strip("_")
        if not safe:
            safe = "tool_call"
        if len(safe) <= FUNCTION_NAME_LIMIT:
            return safe
        digest = hashlib.sha1(safe.encode("utf-8")).hexdigest()[:12]
        prefix = safe[: max(1, FUNCTION_NAME_LIMIT - len(digest) - 1)]
        return f"{prefix}_{digest}"[:FUNCTION_NAME_LIMIT]

    @staticmethod
    def _response_output_items(response: Any) -> list[Any]:
        output = getattr(response, "output", None)
        if isinstance(output, list):
            return output
        if isinstance(response, dict):
            output = response.get("output")
            if isinstance(output, list):
                return output
        return []

    @staticmethod
    def _item_value(item: Any, name: str) -> Any:
        if isinstance(item, dict):
            return item.get(name)
        return getattr(item, name, None)

    @staticmethod
    def _field_name_for_source(config: BaseAgentConfig, source: str) -> str | None:
        for field in config.envelope.input_fields:
            if field.source == source:
                return field.name
        return None
