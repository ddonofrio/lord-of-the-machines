from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class FakeUsageDetails:
    cached_tokens: int | None = None


@dataclass(slots=True)
class FakeUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    input_tokens_details: FakeUsageDetails | None = None


@dataclass(slots=True)
class FakeResponse:
    output_text: str
    id: str = "resp_fake"
    status: str = "completed"
    usage: FakeUsage = field(default_factory=FakeUsage)
    output: list[Any] = field(default_factory=list)


@dataclass(slots=True)
class FakeFunctionCall:
    name: str
    arguments: str
    call_id: str = "call_fake"
    id: str = "fc_fake"
    type: str = "function_call"


@dataclass(slots=True)
class FakeOutputText:
    text: str
    type: str = "output_text"


@dataclass(slots=True)
class FakeMessage:
    content: list[Any]
    type: str = "message"


class FakeResponses:
    def __init__(self, outputs: list[Any] | None = None, *, default_message: str = "ok") -> None:
        self.outputs = list(outputs or [])
        self.default_message = default_message
        self.calls: list[dict[str, Any]] = []

    def create(self, **payload: Any) -> FakeResponse:
        self.calls.append(payload)
        output = self.outputs.pop(0) if self.outputs else self.default_message
        if isinstance(output, Exception):
            raise output
        if isinstance(output, FakeResponse):
            return output
        return FakeResponse(str(output), id=f"resp_{len(self.calls)}")


class FakeClient:
    def __init__(self, outputs: list[Any] | None = None, *, default_message: str = "ok") -> None:
        self.responses = FakeResponses(outputs, default_message=default_message)


class FakeContextWindowError(Exception):
    status_code = 400


class FakeRateLimitError(Exception):
    status_code = 429


class FakeUnsupportedVerbosityError(Exception):
    status_code = 400
