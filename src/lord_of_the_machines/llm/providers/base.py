from __future__ import annotations

from typing import Any, Protocol

from lord_of_the_machines.llm.config import BaseAgentConfig
from lord_of_the_machines.llm.replies import AgentToolCall, AgentToolResult
from lord_of_the_machines.llm.tool_definitions import ToolDefinition


class ProviderAdapter(Protocol):
    provider_name: str

    def supports_tool_calling_mode(self, mode: str) -> bool: ...

    def build_client(self, *, api_key: str) -> Any: ...

    def create_response(self, client: Any, payload: dict[str, Any]) -> Any: ...

    def extract_text(self, response: Any) -> str: ...

    def uses_native_tool_calling(self, config: BaseAgentConfig) -> bool: ...

    def build_native_tools(self, agent_tools: list[ToolDefinition], *, config: BaseAgentConfig) -> list[dict[str, Any]]: ...

    def parse_native_tool_calls(
        self,
        response: Any,
        *,
        agent_tools: list[ToolDefinition],
        config: BaseAgentConfig,
    ) -> tuple[list[AgentToolCall], str | None]: ...

    def build_tool_result_items(self, tool_results: list[AgentToolResult], *, config: BaseAgentConfig) -> list[dict[str, Any]]: ...

    def build_native_tool_instructions(self, config: BaseAgentConfig) -> str: ...

    def adapt_envelope(self, envelope: dict[str, Any], *, config: BaseAgentConfig) -> None: ...

    def is_context_window_error(self, exc: Exception) -> bool: ...

    def is_rate_limit_error(self, exc: Exception) -> bool: ...

    def rate_limit_wait_seconds(self, exc: Exception, *, attempt: int, config: BaseAgentConfig) -> float: ...

    def rate_limit_budget(self, exc: Exception) -> dict[str, int] | None: ...

    def payload_with_supported_verbosity(
        self,
        payload: dict[str, Any],
        exc: Exception,
    ) -> tuple[dict[str, Any] | None, str | None]: ...
