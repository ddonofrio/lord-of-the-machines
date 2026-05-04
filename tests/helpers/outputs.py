from __future__ import annotations

import json
from typing import Any

from tests.helpers.fake_openai import FakeFunctionCall, FakeMessage, FakeOutputText, FakeResponse


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


def native_function_response(*calls: dict[str, Any], response_id: str = "resp_native") -> FakeResponse:
    output = [
        FakeFunctionCall(
            name=str(call["name"]),
            arguments=json.dumps(call.get("arguments") or {}, ensure_ascii=False),
            call_id=str(call.get("call_id") or f"call_{index + 1}"),
            id=str(call.get("id") or f"fc_{index + 1}"),
        )
        for index, call in enumerate(calls)
    ]
    return FakeResponse(output_text="", id=response_id, output=output)


def native_message_response(message: str, response_id: str = "resp_native_message") -> FakeResponse:
    return FakeResponse(
        output_text=message,
        id=response_id,
        output=[FakeMessage(content=[FakeOutputText(text=message)])],
    )
