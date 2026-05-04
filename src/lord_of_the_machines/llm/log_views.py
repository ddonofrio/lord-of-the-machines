from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from lord_of_the_machines.llm.config import BaseAgentConfig
from lord_of_the_machines.llm.rate_limit import TokenRateLimitReservation
from lord_of_the_machines.llm.replies import AgentReply, AgentToolCall, AgentToolResult


def config_for_log(config: BaseAgentConfig) -> dict[str, Any]:
    config_mapping = asdict(config)
    agent_tools = config_mapping.get("agent_tools") or []
    memory = config_mapping.get("memory") or []
    system_prompt = config_mapping.get("system_prompt") or ""
    protocol_instructions = config.envelope.instructions or ""
    return {
        "config_path": str(config_mapping.get("config_path")),
        "provider": config.model.provider,
        "model": config.model.effective_name(),
        "api_key_env": config.model.api_key_env,
        "model_env": config.model.model_env,
        "envelope_enabled": config.envelope.enabled,
        "envelope_version": config.envelope.version,
        "envelope_fields": [field.name for field in config.envelope.input_fields],
        "output_fields": config.envelope.output.to_mapping(),
        "text_verbosity": config.text_verbosity,
        "output_language": config.reply.output_language,
        "output_repair_attempts": config.output_repair_attempts,
        "max_tool_rounds": config.max_tool_rounds,
        "context_mode": config.context.mode,
        "context_window_tokens": config.context.context_window_tokens,
        "context_safety_margin_tokens": config.context.safety_margin_tokens,
        "max_history_tokens": config.context.max_history_tokens,
        "max_history_messages": config.context.max_history_messages,
        "context_overflow_retries": config.context.context_overflow_retries,
        "rate_limit_retries": config.transport.rate_limit_retries,
        "rate_limit_max_wait_seconds": config.transport.rate_limit_max_wait_seconds,
        "rate_limit_backoff_seconds": config.transport.rate_limit_backoff_seconds,
        "rate_limit_tokens_per_minute": config.transport.rate_limit_tokens_per_minute,
        "rate_limit_window_seconds": config.transport.rate_limit_window_seconds,
        "rate_limit_safety_margin_tokens": config.transport.rate_limit_safety_margin_tokens,
        "prompt_cache_enabled": config.prompt_cache.enabled,
        "prompt_cache_key_prefix": config.prompt_cache.key_prefix,
        "prompt_cache_fields": config.prompt_cache.fields,
        "prompt_cache_retention": config.prompt_cache.retention,
        "max_output_tokens": config.response_defaults.get("max_output_tokens"),
        "parallel_tool_calls": config.response_defaults.get("parallel_tool_calls"),
        "service_tier": config.response_defaults.get("service_tier"),
        "store": config.response_defaults.get("store"),
        "stream": config.response_defaults.get("stream"),
        "temperature": config.response_defaults.get("temperature"),
        "top_p": config.response_defaults.get("top_p"),
        "truncation": config.response_defaults.get("truncation"),
        "reasoning": config.response_defaults.get("reasoning"),
        "system_prompt_chars": len(system_prompt),
        "system_prompt_preview": truncate_text(system_prompt, 200),
        "protocol_instructions_chars": len(protocol_instructions),
        "protocol_instructions_preview": truncate_text(protocol_instructions, 160),
        "memory_count": len(memory),
        "memory_keys": [record.get("key") for record in memory[:5] if isinstance(record, dict) and record.get("key")],
        "tool_names": [tool.get("name") for tool in agent_tools if isinstance(tool, dict)],
        "tool_method_counts": {
            str(tool.get("name")): len(tool.get("methods") or [])
            for tool in agent_tools
            if isinstance(tool, dict) and tool.get("name")
        },
        "text_config": text_config_for_log(config.response_defaults.get("text")),
    }


def tool_call_for_log(tool_call: AgentToolCall) -> dict[str, Any]:
    return {
        "tool": tool_call.tool,
        "method": tool_call.method,
        "arguments": summarize_for_log(tool_call.arguments, long_text=180),
        "raw": summarize_for_log(tool_call.raw, long_text=180),
    }


def tool_result_for_log(tool_result: AgentToolResult) -> dict[str, Any]:
    return {
        "tool": tool_result.tool,
        "method": tool_result.method,
        "ok": tool_result.ok,
        "result": summarize_for_log(tool_result.result, long_text=180),
        "error": truncate_text(tool_result.error, 200) if isinstance(tool_result.error, str) else tool_result.error,
    }


def reply_for_log(reply: AgentReply) -> dict[str, Any]:
    return {
        "text_chars": len(reply.text or ""),
        "text_preview": truncate_text(reply.text, 500),
        "messages": [truncate_text(message, 240) for message in reply.messages],
        "message_count": len(reply.messages),
        "tool_calls": [tool_call_for_log(tool_call) for tool_call in reply.tool_calls],
        "parse_error": reply.parse_error,
        "response_id": reply.response_id,
        "status": reply.status,
        "usage": usage_for_log(reply.usage),
        "tool_results": [tool_result_for_log(tool_result) for tool_result in reply.tool_results],
    }


def rate_limit_reservation_for_log(reservation: TokenRateLimitReservation | None) -> dict[str, Any] | None:
    if reservation is None:
        return None
    return {
        "token_count": reservation.token_count,
        "capacity": reservation.capacity,
        "used_before": reservation.used_before,
        "wait_seconds": round(reservation.wait_seconds, 3),
        "attempts": reservation.attempts,
        "oversized": reservation.oversized,
    }


