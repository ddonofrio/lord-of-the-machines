from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lord_of_the_machines.llm.envelope import AgentEnvelopeSpec, ToolCallOutputSpec
from lord_of_the_machines.llm.tool_definitions import ToolDefinition, ensure_tool_definitions
from lord_of_the_machines.runtime.paths import DEFAULT_BASE_AGENT_CONFIG


CONFIG_ENV_VAR = "LORD_OF_THE_MACHINES_BASE_AGENT_CONFIG"
DEFAULT_CONFIG_PATH = DEFAULT_BASE_AGENT_CONFIG

DEFAULT_MODEL_NAME = "gpt-4.1"
DEFAULT_TEXT_VERBOSITY = "medium"
DEFAULT_OUTPUT_LANGUAGE = "English"
DEFAULT_OUTPUT_REPAIR_ATTEMPTS = 5
DEFAULT_MAX_TOOL_ROUNDS = 5
DEFAULT_CONTEXT_MODE = "local_history"
DEFAULT_CONTEXT_WINDOW_TOKENS = 400_000
DEFAULT_CONTEXT_SAFETY_MARGIN_TOKENS = 4096
DEFAULT_FALLBACK_CHARS_PER_TOKEN = 4
DEFAULT_CONTEXT_OVERFLOW_RETRIES = 1
DEFAULT_RATE_LIMIT_RETRIES = 3
DEFAULT_RATE_LIMIT_MAX_WAIT_SECONDS = 90.0
DEFAULT_RATE_LIMIT_BACKOFF_SECONDS = 2.0
DEFAULT_RATE_LIMIT_TOKENS_PER_MINUTE = 30_000
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60.0
DEFAULT_RATE_LIMIT_SAFETY_MARGIN_TOKENS = 512
DEFAULT_PROMPT_CACHE_PREFIX = "lotm"
DEFAULT_PROMPT_CACHE_RETENTION = "24h"
DEFAULT_MAX_OUTPUT_TOKENS = 4096
DEFAULT_TOOL_CALLING_MODE = "protocol"
DEFAULT_NATIVE_TOOL_NAME_SEPARATOR = "__"
ROOT_CONFIG_KEYS = {
    "provider",
    "agent",
    "reply",
    "tool_calling",
    "envelope",
    "context",
    "transport",
    "prompt_cache",
    "agent_tools",
    "response_defaults",
}

RESPONSE_PARAM_NAMES = (
    "background",
    "context_management",
    "conversation",
    "include",
    "instructions",
    "max_output_tokens",
    "max_tool_calls",
    "metadata",
    "model",
    "parallel_tool_calls",
    "previous_response_id",
    "prompt",
    "prompt_cache_key",
    "prompt_cache_retention",
    "reasoning",
    "safety_identifier",
    "service_tier",
    "store",
    "stream",
    "stream_options",
    "temperature",
    "text",
    "tool_choice",
    "tools",
    "top_logprobs",
    "top_p",
    "truncation",
    "user",
    "extra_headers",
    "extra_query",
    "extra_body",
    "timeout",
)


