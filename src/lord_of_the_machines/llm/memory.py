from __future__ import annotations

import copy
import json
from typing import Any


def remember(memory: list[Any], arguments: dict[str, Any]) -> tuple[list[Any], dict[str, Any]]:
    key = str(arguments.get("key") or f"memory_{len(memory) + 1}").strip()
    value = str(arguments.get("value") or "").strip()
    importance = arguments.get("importance") or "normal"
    record = {
        "key": key,
        "value": value,
        "importance": importance,
    }
    updated_memory = [
        item
        for item in memory
        if not (isinstance(item, dict) and item.get("key") == key)
    ]
    updated_memory.append(record)
    return updated_memory, {"remembered": True, "key": key}


def recall(memory: list[Any], arguments: dict[str, Any]) -> dict[str, Any]:
    key = arguments.get("key")
    query = str(arguments.get("query") or "").lower()
    records = []

    for item in memory:
        if isinstance(item, dict):
            if key and item.get("key") != key:
                continue
            if query and query not in json.dumps(item, ensure_ascii=False).lower():
                continue
            records.append(copy.deepcopy(item))
            continue

        item_text = str(item)
        if key:
            continue
        if query and query not in item_text.lower():
            continue
        records.append(item_text)

    return {"records": records}


def forget(memory: list[Any], arguments: dict[str, Any]) -> tuple[list[Any], dict[str, Any]]:
    key = arguments.get("key")
    updated_memory = [
        item
        for item in memory
        if not (isinstance(item, dict) and item.get("key") == key)
    ]
    return updated_memory, {"forgotten": len(memory) - len(updated_memory), "key": key}