def payload_for_log(payload: dict[str, Any]) -> dict[str, Any]:
    instructions = payload.get("instructions")
    tools = payload.get("tools") or []
    return {
        "model": payload.get("model"),
        "input": input_for_log(payload.get("input")),
        "instructions_chars": len(instructions or ""),
        "tools_count": len(tools),
        "tool_names": [
            tool.get("name") or tool.get("type") or tool.get("function", {}).get("name")
            for tool in tools
            if isinstance(tool, dict)
        ],
        "text": text_config_for_log(payload.get("text")),
        "max_output_tokens": payload.get("max_output_tokens"),
        "prompt_cache_key": payload.get("prompt_cache_key"),
        "prompt_cache_retention": payload.get("prompt_cache_retention"),
        "previous_response_id": payload.get("previous_response_id"),
        "parallel_tool_calls": payload.get("parallel_tool_calls"),
        "service_tier": payload.get("service_tier"),
        "store": payload.get("store"),
        "stream": payload.get("stream"),
        "temperature": payload.get("temperature"),
        "top_p": payload.get("top_p"),
        "truncation": payload.get("truncation"),
        "reasoning": payload.get("reasoning"),
    }


def response_for_log(response: Any) -> dict[str, Any]:
    output_text = extract_text(response)
    return {
        "type": type(response).__name__,
        "id": getattr(response, "id", None),
        "status": getattr(response, "status", None),
        "usage": usage_for_log(getattr(response, "usage", None)),
        "output_text_chars": len(output_text),
        "output_text_preview": truncate_text(output_text, 500),
    }


def usage_for_log(usage: Any) -> dict[str, Any] | Any:
    if usage is None:
        return None
    input_tokens = usage_value(usage, "input_tokens", "prompt_tokens")
    output_tokens = usage_value(usage, "output_tokens", "completion_tokens")
    total_tokens = usage_value(usage, "total_tokens")
    input_details = usage_value(usage, "input_tokens_details", "prompt_tokens_details")
    cached_tokens = usage_value(input_details, "cached_tokens")
    summary = {
        "input_tokens": input_tokens,
        "cached_tokens": cached_tokens,
        "cache_hit_ratio": round(cached_tokens / input_tokens, 4) if input_tokens else None,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }
    if any(value is not None for value in summary.values()):
        return summary
    return usage


def usage_value(value: Any, *names: str) -> Any:
    for name in names:
        if isinstance(value, dict) and name in value:
            return value[name]
        if value is not None and hasattr(value, name):
            return getattr(value, name)
    return None


def input_for_log(input_value: Any) -> dict[str, Any]:
    if not isinstance(input_value, str):
        return {
            "type": type(input_value).__name__,
            "summary": summarize_for_log(input_value, long_text=160),
        }

    summary: dict[str, Any] = {
        "type": "json-string",
        "chars": len(input_value),
    }
    try:
        envelope = json.loads(input_value)
    except json.JSONDecodeError:
        summary["preview"] = truncate_text(input_value, 200)
        return summary

    for field_name in ("conversation_history", "history"):
        conversation_history = envelope.get(field_name)
        if isinstance(conversation_history, list):
            summary["history_messages"] = len(conversation_history)
            break

    runtime_context = envelope.get("runtime_context") or envelope.get("context")
    if isinstance(runtime_context, dict):
        memories = runtime_context.get("memory")
        tools = runtime_context.get("available_tools")
        if isinstance(memories, list):
            summary["memory_count"] = len(memories)
        if isinstance(tools, list):
            summary["available_tools"] = [
                tool.get("name")
                for tool in tools
                if isinstance(tool, dict) and tool.get("name")
            ]

    prompt = None
    for field_name in ("user", "request"):
        value = envelope.get(field_name)
        if isinstance(value, dict) and "prompt" in value:
            prompt = value.get("prompt")
            break
    if isinstance(prompt, dict):
        summary["prompt_type"] = prompt.get("type")
        summary["prompt"] = summarize_for_log(prompt, long_text=160)
    else:
        summary["prompt"] = summarize_for_log(prompt, long_text=160)

    return summary


def text_config_for_log(value: Any) -> Any:
    if not isinstance(value, dict):
        return summarize_for_log(value, long_text=100)
    format_config = value.get("format")
    summary: dict[str, Any] = {"keys": sorted(value)}
    if isinstance(format_config, dict):
        schema = format_config.get("schema")
        summary["format"] = {
            "type": format_config.get("type"),
            "name": format_config.get("name"),
            "schema_keys": sorted(schema) if isinstance(schema, dict) else None,
        }
    return summary


def summarize_for_log(value: Any, *, long_text: int = 160) -> Any:
    if isinstance(value, str):
        return truncate_text(value, long_text)
    if isinstance(value, dict):
        return {str(key): summarize_for_log(item, long_text=long_text) for key, item in value.items()}
    if isinstance(value, list):
        return [summarize_for_log(item, long_text=long_text) for item in value]
    if isinstance(value, tuple):
        return [summarize_for_log(item, long_text=long_text) for item in value]
    return value


def truncate_text(value: str | None, max_chars: int) -> str | None:
    if value is None:
        return None
    if len(value) <= max_chars:
        return value
    return value[: max(0, max_chars - 3)].rstrip() + "..."


def extract_text(response: Any) -> str:
    return (getattr(response, "output_text", "") or "").strip()
