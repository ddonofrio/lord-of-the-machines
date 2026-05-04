from __future__ import annotations

from lord_of_the_machines.llm.tool_definitions import ToolDefinition, ToolMethodDefinition


def build_definition(tool_name: str) -> ToolDefinition:
    return ToolDefinition(
        name=tool_name,
        description=(
            "Persistent event bus with publish, filtered list, consumer offsets and acknowledgements. "
            "Use it to drive mission phases through events."
        ),
        internal=True,
        methods=[
            ToolMethodDefinition(
                name="publish_event",
                description="Append a new event to the bus stream.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "topic": {"type": "string"},
                        "mission_id": {"type": "string"},
                        "producer_role": {"type": "string"},
                        "correlation_id": {"type": "string"},
                        "causation_id": {"type": "string"},
                        "payload": {"type": "object"},
                    },
                    "required": ["topic"],
                },
            ),
            ToolMethodDefinition(
                name="list_events",
                description="List events with optional topic/mission/sequence filters.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "topics": {"type": "array", "items": {"type": "string"}},
                        "mission_id": {"type": "string"},
                        "after_sequence": {"type": "integer"},
                        "limit": {"type": "integer"},
                    },
                    "required": [],
                },
            ),
            ToolMethodDefinition(
                name="consume_events",
                description="Read unacked events for a consumer from its offset, with optional topic filter.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "consumer_id": {"type": "string"},
                        "topics": {"type": "array", "items": {"type": "string"}},
                        "limit": {"type": "integer"},
                    },
                    "required": ["consumer_id"],
                },
            ),
            ToolMethodDefinition(
                name="ack_event",
                description="Advance a consumer offset by event id or sequence.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "consumer_id": {"type": "string"},
                        "event_id": {"type": "string"},
                        "sequence": {"type": "integer"},
                    },
                    "required": ["consumer_id"],
                },
            ),
            ToolMethodDefinition(
                name="get_consumer_state",
                description="Return current ack offset for one consumer.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "consumer_id": {"type": "string"},
                    },
                    "required": ["consumer_id"],
                },
            ),
        ],
    )