def load_base_agent_settings(config_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(config_path or os.getenv(CONFIG_ENV_VAR) or DEFAULT_CONFIG_PATH)
    with path.open("r", encoding="utf-8") as config_file:
        settings = json.load(config_file)

    if not isinstance(settings, dict):
        raise ValueError(f"Base agent config must be a JSON object: {path}")
    unknown = sorted(set(settings) - ROOT_CONFIG_KEYS)
    if unknown:
        raise ValueError(
            "Unsupported base agent config field(s): "
            f"{', '.join(unknown)}. Use the structured sections: {', '.join(sorted(ROOT_CONFIG_KEYS))}."
        )
    return copy.deepcopy(settings)


def load_mapping_section(settings: dict[str, Any], section_name: str) -> dict[str, Any]:
    value = settings.get(section_name)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Config section '{section_name}' must be a JSON object.")
    return copy.deepcopy(value)


@dataclass(slots=True)
class ModelConfig:
    provider: str = "openai"
    name: str = DEFAULT_MODEL_NAME
    api_key_env: str = "OPENAI_API_KEY"
    model_env: str | None = "OPENAI_MODEL"

    @classmethod
    def from_mapping(cls, settings: dict[str, Any] | None) -> ModelConfig:
        settings = settings or {}
        return cls(
            provider=str(settings.get("provider") or "openai"),
            name=str(settings.get("model") or settings.get("name") or DEFAULT_MODEL_NAME),
            api_key_env=str(settings.get("api_key_env") or "OPENAI_API_KEY"),
            model_env=settings.get("model_env", "OPENAI_MODEL"),
        )

    def effective_name(self) -> str:
        if self.model_env and os.getenv(self.model_env):
            return str(os.getenv(self.model_env))
        return self.name


@dataclass(slots=True)
class ContextConfig:
    mode: str = DEFAULT_CONTEXT_MODE
    context_window_tokens: int = DEFAULT_CONTEXT_WINDOW_TOKENS
    safety_margin_tokens: int = DEFAULT_CONTEXT_SAFETY_MARGIN_TOKENS
    max_history_tokens: int | None = None
    max_history_messages: int | None = None
    token_counter_encoding: str | None = "auto"
    fallback_chars_per_token: int = DEFAULT_FALLBACK_CHARS_PER_TOKEN
    context_overflow_retries: int = DEFAULT_CONTEXT_OVERFLOW_RETRIES

    @classmethod
    def from_mapping(cls, settings: dict[str, Any] | None) -> ContextConfig:
        settings = settings or {}
        return cls(
            mode=str(settings.get("mode") or DEFAULT_CONTEXT_MODE),
            context_window_tokens=int(settings.get("context_window_tokens", DEFAULT_CONTEXT_WINDOW_TOKENS)),
            safety_margin_tokens=int(settings.get("safety_margin_tokens", DEFAULT_CONTEXT_SAFETY_MARGIN_TOKENS)),
            max_history_tokens=settings.get("max_history_tokens"),
            max_history_messages=settings.get("max_history_messages"),
            token_counter_encoding=settings.get("token_counter_encoding", "auto"),
            fallback_chars_per_token=int(settings.get("fallback_chars_per_token", DEFAULT_FALLBACK_CHARS_PER_TOKEN)),
            context_overflow_retries=int(settings.get("context_overflow_retries", DEFAULT_CONTEXT_OVERFLOW_RETRIES)),
        )


@dataclass(slots=True)
class TransportConfig:
    rate_limit_retries: int = DEFAULT_RATE_LIMIT_RETRIES
    rate_limit_max_wait_seconds: float = DEFAULT_RATE_LIMIT_MAX_WAIT_SECONDS
    rate_limit_backoff_seconds: float = DEFAULT_RATE_LIMIT_BACKOFF_SECONDS
    rate_limit_tokens_per_minute: int | None = DEFAULT_RATE_LIMIT_TOKENS_PER_MINUTE
    rate_limit_window_seconds: float = DEFAULT_RATE_LIMIT_WINDOW_SECONDS
    rate_limit_safety_margin_tokens: int = DEFAULT_RATE_LIMIT_SAFETY_MARGIN_TOKENS

    @classmethod
    def from_mapping(cls, settings: dict[str, Any] | None) -> TransportConfig:
        settings = settings or {}
        return cls(
            rate_limit_retries=int(settings.get("rate_limit_retries", DEFAULT_RATE_LIMIT_RETRIES)),
            rate_limit_max_wait_seconds=float(settings.get("rate_limit_max_wait_seconds", DEFAULT_RATE_LIMIT_MAX_WAIT_SECONDS)),
            rate_limit_backoff_seconds=float(settings.get("rate_limit_backoff_seconds", DEFAULT_RATE_LIMIT_BACKOFF_SECONDS)),
            rate_limit_tokens_per_minute=settings.get("rate_limit_tokens_per_minute", DEFAULT_RATE_LIMIT_TOKENS_PER_MINUTE),
            rate_limit_window_seconds=float(settings.get("rate_limit_window_seconds", DEFAULT_RATE_LIMIT_WINDOW_SECONDS)),
            rate_limit_safety_margin_tokens=int(settings.get("rate_limit_safety_margin_tokens", DEFAULT_RATE_LIMIT_SAFETY_MARGIN_TOKENS)),
        )


@dataclass(slots=True)
class PromptCacheConfig:
    enabled: bool = True
    key_prefix: str = DEFAULT_PROMPT_CACHE_PREFIX
    retention: str | None = DEFAULT_PROMPT_CACHE_RETENTION
    fields: tuple[str, ...] = ("model", "instructions", "text", "tools", "envelope")

    @classmethod
    def from_mapping(cls, settings: dict[str, Any] | None) -> PromptCacheConfig:
        settings = settings or {}
        fields = settings.get("fields") or ("model", "instructions", "text", "tools", "envelope")
        return cls(
            enabled=bool(settings.get("enabled", True)),
            key_prefix=str(settings.get("key_prefix") or DEFAULT_PROMPT_CACHE_PREFIX),
            retention=settings.get("retention", DEFAULT_PROMPT_CACHE_RETENTION),
            fields=tuple(str(field_name) for field_name in fields),
        )


@dataclass(slots=True)
class ReplyConfig:
    tool: str = "reply"
    method: str = "send_message"
    message_argument: str = "message"
    output_language: str = DEFAULT_OUTPUT_LANGUAGE

    @classmethod
    def from_mapping(cls, settings: dict[str, Any] | None) -> ReplyConfig:
        settings = settings or {}
        return cls(
            tool=str(settings.get("tool") or "reply"),
            method=str(settings.get("method") or "send_message"),
            message_argument=str(settings.get("message_argument") or "message"),
            output_language=str(settings.get("output_language") or DEFAULT_OUTPUT_LANGUAGE),
        )


@dataclass(slots=True)
class ToolCallingConfig:
    mode: str = DEFAULT_TOOL_CALLING_MODE
    native_name_separator: str = DEFAULT_NATIVE_TOOL_NAME_SEPARATOR
    include_tools_in_envelope: bool = False
    include_output_contract_in_envelope: bool = False

    @classmethod
    def from_mapping(cls, settings: dict[str, Any] | None) -> ToolCallingConfig:
        settings = settings or {}
        return cls(
            mode=str(settings.get("mode") or DEFAULT_TOOL_CALLING_MODE),
            native_name_separator=str(settings.get("native_name_separator") or DEFAULT_NATIVE_TOOL_NAME_SEPARATOR),
            include_tools_in_envelope=bool(settings.get("include_tools_in_envelope", False)),
            include_output_contract_in_envelope=bool(settings.get("include_output_contract_in_envelope", False)),
        )


def default_response_defaults() -> dict[str, Any]:
    return {
        "background": False,
        "max_output_tokens": DEFAULT_MAX_OUTPUT_TOKENS,
        "parallel_tool_calls": True,
        "prompt_cache_retention": None,
        "service_tier": "auto",
        "store": True,
        "stream": False,
        "truncation": "disabled",
    }


@dataclass(slots=True)
class BaseAgentConfig:
    config_path: str | Path | None = None
    model: ModelConfig = field(default_factory=ModelConfig)
    envelope: AgentEnvelopeSpec = field(default_factory=AgentEnvelopeSpec)
    context: ContextConfig = field(default_factory=ContextConfig)
    transport: TransportConfig = field(default_factory=TransportConfig)
    prompt_cache: PromptCacheConfig = field(default_factory=PromptCacheConfig)
    reply: ReplyConfig = field(default_factory=ReplyConfig)
    tool_calling: ToolCallingConfig = field(default_factory=ToolCallingConfig)
    system_prompt: str | None = None
    memory: list[Any] = field(default_factory=list)
    agent_tools: list[ToolDefinition] = field(default_factory=list)
    text_verbosity: str = DEFAULT_TEXT_VERBOSITY
    output_repair_attempts: int = DEFAULT_OUTPUT_REPAIR_ATTEMPTS
    max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS
    response_defaults: dict[str, Any] = field(default_factory=default_response_defaults)

    @classmethod
    def from_file(cls, config_path: str | Path | None = None, **overrides: Any) -> BaseAgentConfig:
        settings = load_base_agent_settings(config_path)

        provider_settings = load_mapping_section(settings, "provider")
        envelope_settings = load_mapping_section(settings, "envelope")
        agent_settings = load_mapping_section(settings, "agent")
        response_defaults = default_response_defaults()
        response_defaults.update(load_mapping_section(settings, "response_defaults"))

        config = cls(
            config_path=config_path or os.getenv(CONFIG_ENV_VAR) or str(DEFAULT_CONFIG_PATH),
            model=ModelConfig.from_mapping(provider_settings),
            envelope=AgentEnvelopeSpec.from_mapping(envelope_settings),
            context=ContextConfig.from_mapping(load_mapping_section(settings, "context")),
            transport=TransportConfig.from_mapping(load_mapping_section(settings, "transport")),
            prompt_cache=PromptCacheConfig.from_mapping(load_mapping_section(settings, "prompt_cache")),
            reply=ReplyConfig.from_mapping(load_mapping_section(settings, "reply")),
            tool_calling=ToolCallingConfig.from_mapping(load_mapping_section(settings, "tool_calling")),
            system_prompt=agent_settings.get("system_prompt"),
            memory=copy.deepcopy(agent_settings.get("memory") or []),
            agent_tools=ensure_tool_definitions(settings.get("agent_tools") or []),
            text_verbosity=str(agent_settings.get("text_verbosity") or DEFAULT_TEXT_VERBOSITY),
            output_repair_attempts=int(agent_settings.get("output_repair_attempts", DEFAULT_OUTPUT_REPAIR_ATTEMPTS)),
            max_tool_rounds=int(agent_settings.get("max_tool_rounds", DEFAULT_MAX_TOOL_ROUNDS)),
            response_defaults=response_defaults,
        )
        config.apply_overrides(overrides)
        return config

    def response_payload_defaults(self) -> dict[str, Any]:
        defaults = copy.deepcopy(self.response_defaults)
        defaults["model"] = self.model.effective_name()
        return {key: value for key, value in defaults.items() if value is not None}

    def apply_overrides(self, overrides: dict[str, Any]) -> None:
        unknown = []
        for key, value in overrides.items():
            if key in RESPONSE_PARAM_NAMES:
                self.response_defaults[key] = value
            elif key in {"model_name", "model"}:
                self.model.name = str(value)
            elif key == "provider":
                self.model.provider = str(value)
            elif key == "api_key_env":
                self.model.api_key_env = str(value)
            elif key == "model_env":
                self.model.model_env = value
            elif key in {"envelope", "envelope_spec"}:
                self.envelope = value if isinstance(value, AgentEnvelopeSpec) else AgentEnvelopeSpec.from_mapping(value)
            elif key == "output_spec":
                self.envelope.output = value if isinstance(value, ToolCallOutputSpec) else ToolCallOutputSpec.from_mapping(value)
            elif key == "system_prompt":
                self.system_prompt = value
            elif key == "memory":
                self.memory = copy.deepcopy(value)
            elif key == "agent_tools":
                self.agent_tools = ensure_tool_definitions(value)
            elif key == "text_verbosity":
                self.text_verbosity = str(value)
            elif key == "output_language":
                self.reply.output_language = str(value)
            elif key == "reply_tool":
                self.reply.tool = str(value)
            elif key == "reply_method":
                self.reply.method = str(value)
            elif key == "reply_message_argument":
                self.reply.message_argument = str(value)
            elif key == "tool_calling":
                self.tool_calling = value if isinstance(value, ToolCallingConfig) else ToolCallingConfig.from_mapping(value)
            elif key == "tool_calling_mode":
                self.tool_calling.mode = str(value)
            elif key == "native_tool_name_separator":
                self.tool_calling.native_name_separator = str(value)
            elif key == "include_tools_in_envelope":
                self.tool_calling.include_tools_in_envelope = bool(value)
            elif key == "include_output_contract_in_envelope":
                self.tool_calling.include_output_contract_in_envelope = bool(value)
            elif key == "output_repair_attempts":
                self.output_repair_attempts = int(value)
            elif key == "max_tool_rounds":
                self.max_tool_rounds = int(value)
            elif key == "context_mode":
                self.context.mode = str(value)
            elif key == "context_window_tokens":
                self.context.context_window_tokens = int(value)
            elif key == "context_safety_margin_tokens":
                self.context.safety_margin_tokens = int(value)
            elif key == "max_history_tokens":
                self.context.max_history_tokens = value
            elif key == "max_history_messages":
                self.context.max_history_messages = value
            elif key == "token_counter_encoding":
                self.context.token_counter_encoding = value
            elif key == "fallback_chars_per_token":
                self.context.fallback_chars_per_token = int(value)
            elif key == "context_overflow_retries":
                self.context.context_overflow_retries = int(value)
            elif key == "rate_limit_retries":
                self.transport.rate_limit_retries = int(value)
            elif key == "rate_limit_max_wait_seconds":
                self.transport.rate_limit_max_wait_seconds = float(value)
            elif key == "rate_limit_backoff_seconds":
                self.transport.rate_limit_backoff_seconds = float(value)
            elif key == "rate_limit_tokens_per_minute":
                self.transport.rate_limit_tokens_per_minute = value
            elif key == "rate_limit_window_seconds":
                self.transport.rate_limit_window_seconds = float(value)
            elif key == "rate_limit_safety_margin_tokens":
                self.transport.rate_limit_safety_margin_tokens = int(value)
            elif key == "prompt_cache_enabled":
                self.prompt_cache.enabled = bool(value)
            elif key == "prompt_cache_key_prefix":
                self.prompt_cache.key_prefix = str(value)
            elif key == "prompt_cache_fields":
                self.prompt_cache.fields = tuple(str(field_name) for field_name in value)
            elif key == "prompt_cache_retention":
                self.prompt_cache.retention = value
            else:
                unknown.append(key)
        if unknown:
            raise ValueError(f"Unknown BaseAgentConfig override(s): {', '.join(sorted(unknown))}")
