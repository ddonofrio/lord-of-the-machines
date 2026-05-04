from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lord_of_the_machines.agent_tools.todo_list.config import TodoListToolConfig
from lord_of_the_machines.agent_tools.todo_list.contracts import (
    AddTodoItemsRequest,
    CreateTodoListRequest,
    DeleteTodoListRequest,
    GetTodoListRequest,
    ListAgentsRequest,
    ListTodoListsRequest,
    RemoveTodoItemRequest,
    TodoItem,
    TodoListDocument,
    UpdateTodoItemRequest,
)
from lord_of_the_machines.agent_tools.todo_list.definition import build_definition
from lord_of_the_machines.llm.base_agent import BaseAgent
from lord_of_the_machines.llm.tool_definitions import ToolDefinition
from lord_of_the_machines.llm.tools import ToolHandler


SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


class TodoListTool:
    TOOL_NAME = "todo_list"

    def __init__(self, root_path: str | Path, *, config: TodoListToolConfig | None = None) -> None:
        self.config = config or TodoListToolConfig(root_path=Path(root_path))

    def install(self, agent: BaseAgent) -> None:
        agent.add_tool(self.definition(), handlers=self.handlers())

    def definition(self) -> ToolDefinition:
        return build_definition(self.TOOL_NAME)

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "list_agents": self._list_agents,
            "list_todo_lists": self._list_todo_lists,
            "create_todo_list": self._create_todo_list,
            "get_todo_list": self._get_todo_list,
            "add_todo_items": self._add_todo_items,
            "update_todo_item": self._update_todo_item,
            "remove_todo_item": self._remove_todo_item,
            "delete_todo_list": self._delete_todo_list,
        }

    def _list_agents(self, arguments: dict[str, Any]) -> dict[str, Any]:
        ListAgentsRequest.from_mapping(arguments)
        agents = []
        for agent_dir in sorted(self.config.root_path.iterdir(), key=lambda path: path.name.lower()):
            if not agent_dir.is_dir():
                continue
            lists = self._list_paths_for_agent(agent_dir.name)
            open_tasks = 0
            completed_tasks = 0
            for list_path in lists:
                document = self._load_document(list_path)
                for item in document.items:
                    if item.completed:
                        completed_tasks += 1
                    else:
                        open_tasks += 1
            agents.append(
                {
                    "agent_id": agent_dir.name,
                    "todo_lists": len(lists),
                    "open_tasks": open_tasks,
                    "completed_tasks": completed_tasks,
                }
            )
        return {"root_path": str(self.config.root_path), "agents": agents}

    def _list_todo_lists(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = ListTodoListsRequest.from_mapping(arguments)
        agent_id = self._safe_name(request.agent_id, field_name="agent_id")
        agent_dir = self._agent_dir(agent_id)
        if not agent_dir.exists():
            return {"agent_id": agent_id, "lists": []}
        lists = []
        for list_path in self._list_paths_for_agent(agent_id):
            document = self._load_document(list_path)
            total = len(document.items)
            completed = sum(1 for item in document.items if item.completed)
            lists.append(
                {
                    "list_name": document.list_name,
                    "title": document.title,
                    "total_tasks": total,
                    "completed_tasks": completed,
                    "open_tasks": total - completed,
                    "updated_at": document.updated_at,
                    "path": self._relative_to_root(list_path),
                }
            )
        return {"agent_id": agent_id, "lists": lists}

    def _create_todo_list(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = CreateTodoListRequest.from_mapping(arguments)
        agent_id = self._safe_name(request.agent_id, field_name="agent_id")
        list_name = self._safe_name(request.list_name, field_name="list_name")
        list_path = self._list_path(agent_id, list_name)

        agent_dir = self._agent_dir(agent_id)
        agent_dir.mkdir(parents=True, exist_ok=True)
        if not request.overwrite and list_path.exists():
            raise FileExistsError(f"Todo list already exists: {self._relative_to_root(list_path)}")

        existing_lists = self._list_paths_for_agent(agent_id)
        if self.config.max_lists_per_agent is not None and not list_path.exists():
            if len(existing_lists) >= self.config.max_lists_per_agent:
                raise ValueError(
                    f"Agent '{agent_id}' reached max_lists_per_agent={self.config.max_lists_per_agent}."
                )

        created_at = self._utc_now()
        items: list[TodoItem] = []
        next_item_id = 1
        for task in request.tasks:
            items.append(
                TodoItem(
                    item_id=self._format_item_id(next_item_id),
                    text=task,
                    completed=False,
                    created_at=created_at,
                    completed_at=None,
                )
            )
            next_item_id += 1

        self._assert_item_limit(len(items))
        document = TodoListDocument(
            agent_id=agent_id,
            list_name=list_name,
            title=request.title or list_name.replace("_", " ").replace("-", " ").strip().title(),
            created_at=created_at,
            updated_at=created_at,
            next_item_id=next_item_id,
            items=items,
        )
        self._save_document(list_path, document)
        return {
            "created": True,
            "path": self._relative_to_root(list_path),
            "todo_list": self._summarize_document(document, include_items=True),
        }

    def _get_todo_list(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = GetTodoListRequest.from_mapping(arguments)
        document, list_path = self._read_existing_document(request.agent_id, request.list_name)
        return {
            "path": self._relative_to_root(list_path),
            "todo_list": self._summarize_document(document, include_items=True),
        }

    def _add_todo_items(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = AddTodoItemsRequest.from_mapping(arguments)
        document, list_path = self._read_existing_document(request.agent_id, request.list_name)
        position = request.position.lower()
        if position not in {"start", "end"}:
            raise ValueError("position must be 'start' or 'end'.")

        now = self._utc_now()
        new_items = []
        for task in request.tasks:
            new_items.append(
                TodoItem(
                    item_id=self._format_item_id(document.next_item_id),
                    text=task,
                    completed=False,
                    created_at=now,
                    completed_at=None,
                )
            )
            document.next_item_id += 1

        if position == "start":
            document.items = [*new_items, *document.items]
        else:
            document.items.extend(new_items)
        self._assert_item_limit(len(document.items))
        document.updated_at = now
        self._save_document(list_path, document)
        return {
            "added_items": [item.to_mapping() for item in new_items],
            "todo_list": self._summarize_document(document, include_items=True),
        }

    def _update_todo_item(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = UpdateTodoItemRequest.from_mapping(arguments)
        document, list_path = self._read_existing_document(request.agent_id, request.list_name)

        item = self._find_item(document, request.item_id)
        if item is None:
            raise ValueError(f"Todo item '{request.item_id}' not found.")

        now = self._utc_now()
        if request.text is not None:
            item.text = request.text
        if request.completed is not None:
            item.completed = request.completed
            item.completed_at = now if request.completed else None

        document.updated_at = now
        self._save_document(list_path, document)
        return {
            "updated_item": item.to_mapping(),
            "todo_list": self._summarize_document(document, include_items=True),
        }

    def _remove_todo_item(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = RemoveTodoItemRequest.from_mapping(arguments)
        document, list_path = self._read_existing_document(request.agent_id, request.list_name)

        removed_item: TodoItem | None = None
        remaining_items: list[TodoItem] = []
        for item in document.items:
            if item.item_id == request.item_id and removed_item is None:
                removed_item = item
                continue
            remaining_items.append(item)
        if removed_item is None:
            raise ValueError(f"Todo item '{request.item_id}' not found.")

        document.items = remaining_items
        document.updated_at = self._utc_now()
        self._save_document(list_path, document)
        return {
            "removed_item": removed_item.to_mapping(),
            "todo_list": self._summarize_document(document, include_items=True),
        }

    def _delete_todo_list(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = DeleteTodoListRequest.from_mapping(arguments)
        _, list_path = self._read_existing_document(request.agent_id, request.list_name)
        list_path.unlink()
        return {"deleted": True, "path": self._relative_to_root(list_path)}

    def _read_existing_document(self, raw_agent_id: str, raw_list_name: str) -> tuple[TodoListDocument, Path]:
        agent_id = self._safe_name(raw_agent_id, field_name="agent_id")
        list_name = self._safe_name(raw_list_name, field_name="list_name")
        list_path = self._list_path(agent_id, list_name)
        if not list_path.exists():
            raise FileNotFoundError(f"Todo list does not exist: {self._relative_to_root(list_path)}")
        return self._load_document(list_path), list_path

    def _list_paths_for_agent(self, agent_id: str) -> list[Path]:
        agent_dir = self._agent_dir(agent_id)
        if not agent_dir.exists():
            return []
        return sorted(
            [
                path
                for path in agent_dir.iterdir()
                if path.is_file() and path.name.endswith(self.config.list_extension)
            ],
            key=lambda path: path.name.lower(),
        )

    def _load_document(self, path: Path) -> TodoListDocument:
        raw = json.loads(path.read_text(encoding="utf-8"))
        document = TodoListDocument.from_mapping(raw)
        return document

    def _save_document(self, path: Path, document: TodoListDocument) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document.to_mapping(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _summarize_document(self, document: TodoListDocument, *, include_items: bool) -> dict[str, Any]:
        total = len(document.items)
        completed = sum(1 for item in document.items if item.completed)
        payload: dict[str, Any] = {
            "agent_id": document.agent_id,
            "list_name": document.list_name,
            "title": document.title,
            "created_at": document.created_at,
            "updated_at": document.updated_at,
            "total_tasks": total,
            "completed_tasks": completed,
            "open_tasks": total - completed,
        }
        if include_items:
            payload["items"] = [item.to_mapping() for item in document.items]
        return payload

    def _find_item(self, document: TodoListDocument, item_id: str) -> TodoItem | None:
        for item in document.items:
            if item.item_id == item_id:
                return item
        return None

    def _assert_item_limit(self, items_count: int) -> None:
        if self.config.max_items_per_list is not None and items_count > self.config.max_items_per_list:
            raise ValueError(f"Todo list reached max_items_per_list={self.config.max_items_per_list}.")

    def _agent_dir(self, agent_id: str) -> Path:
        return (self.config.root_path / agent_id).resolve()

    def _list_path(self, agent_id: str, list_name: str) -> Path:
        path = (self._agent_dir(agent_id) / f"{list_name}{self.config.list_extension}").resolve()
        if not self._is_within_root(path):
            raise ValueError("Resolved todo list path is outside configured root.")
        return path

    def _is_within_root(self, path: Path) -> bool:
        try:
            path.relative_to(self.config.root_path)
            return True
        except ValueError:
            return False

    def _relative_to_root(self, path: Path) -> str:
        return path.relative_to(self.config.root_path).as_posix()

    def _safe_name(self, value: str, *, field_name: str) -> str:
        if not SAFE_NAME_RE.fullmatch(value):
            raise ValueError(
                f"{field_name} must match {SAFE_NAME_RE.pattern} "
                "(letters, numbers, underscore, hyphen; max 64 chars)."
            )
        return value

    def _utc_now(self) -> str:
        return datetime.now(tz=timezone.utc).isoformat()

    @staticmethod
    def _format_item_id(value: int) -> str:
        return f"T-{value:04d}"

