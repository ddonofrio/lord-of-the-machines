from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Self


class MappingModel:
    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)


def _ensure_mapping(value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Tool arguments must be a JSON object.")
    return value


def _require_string(values: dict[str, Any], field_name: str) -> str:
    value = values.get(field_name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value


def _optional_string(values: dict[str, Any], field_name: str) -> str | None:
    value = values.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    return value


def _optional_bool(values: dict[str, Any], field_name: str, default: bool) -> bool:
    value = values.get(field_name)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean.")
    return value


def _optional_string_list(values: dict[str, Any], field_name: str) -> list[str]:
    value = values.get(field_name)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{field_name} must be a list of non-empty strings.")
    return list(value)


@dataclass(slots=True)
class TodoItem(MappingModel):
    item_id: str
    text: str
    completed: bool
    created_at: str
    completed_at: str | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> Self:
        values = _ensure_mapping(value)
        return cls(
            item_id=_require_string(values, "item_id"),
            text=_require_string(values, "text"),
            completed=bool(values.get("completed", False)),
            created_at=_require_string(values, "created_at"),
            completed_at=_optional_string(values, "completed_at"),
        )


@dataclass(slots=True)
class TodoListDocument(MappingModel):
    agent_id: str
    list_name: str
    title: str
    created_at: str
    updated_at: str
    next_item_id: int
    items: list[TodoItem] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> Self:
        values = _ensure_mapping(value)
        items_raw = values.get("items") or []
        if not isinstance(items_raw, list):
            raise ValueError("items must be a list.")
        return cls(
            agent_id=_require_string(values, "agent_id"),
            list_name=_require_string(values, "list_name"),
            title=_require_string(values, "title"),
            created_at=_require_string(values, "created_at"),
            updated_at=_require_string(values, "updated_at"),
            next_item_id=int(values.get("next_item_id", 1)),
            items=[TodoItem.from_mapping(item) for item in items_raw],
        )


@dataclass(slots=True)
class ListAgentsRequest:
    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        _ensure_mapping(value)
        return cls()


@dataclass(slots=True)
class ListTodoListsRequest:
    agent_id: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(agent_id=_require_string(values, "agent_id"))


@dataclass(slots=True)
class CreateTodoListRequest:
    agent_id: str
    list_name: str
    title: str | None = None
    tasks: list[str] = field(default_factory=list)
    overwrite: bool = False

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(
            agent_id=_require_string(values, "agent_id"),
            list_name=_require_string(values, "list_name"),
            title=_optional_string(values, "title"),
            tasks=_optional_string_list(values, "tasks"),
            overwrite=_optional_bool(values, "overwrite", False),
        )


@dataclass(slots=True)
class GetTodoListRequest:
    agent_id: str
    list_name: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(
            agent_id=_require_string(values, "agent_id"),
            list_name=_require_string(values, "list_name"),
        )


@dataclass(slots=True)
class AddTodoItemsRequest:
    agent_id: str
    list_name: str
    tasks: list[str]
    position: str = "end"

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        tasks = _optional_string_list(values, "tasks")
        if not tasks:
            raise ValueError("tasks must be a non-empty list of strings.")
        return cls(
            agent_id=_require_string(values, "agent_id"),
            list_name=_require_string(values, "list_name"),
            tasks=tasks,
            position=_optional_string(values, "position") or "end",
        )


@dataclass(slots=True)
class UpdateTodoItemRequest:
    agent_id: str
    list_name: str
    item_id: str
    completed: bool | None = None
    text: str | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        completed_raw = values.get("completed")
        if completed_raw is not None and not isinstance(completed_raw, bool):
            raise ValueError("completed must be a boolean when provided.")
        text_value = _optional_string(values, "text")
        if completed_raw is None and text_value is None:
            raise ValueError("At least one of completed or text must be provided.")
        return cls(
            agent_id=_require_string(values, "agent_id"),
            list_name=_require_string(values, "list_name"),
            item_id=_require_string(values, "item_id"),
            completed=completed_raw,
            text=text_value,
        )


@dataclass(slots=True)
class RemoveTodoItemRequest:
    agent_id: str
    list_name: str
    item_id: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(
            agent_id=_require_string(values, "agent_id"),
            list_name=_require_string(values, "list_name"),
            item_id=_require_string(values, "item_id"),
        )


@dataclass(slots=True)
class DeleteTodoListRequest:
    agent_id: str
    list_name: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(
            agent_id=_require_string(values, "agent_id"),
            list_name=_require_string(values, "list_name"),
        )

