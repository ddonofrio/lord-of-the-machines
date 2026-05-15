from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Self

ALLOWED_PRIORITIES = ("P0", "P1", "P2", "P3")


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
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _optional_string(values: dict[str, Any], field_name: str) -> str | None:
    value = values.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    value = value.strip()
    return value or None


def _optional_bool(values: dict[str, Any], field_name: str, default: bool = False) -> bool:
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
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{field_name} must be a list of non-empty strings.")
    return [item.strip() for item in value]


def _optional_mapping(values: dict[str, Any], field_name: str) -> dict[str, Any]:
    value = values.get(field_name)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object.")
    return dict(value)


def _normalize_priority(value: str | None, *, default: str = "P2") -> str:
    candidate = (value or default).strip().upper()
    if candidate not in ALLOWED_PRIORITIES:
        allowed = ", ".join(ALLOWED_PRIORITIES)
        raise ValueError(f"priority must be one of: {allowed}.")
    return candidate


@dataclass(slots=True)
class TaskHistoryEntry(MappingModel):
    at: str
    action: str
    by: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> Self:
        values = _ensure_mapping(value)
        return cls(
            at=_require_string(values, "at"),
            action=_require_string(values, "action"),
            by=_optional_string(values, "by"),
            details=_optional_mapping(values, "details"),
        )


@dataclass(slots=True)
class KanbanTaskMeta(MappingModel):
    task_id: str
    title: str
    status: str
    owner: str | None
    created_at: str
    updated_at: str
    priority: str = "P2"
    task_type: str = "implementation"
    depends_on: list[str] = field(default_factory=list)
    assignee_role: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    history: list[TaskHistoryEntry] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> Self:
        values = _ensure_mapping(value)
        raw_history = values.get("history") or []
        if not isinstance(raw_history, list):
            raise ValueError("history must be a list.")
        return cls(
            task_id=_require_string(values, "task_id"),
            title=_require_string(values, "title"),
            status=_require_string(values, "status"),
            owner=_optional_string(values, "owner"),
            created_at=_require_string(values, "created_at"),
            updated_at=_require_string(values, "updated_at"),
            priority=_normalize_priority(_optional_string(values, "priority"), default="P2"),
            task_type=_optional_string(values, "task_type") or "implementation",
            depends_on=_optional_string_list(values, "depends_on"),
            assignee_role=_optional_string(values, "assignee_role"),
            metadata=_optional_mapping(values, "metadata"),
            history=[TaskHistoryEntry.from_mapping(item) for item in raw_history],
        )


@dataclass(slots=True)
class ListColumnsRequest:
    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        _ensure_mapping(value)
        return cls()


@dataclass(slots=True)
class ListTasksRequest:
    column: str | None = None
    include_body: bool = False
    statuses: list[str] = field(default_factory=list)
    owner: str | None = None
    task_type: str | None = None
    priorities: list[str] = field(default_factory=list)
    assignee_role: str | None = None
    mission_id: str | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        priorities = [item.strip().upper() for item in _optional_string_list(values, "priorities")]
        for priority in priorities:
            _normalize_priority(priority)
        return cls(
            column=_optional_string(values, "column"),
            include_body=_optional_bool(values, "include_body", False),
            statuses=[item.strip().lower() for item in _optional_string_list(values, "statuses")],
            owner=_optional_string(values, "owner"),
            task_type=_optional_string(values, "task_type"),
            priorities=priorities,
            assignee_role=_optional_string(values, "assignee_role"),
            mission_id=_optional_string(values, "mission_id"),
        )


@dataclass(slots=True)
class CreateTaskRequest:
    column: str
    title: str
    description: str
    task_id: str | None = None
    status: str = "ready"
    owner: str | None = None
    priority: str = "P2"
    task_type: str = "implementation"
    depends_on: list[str] = field(default_factory=list)
    assignee_role: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    overwrite: bool = False

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(
            column=_require_string(values, "column"),
            title=_require_string(values, "title"),
            description=_optional_string(values, "description") or "",
            task_id=_optional_string(values, "task_id"),
            status=_optional_string(values, "status") or "ready",
            owner=_optional_string(values, "owner"),
            priority=_normalize_priority(_optional_string(values, "priority"), default="P2"),
            task_type=_optional_string(values, "task_type") or "implementation",
            depends_on=_optional_string_list(values, "depends_on"),
            assignee_role=_optional_string(values, "assignee_role"),
            metadata=_optional_mapping(values, "metadata"),
            overwrite=_optional_bool(values, "overwrite", False),
        )


