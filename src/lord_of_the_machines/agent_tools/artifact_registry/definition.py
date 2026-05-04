from __future__ import annotations

from lord_of_the_machines.llm.tool_definitions import ToolDefinition, ToolMethodDefinition


def build_definition(tool_name: str) -> ToolDefinition:
    return ToolDefinition(
        name=tool_name,
        description=(
            "Persistent artifact registry for mission documents across phases. "
            "Publish, list, retrieve and update versioned artifacts."
        ),
        internal=True,
        methods=[
            ToolMethodDefinition(
                name="publish_artifact",
                description="Create a new artifact version for a mission and phase.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "mission_id": {"type": "string"},
                        "phase": {"type": "string"},
                        "artifact_type": {"type": "string"},
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "format": {"type": "string"},
                        "producer_role": {"type": "string"},
                        "status": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "metadata": {"type": "object"},
                    },
                    "required": ["mission_id", "phase", "artifact_type", "title", "content"],
                },
            ),
            ToolMethodDefinition(
                name="list_artifacts",
                description="List artifacts by mission, phase, type, status and tags.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "mission_id": {"type": "string"},
                        "phase": {"type": "string"},
                        "artifact_type": {"type": "string"},
                        "statuses": {"type": "array", "items": {"type": "string"}},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": [],
                },
            ),
            ToolMethodDefinition(
                name="get_artifact",
                description="Load one artifact by artifact id.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "artifact_id": {"type": "string"},
                    },
                    "required": ["artifact_id"],
                },
            ),
            ToolMethodDefinition(
                name="update_artifact",
                description="Update an artifact content/metadata/status and create a new version.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "artifact_id": {"type": "string"},
                        "content": {"type": "string"},
                        "title": {"type": "string"},
                        "status": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string"}},
                        "metadata": {"type": "object"},
                    },
                    "required": ["artifact_id"],
                },
            ),
        ],
    )

