from __future__ import annotations

import copy
from typing import Any

from lord_of_the_machines.llm.envelope import ToolCallOutputSpec
from lord_of_the_machines.llm.tool_definitions import ToolDefinition


def normalize_strict_json_schema(schema: dict[str, Any], *, optional: bool = False) -> dict[str, Any]:
    normalized = copy.deepcopy(schema)

    schema_type = normalized.get("type")
    if schema_type == "object" or "properties" in normalized:
        properties = normalized.get("properties") or {}
        original_required = set(normalized.get("required", []))
        normalized["properties"] = {
            name: normalize_strict_json_schema(property_schema, optional=name not in original_required)
            for name, property_schema in properties.items()
        }
        normalized["required"] = list(properties)
        normalized["additionalProperties"] = False
    elif schema_type == "array" and isinstance(normalized.get("items"), dict):
        normalized["items"] = normalize_strict_json_schema(normalized["items"])
    elif "anyOf" in normalized:
        normalized["anyOf"] = [normalize_strict_json_schema(option) for option in normalized["anyOf"]]

    if optional:
        normalized = allow_null_schema(normalized)
    return normalized


def allow_null_schema(schema: dict[str, Any]) -> dict[str, Any]:
    nullable = copy.deepcopy(schema)
    schema_type = nullable.get("type")
    if isinstance(schema_type, str):
        if schema_type != "null":
            nullable["type"] = [schema_type, "null"]
    elif isinstance(schema_type, list):
        if "null" not in schema_type:
            nullable["type"] = [*schema_type, "null"]
    elif "anyOf" in nullable:
        if not any(option.get("type") == "null" for option in nullable["anyOf"] if isinstance(option, dict)):
            nullable["anyOf"] = [*nullable["anyOf"], {"type": "null"}]
    else:
        nullable["type"] = ["object", "null"] if "properties" in nullable else ["string", "null"]
    return nullable


def build_tool_call_schema(
    agent_tools: list[ToolDefinition],
    output_spec: ToolCallOutputSpec,
    verbosity: str,
) -> dict[str, Any]:
    call_schemas = []
    for tool in agent_tools:
        tool_name = tool.name
        if not tool_name:
            continue
        for method in tool.methods:
            method_name = method.name
            if not method_name:
                continue
            arguments_schema = normalize_strict_json_schema(
                method.arguments_schema
                or {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {},
                    "required": [],
                }
            )
            call_schemas.append(
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        output_spec.tool_field: {
                            "type": "string",
                            "enum": [tool_name],
                            "description": "Name of the selected conceptual tool.",
                        },
                        output_spec.method_field: {
                            "type": "string",
                            "enum": [method_name],
                            "description": "Name of the selected method on the tool.",
                        },
                        output_spec.arguments_field: arguments_schema,
                    },
                    "required": output_spec.call_required_fields(),
                }
            )

    if not call_schemas:
        item_schema: dict[str, Any] = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                output_spec.tool_field: {"type": "string"},
                output_spec.method_field: {"type": "string"},
                output_spec.arguments_field: {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {},
                    "required": [],
                },
            },
            "required": output_spec.call_required_fields(),
        }
    elif len(call_schemas) == 1:
        item_schema = call_schemas[0]
    else:
        item_schema = {"anyOf": call_schemas}

    return {
        "format": {
            "type": "json_schema",
            "name": "agent_tool_call_list",
            "description": "An object containing conceptual tool calls selected by the agent.",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    output_spec.calls_field: {
                        "type": "array",
                        "minItems": output_spec.min_calls,
                        "items": item_schema,
                    }
                },
                "required": [output_spec.calls_field],
            },
        },
        "verbosity": verbosity,
    }
