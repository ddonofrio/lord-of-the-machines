from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from lord_of_the_machines.llm.config import BaseAgentConfig
from lord_of_the_machines.llm.envelope import DEFAULT_MEMORY_INSTRUCTION
from lord_of_the_machines.llm.replies import AgentReply
from lord_of_the_machines.llm.tokens import TokenCounter, int_payload_value


class HistoryManager:
    def __init__(
        self,
        *,
        config: BaseAgentConfig,
        token_counter: TokenCounter,
        logger: Any,
        log_id: Callable[[], str],
        summarize_for_log: Callable[[Any], Any],
        log_json: Callable[..., None],
    ):
        self._items: list[dict[str, Any]] = []
        self.config = config
        self.token_counter = token_counter
        self._logger = logger
        self._log_id = log_id
        self._summarize_for_log = summarize_for_log
        self._log_json = log_json

    def get(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._items)

    def clear(self) -> None:
        self._items.clear()

    def add(self, role: str, content: Any) -> None:
        if role not in {"user", "assistant"}:
            raise ValueError("History role must be 'user' or 'assistant'.")
        self._items.append({"role": role, "content": copy.deepcopy(content)})
        self._log_json(
            self._logger,
            "base_agent.history.append",
            {
                "agent_id": self._log_id(),
                "role": role,
                "content": self._summarize_for_log(content),
                "history_size": len(self._items),
            },
        )

    def record_turn(
        self,
        user_message: str | list[dict[str, Any]] | dict[str, Any],
        reply: AgentReply,
    ) -> None:
        if self.config.context.mode != "local_history":
            return

        self.add("user", user_message)
        if reply.messages:
            for message in reply.messages:
                self.add("assistant", message)
        elif reply.text:
            self.add("assistant", reply.text)

    def select(
        self,
        *,
        message: str | list[dict[str, Any]] | dict[str, Any],
        instructions: str | None,
        tools: list[dict[str, Any]],
        text_config: dict[str, Any] | None,
        max_output_tokens: Any,
        history_token_budget: int | None,
    ) -> list[dict[str, Any]]:
        if self.config.context.mode != "local_history" or not self._items:
            self._log_json(
                self._logger,
                "base_agent.history.selected",
                {"agent_id": self._log_id(), "mode": self.config.context.mode, "available": len(self._items), "selected": 0},
            )
            return []

        budget = self.budget(
            message=message,
            instructions=instructions,
            tools=tools,
            text_config=text_config,
            max_output_tokens=max_output_tokens,
            history_token_budget=history_token_budget,
        )
        if budget <= 0:
            self._log_json(
                self._logger,
                "base_agent.history.selected",
                {"agent_id": self._log_id(), "budget": budget, "available": len(self._items), "selected": 0},
            )
            return []

        candidates = self._items
        if self.config.context.max_history_messages is not None:
            max_messages = max(0, self.config.context.max_history_messages)
            candidates = candidates[-max_messages:] if max_messages else []

        selected_reversed: list[dict[str, Any]] = []
        used = 0
        for item in reversed(candidates):
            item_tokens = self.token_counter.count(item) + 4
            if selected_reversed and used + item_tokens > budget:
                break
            if not selected_reversed and item_tokens > budget:
                break
            selected_reversed.append(copy.deepcopy(item))
            used += item_tokens

        selected = list(reversed(selected_reversed))
        self._log_json(
            self._logger,
            "base_agent.history.selected",
            {
                "agent_id": self._log_id(),
                "budget": budget,
                "available": len(self._items),
                "selected": len(selected),
                "used_tokens_estimate": used,
            },
        )
        return selected

    def budget(
        self,
        *,
        message: str | list[dict[str, Any]] | dict[str, Any],
        instructions: str | None,
        tools: list[dict[str, Any]],
        text_config: dict[str, Any] | None,
        max_output_tokens: Any,
        history_token_budget: int | None,
    ) -> int:
        non_history_envelope = self.config.envelope.build(
            system_prompt=self.config.system_prompt,
            context_mode=self.config.context.mode,
            history=[],
            memory=self.config.memory,
            tools=tools,
            message=message,
            memory_instruction=DEFAULT_MEMORY_INSTRUCTION,
        )
        reserved_output_tokens = int_payload_value(max_output_tokens)
        fixed_tokens = (
            self.token_counter.count(instructions or "")
            + self.token_counter.count(non_history_envelope)
            + self.token_counter.count(text_config or {})
        )
        budgets = [
            self.config.context.context_window_tokens
            - reserved_output_tokens
            - int(self.config.context.safety_margin_tokens)
            - fixed_tokens
        ]
        if history_token_budget is not None:
            budgets.append(max(0, history_token_budget))
        if self.config.context.max_history_tokens is not None:
            budgets.append(max(0, self.config.context.max_history_tokens))
        request_token_limit = self.single_request_token_limit()
        if request_token_limit is not None:
            budgets.append(
                request_token_limit
                - reserved_output_tokens
                - int(self.config.transport.rate_limit_safety_margin_tokens)
                - fixed_tokens
            )
        budget = min(budgets)
        self._log_json(
            self._logger,
            "base_agent.history.budget",
            {
                "agent_id": self._log_id(),
                "budget": max(0, budget),
                "fixed_tokens_estimate": fixed_tokens,
                "reserved_output_tokens": reserved_output_tokens,
                "context_window_tokens": self.config.context.context_window_tokens,
                "request_token_limit": request_token_limit,
                "rate_limit_safety_margin_tokens": self.config.transport.rate_limit_safety_margin_tokens,
            },
        )
        return max(0, budget)

    def single_request_token_limit(self) -> int | None:
        tokens_per_minute = self.config.transport.rate_limit_tokens_per_minute
        if tokens_per_minute is None or tokens_per_minute <= 0:
            return None
        return int(tokens_per_minute)
