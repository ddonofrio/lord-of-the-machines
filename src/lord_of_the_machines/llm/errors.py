from __future__ import annotations

from typing import Any


class MissingApiKeyError(RuntimeError):
    pass


class AgentProtocolError(RuntimeError):
    def __init__(self, parsing_error: str, *, last_output: str, last_response: Any = None):
        super().__init__(parsing_error)
        self.parsing_error = parsing_error
        self.last_output = last_output
        self.last_response = last_response


class AgentContextBudgetError(RuntimeError):
    pass
