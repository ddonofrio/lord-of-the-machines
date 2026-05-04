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


def _optional_int(values: dict[str, Any], field_name: str) -> int | None:
    value = values.get(field_name)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer.")
    return value


def _optional_string_list(values: dict[str, Any], field_name: str) -> list[str]:
    value = values.get(field_name)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{field_name} must be a list of non-empty strings.")
    return list(value)


@dataclass(slots=True)
class EventRecord(MappingModel):
    event_id: str
    sequence: int
    topic: str
    timestamp: str
    mission_id: str | None
    producer_role: str | None
    correlation_id: str | None
    causation_id: str | None
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> Self:
        values = _ensure_mapping(value)
        payload = values.get("payload") or {}
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object.")
        sequence = values.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool):
            raise ValueError("sequence must be an integer.")
        return cls(
            event_id=_require_string(values, "event_id"),
            sequence=sequence,
            topic=_require_string(values, "topic"),
            timestamp=_require_string(values, "timestamp"),
            mission_id=_optional_string(values, "mission_id"),
            producer_role=_optional_string(values, "producer_role"),
            correlation_id=_optional_string(values, "correlation_id"),
            causation_id=_optional_string(values, "causation_id"),
            payload=dict(payload),
        )


@dataclass(slots=True)
class ConsumerState(MappingModel):
    consumer_id: str
    last_acked_sequence: int
    updated_at: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> Self:
        values = _ensure_mapping(value)
        seq = values.get("last_acked_sequence", 0)
        if not isinstance(seq, int) or isinstance(seq, bool):
            raise ValueError("last_acked_sequence must be an integer.")
        return cls(
            consumer_id=_require_string(values, "consumer_id"),
            last_acked_sequence=seq,
            updated_at=_require_string(values, "updated_at"),
        )


@dataclass(slots=True)
class PublishEventRequest:
    topic: str
    payload: dict[str, Any] = field(default_factory=dict)
    mission_id: str | None = None
    producer_role: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        payload = values.get("payload") or {}
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object.")
        return cls(
            topic=_require_string(values, "topic"),
            payload=dict(payload),
            mission_id=_optional_string(values, "mission_id"),
            producer_role=_optional_string(values, "producer_role"),
            correlation_id=_optional_string(values, "correlation_id"),
            causation_id=_optional_string(values, "causation_id"),
        )


@dataclass(slots=True)
class ListEventsRequest:
    topics: list[str] = field(default_factory=list)
    mission_id: str | None = None
    after_sequence: int | None = None
    limit: int | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(
            topics=_optional_string_list(values, "topics"),
            mission_id=_optional_string(values, "mission_id"),
            after_sequence=_optional_int(values, "after_sequence"),
            limit=_optional_int(values, "limit"),
        )


@dataclass(slots=True)
class ConsumeEventsRequest:
    consumer_id: str
    topics: list[str] = field(default_factory=list)
    limit: int | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(
            consumer_id=_require_string(values, "consumer_id"),
            topics=_optional_string_list(values, "topics"),
            limit=_optional_int(values, "limit"),
        )


@dataclass(slots=True)
class AckEventRequest:
    consumer_id: str
    event_id: str | None = None
    sequence: int | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        event_id = _optional_string(values, "event_id")
        sequence = _optional_int(values, "sequence")
        if event_id is None and sequence is None:
            raise ValueError("One of event_id or sequence must be provided.")
        return cls(
            consumer_id=_require_string(values, "consumer_id"),
            event_id=event_id,
            sequence=sequence,
        )


@dataclass(slots=True)
class GetConsumerStateRequest:
    consumer_id: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(consumer_id=_require_string(values, "consumer_id"))

