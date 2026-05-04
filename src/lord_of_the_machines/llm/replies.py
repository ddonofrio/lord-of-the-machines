from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AgentToolCall:
    tool: str
    method: str
    arguments: dict[str, Any]
    raw: dict[str, Any]
    call_id: str | None = None


@dataclass(slots=True)
class AgentToolResult:
    tool: str
    method: str
    ok: bool
    result: Any = None
    error: str | None = None
    call_id: str | None = None

    def to_protocol(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "method": self.method,
            "ok": self.ok,
            "result": self.result,
            "error": self.error,
            "call_id": self.call_id,
        }


@dataclass(slots=True)
class AgentReply:
    text: str
    tool_calls: list[AgentToolCall]
    parse_error: str | None
    response_id: str | None
    status: str | None
    usage: Any | None
    raw_response: Any
    tool_results: list[AgentToolResult] = field(default_factory=list)
    reply_tool: str = "reply"
    reply_method: str = "send_message"
    reply_message_argument: str = "message"

    @property
    def parsed(self) -> list[dict[str, Any]] | None:
        if self.parse_error:
            return None
        return [tool_call.raw for tool_call in self.tool_calls]

    @property
    def tool(self) -> str | None:
        return self.tool_calls[0].tool if self.tool_calls else None

    @property
    def method(self) -> str | None:
        return self.tool_calls[0].method if self.tool_calls else None

    @property
    def messages(self) -> list[str]:
        messages = []
        for tool_call in self.tool_calls:
            if tool_call.tool == self.reply_tool and tool_call.method == self.reply_method:
                message = tool_call.arguments.get(self.reply_message_argument)
                if isinstance(message, str):
                    messages.append(message)
        return messages

    @property
    def message(self) -> str:
        messages = self.messages
        return "\n".join(messages) if messages else self.text

    def __str__(self) -> str:
        return self.message
