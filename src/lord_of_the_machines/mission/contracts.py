from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Self

from lord_of_the_machines.mission.events import (
    ALLOWED_ROLE_RESULT_STATUSES,
    STATUS_COMPLETED,
)


class MappingModel:
    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)


def _ensure_mapping(value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object.")
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
        raise ValueError(f"{field_name} must be a string when provided.")
    return value


def _optional_string_list(values: dict[str, Any], field_name: str) -> list[str]:
    value = values.get(field_name)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{field_name} must be a list of non-empty strings.")
    return list(value)


def _optional_mapping(values: dict[str, Any], field_name: str) -> dict[str, Any]:
    value = values.get(field_name)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object when provided.")
    return dict(value)


def _optional_bool(values: dict[str, Any], field_name: str) -> bool | None:
    value = values.get(field_name)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean when provided.")
    return value


def _optional_int(values: dict[str, Any], field_name: str) -> int | None:
    value = values.get(field_name)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer when provided.")
    return value


@dataclass(slots=True)
class RoleTaskRequest(MappingModel):
    objective: str
    mission_id: str | None = None
    phase: str | None = None
    task_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    constraints: list[str] = field(default_factory=list)
    max_rounds: int = 1
    continue_previous: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        max_rounds = _optional_int(values, "max_rounds")
        if max_rounds is not None and max_rounds < 1:
            raise ValueError("max_rounds must be >= 1.")
        return cls(
            objective=_require_string(values, "objective"),
            mission_id=_optional_string(values, "mission_id"),
            phase=_optional_string(values, "phase"),
            task_id=_optional_string(values, "task_id"),
            context=_optional_mapping(values, "context"),
            constraints=_optional_string_list(values, "constraints"),
            max_rounds=max_rounds or 1,
            continue_previous=bool(_optional_bool(values, "continue_previous") or False),
            metadata=_optional_mapping(values, "metadata"),
        )


@dataclass(slots=True)
class RoleTaskResult(MappingModel):
    status: str = STATUS_COMPLETED
    summary: str = ""
    artifact_type: str | None = None
    artifact_title: str | None = None
    artifact_content: str | None = None
    artifact_format: str = "markdown"
    tags: list[str] = field(default_factory=list)
    required_changes: list[str] = field(default_factory=list)
    unresolved_questions: list[str] = field(default_factory=list)
    follow_ups: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        status = (_optional_string(values, "status") or STATUS_COMPLETED).strip().lower()
        if status not in ALLOWED_ROLE_RESULT_STATUSES:
            allowed = ", ".join(sorted(ALLOWED_ROLE_RESULT_STATUSES))
            raise ValueError(f"status must be one of: {allowed}.")
        return cls(
            status=status,
            summary=_optional_string(values, "summary") or "",
            artifact_type=_optional_string(values, "artifact_type"),
            artifact_title=_optional_string(values, "artifact_title"),
            artifact_content=_optional_string(values, "artifact_content"),
            artifact_format=_optional_string(values, "artifact_format") or "markdown",
            tags=_optional_string_list(values, "tags"),
            required_changes=_optional_string_list(values, "required_changes"),
            unresolved_questions=_optional_string_list(values, "unresolved_questions"),
            follow_ups=_optional_string_list(values, "follow_ups"),
            metadata=_optional_mapping(values, "metadata"),
        )


@dataclass(slots=True)
class MeetingRequest(MappingModel):
    objective: str
    presenter: str
    participants: list[str] = field(default_factory=list)
    structured_input: str | None = None
    constraints: list[str] = field(default_factory=list)
    max_rounds: int = 3
    mission_id: str | None = None
    phase: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        max_rounds = _optional_int(values, "max_rounds")
        if max_rounds is not None and max_rounds < 1:
            raise ValueError("max_rounds must be >= 1.")
        return cls(
            objective=_require_string(values, "objective"),
            presenter=_require_string(values, "presenter"),
            participants=_optional_string_list(values, "participants"),
            structured_input=_optional_string(values, "structured_input"),
            constraints=_optional_string_list(values, "constraints"),
            max_rounds=max_rounds or 3,
            mission_id=_optional_string(values, "mission_id"),
            phase=_optional_string(values, "phase"),
            metadata=_optional_mapping(values, "metadata"),
        )


@dataclass(slots=True)
class MeetingResult(MappingModel):
    status: str = STATUS_COMPLETED
    meeting_summary: str = ""
    decisions: list[str] = field(default_factory=list)
    required_changes: list[str] = field(default_factory=list)
    unresolved_questions: list[str] = field(default_factory=list)
    follow_ups: list[str] = field(default_factory=list)
    final_recommendation: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        status = (_optional_string(values, "status") or STATUS_COMPLETED).strip().lower()
        if status not in ALLOWED_ROLE_RESULT_STATUSES:
            allowed = ", ".join(sorted(ALLOWED_ROLE_RESULT_STATUSES))
            raise ValueError(f"status must be one of: {allowed}.")
        return cls(
            status=status,
            meeting_summary=_optional_string(values, "meeting_summary") or "",
            decisions=_optional_string_list(values, "decisions"),
            required_changes=_optional_string_list(values, "required_changes"),
            unresolved_questions=_optional_string_list(values, "unresolved_questions"),
            follow_ups=_optional_string_list(values, "follow_ups"),
            final_recommendation=_optional_string(values, "final_recommendation") or "",
            metadata=_optional_mapping(values, "metadata"),
        )