@dataclass(slots=True)
class GetTaskRequest:
    task_id: str
    column: str | None = None
    include_body: bool = True

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(
            task_id=_require_string(values, "task_id"),
            column=_optional_string(values, "column"),
            include_body=_optional_bool(values, "include_body", True),
        )


@dataclass(slots=True)
class ClaimNextTaskRequest:
    column: str
    agent_id: str
    agent_role: str | None = None
    statuses: list[str] = field(default_factory=lambda: ["ready"])
    claimed_status: str = "in_progress"
    respect_dependencies: bool = True
    done_statuses: list[str] = field(default_factory=lambda: ["done", "completed", "closed"])
    allow_assignee_role_mismatch: bool = False

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        statuses = _optional_string_list(values, "statuses") or ["ready"]
        done_statuses = _optional_string_list(values, "done_statuses") or ["done", "completed", "closed"]
        return cls(
            column=_require_string(values, "column"),
            agent_id=_require_string(values, "agent_id"),
            agent_role=_optional_string(values, "agent_role"),
            statuses=statuses,
            claimed_status=_optional_string(values, "claimed_status") or "in_progress",
            respect_dependencies=_optional_bool(values, "respect_dependencies", True),
            done_statuses=done_statuses,
            allow_assignee_role_mismatch=_optional_bool(values, "allow_assignee_role_mismatch", False),
        )


@dataclass(slots=True)
class MoveTaskRequest:
    task_id: str
    to_column: str
    from_column: str | None = None
    actor: str | None = None
    status: str | None = None
    note: str | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(
            task_id=_require_string(values, "task_id"),
            to_column=_require_string(values, "to_column"),
            from_column=_optional_string(values, "from_column"),
            actor=_optional_string(values, "actor"),
            status=_optional_string(values, "status"),
            note=_optional_string(values, "note"),
        )


@dataclass(slots=True)
class AppendTaskNoteRequest:
    task_id: str
    note: str
    column: str | None = None
    actor: str | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(
            task_id=_require_string(values, "task_id"),
            note=_require_string(values, "note"),
            column=_optional_string(values, "column"),
            actor=_optional_string(values, "actor"),
        )


@dataclass(slots=True)
class UpdateTaskRequest:
    task_id: str
    column: str | None = None
    actor: str | None = None
    status: str | None = None
    owner: str | None = None
    clear_owner: bool = False
    priority: str | None = None
    task_type: str | None = None
    depends_on: list[str] | None = None
    assignee_role: str | None = None
    clear_assignee_role: bool = False
    metadata_merge: dict[str, Any] = field(default_factory=dict)
    note: str | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        priority = _optional_string(values, "priority")
        if priority is not None:
            priority = _normalize_priority(priority)
        depends_on_raw = values.get("depends_on")
        depends_on: list[str] | None
        if depends_on_raw is None:
            depends_on = None
        else:
            depends_on = _optional_string_list(values, "depends_on")
        return cls(
            task_id=_require_string(values, "task_id"),
            column=_optional_string(values, "column"),
            actor=_optional_string(values, "actor"),
            status=_optional_string(values, "status"),
            owner=_optional_string(values, "owner"),
            clear_owner=_optional_bool(values, "clear_owner", False),
            priority=priority,
            task_type=_optional_string(values, "task_type"),
            depends_on=depends_on,
            assignee_role=_optional_string(values, "assignee_role"),
            clear_assignee_role=_optional_bool(values, "clear_assignee_role", False),
            metadata_merge=_optional_mapping(values, "metadata_merge"),
            note=_optional_string(values, "note"),
        )
