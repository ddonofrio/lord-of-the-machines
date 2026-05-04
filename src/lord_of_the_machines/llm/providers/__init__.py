from __future__ import annotations

from typing import Any

from lord_of_the_machines.llm.providers.base import ProviderAdapter
from lord_of_the_machines.llm.providers.openai import OpenAIProviderAdapter


_PROVIDER_ADAPTERS: dict[str, ProviderAdapter] = {
    "openai": OpenAIProviderAdapter(),
}


def get_provider_adapter(provider_name: str) -> ProviderAdapter:
    normalized = str(provider_name).strip().lower()
    adapter = _PROVIDER_ADAPTERS.get(normalized)
    if adapter is None:
        raise ValueError(f"Unsupported provider '{provider_name}'.")
    return adapter


__all__ = [
    "ProviderAdapter",
    "get_provider_adapter",
]
