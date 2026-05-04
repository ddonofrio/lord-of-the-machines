from __future__ import annotations

import copy
import json
from typing import Any

from lord_of_the_machines.llm.envelope import ToolCallOutputSpec
from lord_of_the_machines.llm.replies import AgentToolCall
from lord_of_the_machines.llm.tool_definitions import ToolDefinition, ToolMethodDefinition


class AgentOutputParser:
    def __init__(self, *, output_spec: ToolCallOutputSpec, agent_tools: list[ToolDefinition]):
        self.output_spec = output_spec
        self.agent_tools = agent_tools

    def parse_text(self, text: str) -> tuple[list[AgentToolCall], str | None]:
        if not text:
            return [], "Empty model output; expected a JSON object with a tool call list."
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            return [], f"Invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}."
        return self.validate(parsed)

    def validate(self, parsed: Any) -> tuple[list[AgentToolCall], str | None]:
        output = self.output_spec
        if isinstance(parsed, dict):
            extra = sorted(set(parsed) - {output.calls_field})
            if extra:
                return [], f"Invalid JSON root field(s): {', '.join(extra)}; expected only {output.calls_field}."
            if output.calls_field not in parsed:
                return [], f"Invalid JSON object; missing required field: {output.calls_field}."
            calls = parsed[output.calls_field]
        elif isinstance(parsed, list) and output.allow_root_list:
            calls = parsed
        else:
            return [], f"Invalid JSON root type {type(parsed).__name__}; expected object with {output.calls_field} array."

        if not isinstance(calls, list):
            return [], f"Invalid {output.calls_field} type {type(calls).__name__}; expected array."
        if len(calls) < output.min_calls:
            return [], f"Tool call list must contain at least {output.min_calls} item(s)."

        tool_calls: list[AgentToolCall] = []
        required_fields = set(output.call_required_fields())
        for index, item in enumerate(calls):
            prefix = f"Tool call #{index + 1}"
            if not isinstance(item, dict):
                return [], f"{prefix} must be an object."

            missing = sorted(required_fields - set(item))
            if missing:
                return [], f"{prefix} missing required field(s): {', '.join(missing)}."

            extra = sorted(set(item) - required_fields)
            if extra:
                return [], f"{prefix} has unexpected field(s): {', '.join(extra)}."

            tool = item[output.tool_field]
            method = item[output.method_field]
            arguments = item[output.arguments_field]
            if not isinstance(tool, str):
                return [], f"{prefix} field '{output.tool_field}' must be a string."
            if not isinstance(method, str):
                return [], f"{prefix} field '{output.method_field}' must be a string."
            if not isinstance(arguments, dict):
                return [], f"{prefix} field '{output.arguments_field}' must be an object."

            method_definition = self._method_definition(tool, method)
            if method_definition is None:
                allowed = self._allowed_tool_methods()
                if tool not in allowed:
                    return [], f"{prefix} uses unknown tool '{tool}'. Allowed tools: {', '.join(sorted(allowed))}."
                return (
                    [],
                    (
                        f"{prefix} uses unknown method '{method}' for tool '{tool}'. "
                        f"Allowed methods: {', '.join(sorted(allowed[tool]))}."
                    ),
                )

            schema_error = self._validate_arguments(arguments, method_definition.arguments_schema, prefix)
            if schema_error:
                return [], schema_error

            tool_calls.append(AgentToolCall(tool=tool, method=method, arguments=arguments, raw=copy.deepcopy(item)))

        return tool_calls, None

    def _method_definition(self, tool_name: str, method_name: str) -> ToolMethodDefinition | None:
        for tool in self.agent_tools:
            if tool.name != tool_name:
                continue
            method = tool.method(method_name)
            if method is not None:
                return method
        return None

    def _allowed_tool_methods(self) -> dict[str, set[str]]:
        allowed: dict[str, set[str]] = {}
        for tool in self.agent_tools:
            tool_name = tool.name
            if not isinstance(tool_name, str) or not tool_name:
                continue
            allowed[tool_name] = {
                method.name
                for method in tool.methods
                if isinstance(method.name, str) and method.name
            }
        return allowed

    def _validate_arguments(
        self,
        arguments: dict[str, Any],
        schema: dict[str, Any] | None,
        prefix: str,
    ) -> str | None:
        if not schema:
            return None

        required = schema.get("required", [])
        missing = [name for name in required if name not in arguments]
        if missing:
            return f"{prefix} arguments missing required field(s): {', '.join(missing)}."

        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = sorted(set(arguments) - set(properties))
            if extra:
                return f"{prefix} arguments have unexpected field(s): {', '.join(extra)}."

        required_set = set(required)
        for name, value in arguments.items():
            if value is None and name not in required_set:
                continue
            property_schema = properties.get(name)
            if not property_schema:
                continue
            expected_type = property_schema.get("type")
            if expected_type and not self._matches_json_type(value, expected_type):
                return f"{prefix} argument '{name}' must be {expected_type}."
        return None

    def _matches_json_type(self, value: Any, expected_type: str | list[str]) -> bool:
        if isinstance(expected_type, list):
            return any(self._matches_json_type(value, type_name) for type_name in expected_type)
        if expected_type == "string":
            return isinstance(value, str)
        if expected_type == "object":
            return isinstance(value, dict)
        if expected_type == "array":
            return isinstance(value, list)
        if expected_type == "boolean":
            return isinstance(value, bool)
        if expected_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected_type == "number":
            return isinstance(value, int | float) and not isinstance(value, bool)
        if expected_type == "null":
            return value is None
        return True
