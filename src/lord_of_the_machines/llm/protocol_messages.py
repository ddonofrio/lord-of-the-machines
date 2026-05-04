from __future__ import annotations

from typing import Any

from lord_of_the_machines.llm.config import BaseAgentConfig
from lord_of_the_machines.llm.replies import AgentToolResult


def build_repair_message(
    *,
    config: BaseAgentConfig,
    original_message: str | list[dict[str, Any]] | dict[str, Any],
    invalid_output: str,
    parsing_error: str,
    available_tools: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "type": "protocol_repair_request",
        "instruction": (
            "Your previous response did not match the required agent JSON protocol. "
            "Decide what to do next using only the available tools. Return exactly "
            "one valid JSON object matching required_json_shape."
        ),
        "parser_error": parsing_error,
        "invalid_output": invalid_output,
        "original_user_prompt": original_message,
        "available_tools": available_tools,
        "required_json_shape": config.envelope.output.required_json_shape(),
    }


def build_tool_results_message(
    *,
    config: BaseAgentConfig,
    original_message: str | list[dict[str, Any]] | dict[str, Any],
    tool_results: list[AgentToolResult],
) -> dict[str, Any]:
    return {
        "type": "tool_results",
        "instruction": (
            "Use these tool results to decide your next tool call list. "
            f"If you now have enough information for the caller, call {config.reply.tool}.{config.reply.method}."
        ),
        "original_user_prompt": original_message,
        "tool_results": [tool_result.to_protocol() for tool_result in tool_results],
    }
