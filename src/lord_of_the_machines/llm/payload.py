from __future__ import annotations

import json
from typing import Any

from lord_of_the_machines.llm.config import BaseAgentConfig, RESPONSE_PARAM_NAMES
from lord_of_the_machines.llm.envelope import DEFAULT_MEMORY_INSTRUCTION
from lord_of_the_machines.llm.history import HistoryManager
from lord_of_the_machines.llm.prompt_cache import PromptCacheManager
from lord_of_the_machines.llm.schema import build_tool_call_schema
from lord_of_the_machines.llm.tools import tools_for_prompt


class AgentPayloadBuilder:
    def __init__(
        self,
        *,
        config: BaseAgentConfig,
        history: HistoryManager,
        prompt_cache: PromptCacheManager,
    ):
        self.config = config
        self.history = history
        self.prompt_cache = prompt_cache

    def build(
        self,
        message: str | list[dict[str, Any]] | dict[str, Any],
        *,
        continue_previous: bool,
        overrides: dict[str, Any],
        last_response_id: str | None,
        history_token_budget: int | None = None,
        disabled_tools: set[str] | None = None,
    ) -> dict[str, Any]:
        unknown = sorted(set(overrides) - set(RESPONSE_PARAM_NAMES))
        if unknown:
            raise ValueError(f"Unknown Responses API parameter(s): {', '.join(unknown)}")

        payload = self.config.response_payload_defaults()
        payload.update({key: value for key, value in overrides.items() if value is not None})
        tools = self.tools_for_prompt(disabled_tools=disabled_tools)
        if self.config.envelope.enabled and "text" not in overrides:
            payload["text"] = build_tool_call_schema(tools, self.config.envelope.output, self.config.text_verbosity)
        elif not self.config.envelope.enabled and "text" not in overrides:
            payload.setdefault("text", {"format": {"type": "text"}})

        payload["instructions"] = self._build_instructions(payload.get("instructions"))
        payload["input"] = self._build_input(
            message,
            instructions=payload.get("instructions"),
            text_config=payload.get("text"),
            max_output_tokens=payload.get("max_output_tokens"),
            history_token_budget=history_token_budget,
            tools=tools,
        )
        self.prompt_cache.apply_defaults(payload)

        if payload.get("stream") is True:
            raise ValueError("BaseAgent.query currently supports non-streaming responses only.")
        if payload.get("conversation") and payload.get("previous_response_id"):
            raise ValueError("Use either conversation or previous_response_id, not both.")
        if payload.get("temperature") is not None and payload.get("top_p") is not None:
            raise ValueError("Set temperature or top_p, not both.")

        if self.config.context.mode == "local_history":
            payload.pop("conversation", None)
            payload.pop("previous_response_id", None)
        elif continue_previous and last_response_id and "previous_response_id" not in payload:
            payload["previous_response_id"] = last_response_id

        return payload

    def tools_for_prompt(self, *, disabled_tools: set[str] | None = None) -> list[dict[str, Any]]:
        return tools_for_prompt(self.config.agent_tools, reply=self.config.reply, disabled_tools=disabled_tools)

    def _build_instructions(self, request_instructions: str | None) -> str:
        parts = [self.config.envelope.instructions] if self.config.envelope.enabled else []
        if self.config.system_prompt:
            parts.append(f"System prompt:\n{self.config.system_prompt}")
        parts.append(self._build_output_language_instructions())
        if request_instructions:
            parts.append(f"Additional request instructions:\n{request_instructions}")
        return "\n\n".join(part for part in parts if part)

    def _build_output_language_instructions(self) -> str:
        return (
            "Output language:\n"
            f"All {self.config.reply.tool}.{self.config.reply.method} "
            f"arguments.{self.config.reply.message_argument} values must be written in "
            f"{self.config.reply.output_language}. This applies even when system prompts, tools, "
            "memories, or user messages are written in another language. Tool names, method names, "
            "and non-reply tool arguments must keep their required protocol format."
        )

    def _build_input(
        self,
        message: str | list[dict[str, Any]] | dict[str, Any],
        *,
        instructions: str | None,
        text_config: dict[str, Any] | None,
        max_output_tokens: Any,
        history_token_budget: int | None,
        tools: list[dict[str, Any]],
    ) -> Any:
        if not self.config.envelope.enabled:
            return message

        history = self.history.select(
            message=message,
            instructions=instructions,
            tools=tools,
            text_config=text_config,
            max_output_tokens=max_output_tokens,
            history_token_budget=history_token_budget,
        )
        envelope = self.config.envelope.build(
            system_prompt=self.config.system_prompt,
            context_mode=self.config.context.mode,
            history=history,
            memory=self.config.memory,
            tools=tools,
            message=message,
            memory_instruction=DEFAULT_MEMORY_INSTRUCTION,
        )
        return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), default=repr)
