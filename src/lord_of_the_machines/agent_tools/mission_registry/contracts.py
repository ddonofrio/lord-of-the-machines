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


def _optional_string_list(values: dict[str, Any], field_name: str) -> list[str]:
    value = values.get(field_name)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{field_name} must be a list of non-empty strings.")
    return list(value)


@dataclass(slots=True)
class MissionRecord(MappingModel):
    mission_id: str
    title: str
    description: str
    status: str
    created_at: str
    updated_at: str
    phase_status: dict[str, str] = field(default_factory=dict)
    phase_notes: dict[str, str] = field(default_factory=dict)
    role_assignments: dict[str, list[str]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> Self:
        values = _ensure_mapping(value)
        return cls(
            mission_id=_require_string(values, "mission_id"),
            title=_require_string(values, "title"),
            description=_require_string(values, "description"),
            status=_require_string(values, "status"),
            created_at=_require_string(values, "created_at"),
            updated_at=_require_string(values, "updated_at"),
            phase_status=dict(values.get("phase_status") or {}),
            phase_notes=dict(values.get("phase_notes") or {}),
            role_assignments={
                str(role): [str(agent_id) for agent_id in agent_ids]
                for role, agent_ids in dict(values.get("role_assignments") or {}).items()
                if isinstance(agent_ids, list)
            },
            metadata=dict(values.get("metadata") or {}),
        )


@dataclass(slots=True)
class CreateMissionRequest:
    title: str
    description: str
    mission_id: str | None = None
    initial_status: str = "new"
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        metadata = values.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object.")
        return cls(
            title=_require_string(values, "title"),
            description=_require_string(values, "description"),
            mission_id=_optional_string(values, "mission_id"),
            initial_status=_optional_string(values, "initial_status") or "new",
            metadata=dict(metadata),
        )


@dataclass(slots=True)
class GetMissionRequest:
    mission_id: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(mission_id=_require_string(values, "mission_id"))


@dataclass(slots=True)
class ListMissionsRequest:
    statuses: list[str] = field(default_factory=list)
    limit: int | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        limit_raw = values.get("limit")
        if limit_raw is not None and (not isinstance(limit_raw, int) or isinstance(limit_raw, bool)):
            raise ValueError("limit must be an integer when provided.")
        return cls(
            statuses=_optional_string_list(values, "statuses"),
            limit=limit_raw,
        )


@dataclass(slots=True)
class UpdateMissionStatusRequest:
    mission_id: str
    status: str
    reason: str | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(
            mission_id=_require_string(values, "mission_id"),
            status=_require_string(values, "status"),
            reason=_optional_string(values, "reason"),
        )


@dataclass(slots=True)
class UpdateMissionPhaseRequest:
    mission_id: str
    phase: str
    status: str
    notes: str | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(
            mission_id=_require_string(values, "mission_id"),
            phase=_require_string(values, "phase"),
            status=_require_string(values, "status"),
            notes=_optional_string(values, "notes"),
        )


@dataclass(slots=True)
class AssignMissionRoleRequest:
    mission_id: str
    role: str
    agent_id: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(
            mission_id=_require_string(values, "mission_id"),
            role=_require_string(values, "role"),
            agent_id=_require_string(values, "agent_id"),
        )


@dataclass(slots=True)
class UnassignMissionRoleRequest:
    mission_id: str
    role: str
    agent_id: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(
            mission_id=_require_string(values, "mission_id"),
            role=_require_string(values, "role"),
            agent_id=_require_string(values, "agent_id"),
        )

