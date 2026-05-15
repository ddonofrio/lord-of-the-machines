from __future__ import annotations

from lord_of_the_machines.llm.tool_definitions import ToolDefinition, ToolMethodDefinition


def build_definition(tool_name: str) -> ToolDefinition:
    return ToolDefinition(
        name=tool_name,
        description=(
            "Kanban board backed by markdown task files on disk. "
            "Use columns as workflow stages and move tasks across columns."
        ),
        internal=True,
        methods=[
            ToolMethodDefinition(
                name="list_columns",
                description="List board columns with task counts.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {},
                    "required": [],
                },
            ),
            ToolMethodDefinition(
                name="list_tasks",
                description="List tasks for one column or for the entire board.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "column": {"type": "string"},
                        "include_body": {"type": "boolean"},
                        "statuses": {"type": "array", "items": {"type": "string"}},
                        "owner": {"type": "string"},
                        "task_type": {"type": "string"},
                        "priorities": {"type": "array", "items": {"type": "string"}},
                        "assignee_role": {"type": "string"},
                        "mission_id": {"type": "string"},
                    },
                    "required": [],
                },
            ),
            ToolMethodDefinition(
                name="create_task",
                description="Create a markdown task file in a column.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "column": {"type": "string"},
                        "task_id": {"type": "string"},
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "status": {"type": "string"},
                        "owner": {"type": "string"},
                        "priority": {"type": "string"},
                        "task_type": {"type": "string"},
                        "depends_on": {"type": "array", "items": {"type": "string"}},
                        "assignee_role": {"type": "string"},
                        "metadata": {"type": "object"},
                        "overwrite": {"type": "boolean"},
                    },
                    "required": ["column", "title"],
                },
            ),
            ToolMethodDefinition(
                name="get_task",
                description="Load one task by task id.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "task_id": {"type": "string"},
                        "column": {"type": "string"},
                        "include_body": {"type": "boolean"},
                    },
                    "required": ["task_id"],
                },
            ),
            ToolMethodDefinition(
                name="claim_next_task",
                description="Claim the first available task in a column for one agent.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "column": {"type": "string"},
                        "agent_id": {"type": "string"},
                        "agent_role": {"type": "string"},
                        "statuses": {"type": "array", "items": {"type": "string"}},
                        "claimed_status": {"type": "string"},
                        "respect_dependencies": {"type": "boolean"},
                        "done_statuses": {"type": "array", "items": {"type": "string"}},
                        "allow_assignee_role_mismatch": {"type": "boolean"},
                    },
                    "required": ["column", "agent_id"],
                },
            ),
            ToolMethodDefinition(
                name="move_task",
                description="Move one task file from its current column into another column.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "task_id": {"type": "string"},
                        "to_column": {"type": "string"},
                        "from_column": {"type": "string"},
                        "actor": {"type": "string"},
                        "status": {"type": "string"},
                        "note": {"type": "string"},
                    },
                    "required": ["task_id", "to_column"],
                },
            ),
            ToolMethodDefinition(
                name="append_task_note",
                description="Append a markdown note to an existing task.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "task_id": {"type": "string"},
                        "note": {"type": "string"},
                        "column": {"type": "string"},
                        "actor": {"type": "string"},
                    },
                    "required": ["task_id", "note"],
                },
            ),
            ToolMethodDefinition(
                name="update_task",
                description=(
                    "Update task fields in-place (status, owner, priority, dependencies, "
                    "assignee role, metadata), without moving columns."
                ),
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "task_id": {"type": "string"},
                        "column": {"type": "string"},
                        "actor": {"type": "string"},
                        "status": {"type": "string"},
                        "owner": {"type": "string"},
                        "clear_owner": {"type": "boolean"},
                        "priority": {"type": "string"},
                        "task_type": {"type": "string"},
                        "depends_on": {"type": "array", "items": {"type": "string"}},
                        "assignee_role": {"type": "string"},
                        "clear_assignee_role": {"type": "boolean"},
                        "metadata_merge": {"type": "object"},
                        "note": {"type": "string"},
                    },
                    "required": ["task_id"],
                },
            ),
        ],
    )
