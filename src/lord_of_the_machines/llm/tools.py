from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from lord_of_the_machines.llm.config import ReplyConfig
from lord_of_the_machines.llm.replies import AgentToolCall, AgentToolResult
from lord_of_the_machines.llm.tool_definitions import (
    ToolDefinition,
    tool_definitions_to_mappings,
)


ToolHandler = Callable[[dict[str, Any]], Any]


def validate_tool_definition(tool: ToolDefinition) -> ToolDefinition:
    if not isinstance(tool, ToolDefinition):
        raise TypeError("BaseAgent tools must be ToolDefinition instances.")
    if not isinstance(tool.name, str) or not tool.name:
        raise ValueError("Tool definition requires a non-empty string name.")
    methods = tool.methods
    if not isinstance(methods, list) or not methods:
        raise ValueError("Tool definition requires a non-empty methods list.")
    for method in methods:
        if not isinstance(method.name, str) or not method.name:
            raise ValueError("Each tool method requires a non-empty string name.")
    return copy.deepcopy(tool)


def tools_for_prompt(
    agent_tools: list[ToolDefinition],
    *,
    reply: ReplyConfig,
    disabled_tools: set[str] | None = None,
) -> list[dict[str, Any]]:
    disabled_tools = disabled_tools or set()
    tools = [
        copy.deepcopy(tool)
        for tool in agent_tools
        if tool.name not in disabled_tools
    ]
    tool_mappings = tool_definitions_to_mappings(tools)
    language_note = (
        f" Output language requirement: all {reply.tool}.{reply.method} "
        f"arguments.{reply.message_argument} values must be written in {reply.output_language}."
    )

    for tool in tool_mappings:
        if tool.get("name") != reply.tool:
            continue
        tool["description"] = f"{tool.get('description', '').rstrip()}{language_note}"
        for method in tool.get("methods", []):
            if method.get("name") != reply.method:
                continue
            method["description"] = f"{method.get('description', '').rstrip()}{language_note}"
            schema = method.get("arguments_schema") or {}
            message_property = schema.get("properties", {}).get(reply.message_argument)
            if isinstance(message_property, dict):
                message_property["description"] = (
                    f"{message_property.get('description', '').rstrip()} "
                    f"Must be written in {reply.output_language}."
                )
    return tool_mappings


def single_round_tool_names(agent_tools: list[ToolDefinition], tool_calls: list[AgentToolCall]) -> set[str]:
    single_round_tools = {
        tool.name
        for tool in agent_tools
        if tool.single_round is True
    }
    return {
        tool_call.tool
        for tool_call in tool_calls
        if tool_call.tool in single_round_tools
    }


def should_return_after_tool_results(
    tool_results: list[AgentToolResult],
    return_tool_names: set[str] | None,
) -> bool:
    if return_tool_names is None:
        return True
    return any(tool_result.tool in return_tool_names for tool_result in tool_results)


class ToolExecutor:
    def __init__(
        self,
        *,
        logger: Any,
        log_id: Callable[[], str],
        tool_call_for_log: Callable[[AgentToolCall], dict[str, Any]],
        tool_result_for_log: Callable[[AgentToolResult], dict[str, Any]],
        log_json: Callable[..., None],
    ):
        self._handlers: dict[tuple[str, str], ToolHandler] = {}
        self._logger = logger
        self._log_id = log_id
        self._tool_call_for_log = tool_call_for_log
        self._tool_result_for_log = tool_result_for_log
        self._log_json = log_json

    def register(self, tool_name: str, method_name: str, handler: ToolHandler) -> None:
        if not callable(handler):
            raise TypeError("Tool handler must be callable.")
        self._handlers[(tool_name, method_name)] = handler

    def remove_tool(self, tool_name: str) -> None:
        for key in list(self._handlers):
            if key[0] == tool_name:
                del self._handlers[key]

    def execute(self, tool_calls: list[AgentToolCall]) -> list[AgentToolResult]:
        results = []
        for tool_call in tool_calls:
            handler = self._handlers.get((tool_call.tool, tool_call.method))
            if not handler:
                continue
            self._log_json(
                self._logger,
                "base_agent.tool_call.start",
                {"agent_id": self._log_id(), "tool_call": self._tool_call_for_log(tool_call)},
            )
            try:
                result = handler(copy.deepcopy(tool_call.arguments))
            except Exception as exc:  # pragma: no cover - defensive guard for user handlers.
                tool_result = AgentToolResult(
                    tool=tool_call.tool,
                    method=tool_call.method,
                    ok=False,
                    error=str(exc),
                    call_id=tool_call.call_id,
                )
                results.append(tool_result)
                self._log_json(
                    self._logger,
                    "base_agent.tool_call.error",
                    {"agent_id": self._log_id(), "tool_result": self._tool_result_for_log(tool_result)},
                )
                continue

            tool_result = AgentToolResult(
                tool=tool_call.tool,
                method=tool_call.method,
                ok=True,
                result=result,
                call_id=tool_call.call_id,
            )
            results.append(tool_result)
            self._log_json(
                self._logger,
                "base_agent.tool_call.finish",
                {"agent_id": self._log_id(), "tool_result": self._tool_result_for_log(tool_result)},
            )
        return results
