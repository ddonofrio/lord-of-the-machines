from __future__ import annotations

from lord_of_the_machines.llm.tool_definitions import ToolDefinition, ToolMethodDefinition


def build_definition(tool_name: str) -> ToolDefinition:
    return ToolDefinition(
        name=tool_name,
        description=(
            "Persistent mission registry with lifecycle status, phase tracking, and role assignments. "
            "Use it to discover pending missions and coordinate ownership."
        ),
        internal=True,
        methods=[
            ToolMethodDefinition(
                name="create_mission",
                description="Create a mission entry with initial metadata and lifecycle status.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "mission_id": {"type": "string"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "initial_status": {"type": "string"},
                        "metadata": {"type": "object"},
                    },
                    "required": ["title", "description"],
                },
            ),
            ToolMethodDefinition(
                name="list_missions",
                description="List missions, optionally filtered by status.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "statuses": {"type": "array", "items": {"type": "string"}},
                        "limit": {"type": "integer"},
                    },
                    "required": [],
                },
            ),
            ToolMethodDefinition(
                name="get_mission",
                description="Load one mission by id.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"mission_id": {"type": "string"}},
                    "required": ["mission_id"],
                },
            ),
            ToolMethodDefinition(
                name="update_mission_status",
                description="Update mission lifecycle status.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "mission_id": {"type": "string"},
                        "status": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["mission_id", "status"],
                },
            ),
            ToolMethodDefinition(
                name="update_mission_phase",
                description="Update per-phase status and optional phase notes.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "mission_id": {"type": "string"},
                        "phase": {"type": "string"},
                        "status": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                    "required": ["mission_id", "phase", "status"],
                },
            ),
            ToolMethodDefinition(
                name="assign_mission_role",
                description="Assign one agent id to a role for a mission.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "mission_id": {"type": "string"},
                        "role": {"type": "string"},
                        "agent_id": {"type": "string"},
                    },
                    "required": ["mission_id", "role", "agent_id"],
                },
            ),
            ToolMethodDefinition(
                name="unassign_mission_role",
                description="Remove one agent id from a mission role assignment.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "mission_id": {"type": "string"},
                        "role": {"type": "string"},
                        "agent_id": {"type": "string"},
                    },
                    "required": ["mission_id", "role", "agent_id"],
                },
            ),
        ],
    )

