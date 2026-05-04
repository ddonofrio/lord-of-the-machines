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
class ArtifactRecord(MappingModel):
    artifact_id: str
    mission_id: str
    phase: str
    artifact_type: str
    title: str
    status: str
    version: int
    format: str
    content: str
    producer_role: str | None
    created_at: str
    updated_at: str
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> Self:
        values = _ensure_mapping(value)
        metadata = values.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object.")
        version = values.get("version")
        if not isinstance(version, int) or isinstance(version, bool):
            raise ValueError("version must be an integer.")
        return cls(
            artifact_id=_require_string(values, "artifact_id"),
            mission_id=_require_string(values, "mission_id"),
            phase=_require_string(values, "phase"),
            artifact_type=_require_string(values, "artifact_type"),
            title=_require_string(values, "title"),
            status=_require_string(values, "status"),
            version=version,
            format=_require_string(values, "format"),
            content=_require_string(values, "content"),
            producer_role=_optional_string(values, "producer_role"),
            created_at=_require_string(values, "created_at"),
            updated_at=_require_string(values, "updated_at"),
            tags=_optional_string_list(values, "tags"),
            metadata=dict(metadata),
        )


@dataclass(slots=True)
class PublishArtifactRequest:
    mission_id: str
    phase: str
    artifact_type: str
    title: str
    content: str
    format: str = "markdown"
    producer_role: str | None = None
    status: str = "published"
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        metadata = values.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object.")
        return cls(
            mission_id=_require_string(values, "mission_id"),
            phase=_require_string(values, "phase"),
            artifact_type=_require_string(values, "artifact_type"),
            title=_require_string(values, "title"),
            content=_require_string(values, "content"),
            format=_optional_string(values, "format") or "markdown",
            producer_role=_optional_string(values, "producer_role"),
            status=_optional_string(values, "status") or "published",
            tags=_optional_string_list(values, "tags"),
            metadata=dict(metadata),
        )


@dataclass(slots=True)
class GetArtifactRequest:
    artifact_id: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(artifact_id=_require_string(values, "artifact_id"))


@dataclass(slots=True)
class ListArtifactsRequest:
    mission_id: str | None = None
    phase: str | None = None
    artifact_type: str | None = None
    statuses: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(
            mission_id=_optional_string(values, "mission_id"),
            phase=_optional_string(values, "phase"),
            artifact_type=_optional_string(values, "artifact_type"),
            statuses=_optional_string_list(values, "statuses"),
            tags=_optional_string_list(values, "tags"),
        )


@dataclass(slots=True)
class UpdateArtifactRequest:
    artifact_id: str
    content: str | None = None
    title: str | None = None
    status: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] | None = None
    has_tags: bool = False
    has_metadata: bool = False

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        has_tags = "tags" in values
        has_metadata = "metadata" in values
        metadata = values.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("metadata must be an object when provided.")
        content = values.get("content")
        if content is not None and not isinstance(content, str):
            raise ValueError("content must be a string when provided.")
        title = _optional_string(values, "title")
        status = _optional_string(values, "status")
        tags = _optional_string_list(values, "tags")
        if content is None and title is None and status is None and not has_tags and not has_metadata:
            raise ValueError("At least one updatable field must be provided.")
        return cls(
            artifact_id=_require_string(values, "artifact_id"),
            content=content,
            title=title,
            status=status,
            tags=tags,
            metadata=dict(metadata) if metadata is not None else None,
            has_tags=has_tags,
            has_metadata=has_metadata,
        )
