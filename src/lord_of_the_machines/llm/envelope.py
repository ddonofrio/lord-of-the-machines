from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any


DEFAULT_MEMORY_INSTRUCTION = (
    "These are your current memories. You may include memory.forget tool calls "
    "for memories that are obsolete, false, duplicated, or no longer useful."
)


@dataclass(slots=True)
class EnvelopeField:
    """One top-level input field in the agent protocol envelope.

    The source tells the envelope builder where the value comes from. Supported
    default sources are protocol, system, conversation_history, runtime_context,
    user, output_contract, and literal.
    """

    name: str
    source: str
    required: bool = True
    default: Any = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> EnvelopeField:
        return cls(
            name=str(value["name"]),
            source=str(value.get("source") or value["name"]),
            required=bool(value.get("required", True)),
            default=copy.deepcopy(value.get("default")),
        )

    def to_mapping(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "source": self.source,
            "required": self.required,
        }
        if self.default is not None:
            payload["default"] = copy.deepcopy(self.default)
        return payload


@dataclass(slots=True)
class ToolCallOutputSpec:
    """Names and shape for the model's structured tool-call output."""

    calls_field: str = "calls"
    tool_field: str = "tool"
    method_field: str = "method"
    arguments_field: str = "arguments"
    allow_root_list: bool = True
    min_calls: int = 1

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> ToolCallOutputSpec:
        value = value or {}
        return cls(
            calls_field=str(value.get("calls_field") or "calls"),
            tool_field=str(value.get("tool_field") or "tool"),
            method_field=str(value.get("method_field") or "method"),
            arguments_field=str(value.get("arguments_field") or "arguments"),
            allow_root_list=bool(value.get("allow_root_list", True)),
            min_calls=max(0, int(value.get("min_calls", 1))),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "type": "tool_call_list",
            "calls_field": self.calls_field,
            "tool_field": self.tool_field,
            "method_field": self.method_field,
            "arguments_field": self.arguments_field,
            "allow_root_list": self.allow_root_list,
            "min_calls": self.min_calls,
        }

    def call_required_fields(self) -> list[str]:
        return [self.tool_field, self.method_field, self.arguments_field]

    def required_json_shape(self) -> dict[str, Any]:
        return {
            self.calls_field: [
                {
                    self.tool_field: "tool_name",
                    self.method_field: "method_name",
                    self.arguments_field: {},
                }
            ]
        }


def default_envelope_fields() -> list[EnvelopeField]:
    return [
        EnvelopeField("protocol", "protocol"),
        EnvelopeField("system", "system"),
        EnvelopeField("conversation_history", "conversation_history"),
        EnvelopeField("runtime_context", "runtime_context"),
        EnvelopeField("user", "user"),
        EnvelopeField("output_contract", "output_contract"),
    ]


@dataclass(slots=True)
class AgentEnvelopeSpec:
    """Configurable LLM protocol envelope.

    This object is the explicit contract between the caller and the model. It
    controls which top-level input fields are sent and which output fields the
    parser expects.
    """

    enabled: bool = True
    version: str = "lord_of_the_machines.agent.v1"
    instructions: str = ""
    input_fields: list[EnvelopeField] = field(default_factory=default_envelope_fields)
    output: ToolCallOutputSpec = field(default_factory=ToolCallOutputSpec)
    runtime_context_extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> AgentEnvelopeSpec:
        value = value or {}
        input_fields = value.get("input_fields")
        return cls(
            enabled=bool(value.get("enabled", True)),
            version=str(value.get("version") or "lord_of_the_machines.agent.v1"),
            instructions=str(value.get("instructions") or ""),
            input_fields=[
                EnvelopeField.from_mapping(item)
                for item in input_fields
            ]
            if isinstance(input_fields, list)
            else default_envelope_fields(),
            output=ToolCallOutputSpec.from_mapping(value.get("output")),
            runtime_context_extra=copy.deepcopy(value.get("runtime_context_extra") or {}),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "version": self.version,
            "instructions": self.instructions,
            "input_fields": [field.to_mapping() for field in self.input_fields],
            "output": self.output.to_mapping(),
            "runtime_context_extra": copy.deepcopy(self.runtime_context_extra),
        }

    def build(
        self,
        *,
        system_prompt: str | None,
        context_mode: str,
        history: list[dict[str, Any]],
        memory: list[Any],
        tools: list[dict[str, Any]],
        message: Any,
        memory_instruction: str = DEFAULT_MEMORY_INSTRUCTION,
    ) -> dict[str, Any]:
        runtime_context = {
            "memory": copy.deepcopy(memory),
            "memory_instruction": memory_instruction,
            "available_tools": copy.deepcopy(tools),
        }
        runtime_context.update(copy.deepcopy(self.runtime_context_extra))

        source_values = {
            "protocol": self.version,
            "system": {
                "prompt_is_injected_via_instructions": bool(system_prompt),
                "history_mode": context_mode,
            },
            "conversation_history": copy.deepcopy(history),
            "runtime_context": runtime_context,
            "user": {"prompt": copy.deepcopy(message)},
            "output_contract": {
                "type": "tool_call_list",
                "required_json_shape": self.output.required_json_shape(),
            },
        }

        envelope: dict[str, Any] = {}
        for field_spec in self.input_fields:
            if field_spec.source == "literal":
                value = copy.deepcopy(field_spec.default)
            else:
                value = source_values.get(field_spec.source, copy.deepcopy(field_spec.default))
            if value is None and field_spec.required:
                raise ValueError(f"Envelope field '{field_spec.name}' has no value for source '{field_spec.source}'.")
            if value is not None or field_spec.required:
                envelope[field_spec.name] = value
        return envelope

    def cache_identity(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "input_fields": [field.to_mapping() for field in self.input_fields],
            "output": self.output.to_mapping(),
            "runtime_context_extra": self.runtime_context_extra,
        }
