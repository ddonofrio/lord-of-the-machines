from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from lord_of_the_machines.llm.config import BaseAgentConfig


class PromptCacheManager:
    def __init__(self, config: BaseAgentConfig):
        self.config = config

    def apply_defaults(self, payload: dict[str, Any]) -> None:
        if not self.config.prompt_cache.enabled:
            return
        if self.config.prompt_cache.retention and not payload.get("prompt_cache_retention"):
            payload["prompt_cache_retention"] = self.config.prompt_cache.retention
        if not payload.get("prompt_cache_key"):
            payload["prompt_cache_key"] = self.default_key(payload)

    def default_key(self, payload: dict[str, Any]) -> str:
        model = str(payload.get("model") or self.config.model.effective_name() or "model")
        model_slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", model).strip("-").lower() or "model"
        seed = {
            field_name: self._cache_field_value(payload, field_name)
            for field_name in self.config.prompt_cache.fields
        }
        encoded_seed = json.dumps(seed, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=repr)
        digest = hashlib.sha256(encoded_seed.encode("utf-8")).hexdigest()[:24]
        prefix = re.sub(r"[^a-zA-Z0-9_-]+", "-", self.config.prompt_cache.key_prefix).strip("-").lower() or "agent"
        return f"{prefix}-{model_slug}-{digest}"[:64]

    def _cache_field_value(self, payload: dict[str, Any], field_name: str) -> Any:
        if field_name == "envelope":
            return self.config.envelope.cache_identity()

        current: Any = payload
        for part in field_name.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return None
        return current
