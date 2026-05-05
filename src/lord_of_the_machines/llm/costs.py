from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lord_of_the_machines.runtime.paths import DEFAULT_MODEL_PRICING_CONFIG


MODEL_PRICING_ENV_VAR = "LORD_OF_THE_MACHINES_MODEL_PRICING"


@dataclass(slots=True)
class ModelPricing:
    input_per_1m: float
    cached_input_per_1m: float
    output_per_1m: float
    source: str | None = None
    updated_at: str | None = None


def usage_token_summary(usage: Any) -> dict[str, int] | None:
    if usage is None:
        return None
    input_tokens = _usage_value(usage, "input_tokens", "prompt_tokens")
    output_tokens = _usage_value(usage, "output_tokens", "completion_tokens")
    total_tokens = _usage_value(usage, "total_tokens")
    input_details = _usage_value(usage, "input_tokens_details", "prompt_tokens_details")
    cached_tokens = _usage_value(input_details, "cached_tokens")
    input_int = _as_non_negative_int(input_tokens)
    output_int = _as_non_negative_int(output_tokens)
    cached_int = _as_non_negative_int(cached_tokens)
    total_int = _as_non_negative_int(total_tokens)
    if all(value is None for value in (input_int, output_int, cached_int, total_int)):
        return None
    input_value = input_int or 0
    output_value = output_int or 0
    cached_value = cached_int or 0
    billable_input_value = max(input_value - cached_value, 0)
    total_value = total_int if total_int is not None else input_value + output_value
    return {
        "input_tokens": input_value,
        "cached_input_tokens": cached_value,
        "billable_input_tokens": billable_input_value,
        "output_tokens": output_value,
        "total_tokens": total_value,
    }


def estimate_usage_cost(
    *,
    model_name: str,
    usage: dict[str, int] | None,
    pricing_path: str | Path | None = None,
) -> dict[str, Any] | None:
    if usage is None:
        return None
    pricing = resolve_model_pricing(model_name, pricing_path=pricing_path)
    if pricing is None:
        return None
    billable_input_tokens = int(usage.get("billable_input_tokens", 0))
    cached_input_tokens = int(usage.get("cached_input_tokens", 0))
    output_tokens = int(usage.get("output_tokens", 0))
    input_cost_usd = (billable_input_tokens / 1_000_000) * pricing.input_per_1m
    cached_input_cost_usd = (cached_input_tokens / 1_000_000) * pricing.cached_input_per_1m
    output_cost_usd = (output_tokens / 1_000_000) * pricing.output_per_1m
    total_cost_usd = input_cost_usd + cached_input_cost_usd + output_cost_usd
    return {
        "model": model_name,
        "currency": "USD",
        "rates_per_1m": {
            "input": pricing.input_per_1m,
            "cached_input": pricing.cached_input_per_1m,
            "output": pricing.output_per_1m,
        },
        "tokens": {
            "billable_input": billable_input_tokens,
            "cached_input": cached_input_tokens,
            "output": output_tokens,
            "total": int(usage.get("total_tokens", billable_input_tokens + cached_input_tokens + output_tokens)),
        },
        "cost_usd": {
            "input": round(input_cost_usd, 10),
            "cached_input": round(cached_input_cost_usd, 10),
            "output": round(output_cost_usd, 10),
            "total": round(total_cost_usd, 10),
        },
        "source": pricing.source,
        "updated_at": pricing.updated_at,
    }


def resolve_model_pricing(
    model_name: str,
    *,
    pricing_path: str | Path | None = None,
) -> ModelPricing | None:
    if not model_name:
        return None
    loaded = load_pricing_table(pricing_path)
    models = loaded.get("models")
    if not isinstance(models, dict):
        return None
    normalized = model_name.strip().lower()
    exact = models.get(normalized)
    if isinstance(exact, dict):
        return _parse_pricing_row(exact, loaded)
    prefix_matches = sorted(
        (key for key in models.keys() if isinstance(key, str) and normalized.startswith(key)),
        key=len,
        reverse=True,
    )
    for key in prefix_matches:
        row = models.get(key)
        if isinstance(row, dict):
            return _parse_pricing_row(row, loaded)
    return None


def load_pricing_table(pricing_path: str | Path | None = None) -> dict[str, Any]:
    path = _resolve_pricing_path(pricing_path)
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    return raw


def _resolve_pricing_path(pricing_path: str | Path | None) -> Path:
    if pricing_path is not None:
        return Path(pricing_path).resolve()
    env_value = os.getenv(MODEL_PRICING_ENV_VAR)
    if env_value:
        return Path(env_value).resolve()
    return DEFAULT_MODEL_PRICING_CONFIG.resolve()


def _parse_pricing_row(row: dict[str, Any], table: dict[str, Any]) -> ModelPricing | None:
    input_per_1m = _as_float(row.get("input_per_1m"))
    cached_input_per_1m = _as_float(row.get("cached_input_per_1m"))
    output_per_1m = _as_float(row.get("output_per_1m"))
    if input_per_1m is None or cached_input_per_1m is None or output_per_1m is None:
        return None
    source = _as_string(row.get("source")) or _as_string(table.get("source"))
    updated_at = _as_string(row.get("updated_at")) or _as_string(table.get("updated_at"))
    return ModelPricing(
        input_per_1m=input_per_1m,
        cached_input_per_1m=cached_input_per_1m,
        output_per_1m=output_per_1m,
        source=source,
        updated_at=updated_at,
    )


def _usage_value(value: Any, *names: str) -> Any:
    for name in names:
        if isinstance(value, dict) and name in value:
            return value[name]
        if value is not None and hasattr(value, name):
            return getattr(value, name)
    return None


def _as_non_negative_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return max(number, 0)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None

