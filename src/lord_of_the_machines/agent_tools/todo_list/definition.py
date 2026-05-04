from __future__ import annotations

from lord_of_the_machines.llm.tool_definitions import ToolDefinition, ToolMethodDefinition


def build_definition(tool_name: str) -> ToolDefinition:
    return ToolDefinition(
        name=tool_name,
        description=(
            "Manage TODO lists for multiple agents using files on disk. "
            "Create lists, add tasks, mark/unmark completion, remove tasks, and inspect progress."
        ),
        internal=True,
        methods=[
            ToolMethodDefinition(
                name="list_agents",
                description="List agents that currently have TODO list directories.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {},
                    "required": [],
                },
            ),
            ToolMethodDefinition(
                name="list_todo_lists",
                description="List TODO list files for one agent and show per-list progress counts.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "agent_id": {"type": "string"},
                    },
                    "required": ["agent_id"],
                },
            ),
            ToolMethodDefinition(
                name="create_todo_list",
                description="Create a TODO list file for an agent, optionally with initial tasks.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "agent_id": {"type": "string"},
                        "list_name": {"type": "string"},
                        "title": {"type": "string"},
                        "tasks": {"type": "array", "items": {"type": "string"}},
                        "overwrite": {"type": "boolean"},
                    },
                    "required": ["agent_id", "list_name"],
                },
            ),
            ToolMethodDefinition(
                name="get_todo_list",
                description="Open one TODO list file and return its tasks with completion state.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "agent_id": {"type": "string"},
                        "list_name": {"type": "string"},
                    },
                    "required": ["agent_id", "list_name"],
                },
            ),
            ToolMethodDefinition(
                name="add_todo_items",
                description="Add one or more tasks to an existing TODO list.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "agent_id": {"type": "string"},
                        "list_name": {"type": "string"},
                        "tasks": {"type": "array", "items": {"type": "string"}},
                        "position": {"type": "string", "enum": ["start", "end"]},
                    },
                    "required": ["agent_id", "list_name", "tasks"],
                },
            ),
            ToolMethodDefinition(
                name="update_todo_item",
                description="Update a task text and/or completion status. Use completed=false to unmark.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "agent_id": {"type": "string"},
                        "list_name": {"type": "string"},
                        "item_id": {"type": "string"},
                        "completed": {"type": "boolean"},
                        "text": {"type": "string"},
                    },
                    "required": ["agent_id", "list_name", "item_id"],
                },
            ),
            ToolMethodDefinition(
                name="remove_todo_item",
                description="Remove one task from a TODO list.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "agent_id": {"type": "string"},
                        "list_name": {"type": "string"},
                        "item_id": {"type": "string"},
                    },
                    "required": ["agent_id", "list_name", "item_id"],
                },
            ),
            ToolMethodDefinition(
                name="delete_todo_list",
                description="Delete one TODO list file.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "agent_id": {"type": "string"},
                        "list_name": {"type": "string"},
                    },
                    "required": ["agent_id", "list_name"],
                },
            ),
        ],
    )

