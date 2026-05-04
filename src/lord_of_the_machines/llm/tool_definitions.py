from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


DEFAULT_ARGUMENTS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {},
    "required": [],
}


@dataclass(slots=True)
class ToolMethodDefinition:
    name: str
    description: str = ""
    arguments_schema: dict[str, Any] = field(default_factory=lambda: copy.deepcopy(DEFAULT_ARGUMENTS_SCHEMA))
    extra_fields: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> ToolMethodDefinition:
        if not isinstance(value, dict):
            raise TypeError("Tool method definition must be a dictionary.")
        extra_fields = {
            key: copy.deepcopy(item)
            for key, item in value.items()
            if key not in {"name", "description", "arguments_schema"}
        }
        return cls(
            name=str(value.get("name") or ""),
            description=str(value.get("description") or ""),
            arguments_schema=copy.deepcopy(value.get("arguments_schema") or DEFAULT_ARGUMENTS_SCHEMA),
            extra_fields=extra_fields,
        )

    def to_mapping(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "description": self.description,
            "arguments_schema": copy.deepcopy(self.arguments_schema),
        }
        payload.update(copy.deepcopy(self.extra_fields))
        return payload


@dataclass(slots=True)
class ToolDefinition:
    name: str
    description: str = ""
    methods: list[ToolMethodDefinition] = field(default_factory=list)
    internal: bool = False
    single_round: bool = False
    extra_fields: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> ToolDefinition:
        if not isinstance(value, dict):
            raise TypeError("Tool definition must be a dictionary.")
        extra_fields = {
            key: copy.deepcopy(item)
            for key, item in value.items()
            if key not in {"name", "description", "methods", "internal", "single_round"}
        }
        methods = value.get("methods") or []
        return cls(
            name=str(value.get("name") or ""),
            description=str(value.get("description") or ""),
            methods=[ensure_tool_method_definition(method) for method in methods],
            internal=bool(value.get("internal", False)),
            single_round=bool(value.get("single_round", False)),
            extra_fields=extra_fields,
        )

    def to_mapping(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "description": self.description,
            "methods": [method.to_mapping() for method in self.methods],
        }
        if self.internal:
            payload["internal"] = True
        if self.single_round:
            payload["single_round"] = True
        payload.update(copy.deepcopy(self.extra_fields))
        return payload

    def method(self, method_name: str) -> ToolMethodDefinition | None:
        for method in self.methods:
            if method.name == method_name:
                return method
        return None


def ensure_tool_method_definition(value: ToolMethodDefinition | dict[str, Any]) -> ToolMethodDefinition:
    if isinstance(value, ToolMethodDefinition):
        return copy.deepcopy(value)
    return ToolMethodDefinition.from_mapping(value)


def ensure_tool_definition(value: ToolDefinition | dict[str, Any]) -> ToolDefinition:
    if isinstance(value, ToolDefinition):
        return copy.deepcopy(value)
    return ToolDefinition.from_mapping(value)


def ensure_tool_definitions(values: list[ToolDefinition | dict[str, Any]] | tuple[ToolDefinition | dict[str, Any], ...]) -> list[ToolDefinition]:
    return [ensure_tool_definition(value) for value in values]


def tool_definitions_to_mappings(values: list[ToolDefinition] | tuple[ToolDefinition, ...]) -> list[dict[str, Any]]:
    return [value.to_mapping() for value in values]
