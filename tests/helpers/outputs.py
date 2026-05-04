from __future__ import annotations

import json
from typing import Any


def tool_output(*calls: dict[str, Any], calls_field: str = "calls") -> str:
    return json.dumps({calls_field: list(calls)}, ensure_ascii=False)


def reply_output(message: str) -> str:
    return tool_output(
        {
            "tool": "reply",
            "method": "send_message",
            "arguments": {"message": message},
        }
    )


def custom_reply_output(message: str) -> str:
    return tool_output(
        {
            "tool_name": "reply",
            "operation": "send_message",
            "args": {"message": message},
        },
        calls_field="actions",
    )
