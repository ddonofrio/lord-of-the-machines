from __future__ import annotations

import json
from typing import Any


class TokenCounter:
    def __init__(
        self,
        *,
        model: str,
        encoding_name: str | None = "auto",
        fallback_chars_per_token: int = 4,
    ):
        self.model = model
        self.encoding_name = encoding_name or "auto"
        self.fallback_chars_per_token = max(1, fallback_chars_per_token)
        self._encoding = self._load_encoding()

    def count(self, value: Any) -> int:
        if isinstance(value, str):
            text = value
        else:
            text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=repr)

        if not text:
            return 0
        if self.encoding_name == "character":
            return len(text)
        if self._encoding is not None:
            return len(self._encoding.encode(text))
        return max(1, (len(text) + self.fallback_chars_per_token - 1) // self.fallback_chars_per_token)

    def _load_encoding(self) -> Any | None:
        if self.encoding_name == "character":
            return None

        try:
            import tiktoken
        except ModuleNotFoundError:
            return None

        if self.encoding_name == "auto":
            try:
                return tiktoken.encoding_for_model(self.model)
            except KeyError:
                for fallback_name in ("o200k_base", "cl100k_base"):
                    try:
                        return tiktoken.get_encoding(fallback_name)
                    except ValueError:
                        continue
                return None

        try:
            return tiktoken.get_encoding(self.encoding_name)
        except ValueError:
            return None


def int_payload_value(value: Any) -> int:
    if value is None or isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def estimate_response_tokens(payload: dict[str, Any], token_counter: TokenCounter) -> dict[str, Any]:
    components: dict[str, int] = {}
    for name in ("instructions", "input", "text", "tools", "prompt", "include"):
        value = payload.get(name)
        if value in (None, "", [], {}):
            continue
        components[name] = token_counter.count(value)

    reserved_output_tokens = int_payload_value(payload.get("max_output_tokens"))
    total_tokens = sum(components.values()) + reserved_output_tokens
    return {
        "total_tokens": total_tokens,
        "reserved_output_tokens": reserved_output_tokens,
        "components": components,
    }
