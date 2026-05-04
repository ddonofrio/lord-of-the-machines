from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lord_of_the_machines.agent_tools.event_bus.config import EventBusToolConfig
from lord_of_the_machines.agent_tools.event_bus.contracts import (
    AckEventRequest,
    ConsumeEventsRequest,
    ConsumerState,
    EventRecord,
    GetConsumerStateRequest,
    ListEventsRequest,
    PublishEventRequest,
)
from lord_of_the_machines.agent_tools.event_bus.definition import build_definition
from lord_of_the_machines.llm.base_agent import BaseAgent
from lord_of_the_machines.llm.tool_definitions import ToolDefinition
from lord_of_the_machines.llm.tools import ToolHandler


SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
SAFE_TOPIC_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")


class EventBusTool:
    TOOL_NAME = "event_bus"

    def __init__(self, root_path: str | Path, *, config: EventBusToolConfig | None = None) -> None:
        self.config = config or EventBusToolConfig(root_path=Path(root_path))

    def install(self, agent: BaseAgent) -> None:
        agent.add_tool(self.definition(), handlers=self.handlers())

    def definition(self) -> ToolDefinition:
        return build_definition(self.TOOL_NAME)

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "publish_event": self._publish_event,
            "list_events": self._list_events,
            "consume_events": self._consume_events,
            "ack_event": self._ack_event,
            "get_consumer_state": self._get_consumer_state,
        }

    def _publish_event(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = PublishEventRequest.from_mapping(arguments)
        topic = self._safe_topic(request.topic)
        mission_id = self._safe_id(request.mission_id, field_name="mission_id") if request.mission_id else None
        producer_role = self._safe_id(request.producer_role, field_name="producer_role") if request.producer_role else None
        correlation_id = self._safe_id(request.correlation_id, field_name="correlation_id") if request.correlation_id else None
        causation_id = self._safe_id(request.causation_id, field_name="causation_id") if request.causation_id else None

        events = self._read_all_events()
        next_sequence = (events[-1].sequence + 1) if events else 1
        event = EventRecord(
            event_id=self._format_event_id(next_sequence),
            sequence=next_sequence,
            topic=topic,
            timestamp=self._utc_now(),
            mission_id=mission_id,
            producer_role=producer_role,
            correlation_id=correlation_id,
            causation_id=causation_id,
            payload=dict(request.payload),
        )
        self._append_event(event)
        return {"event": event.to_mapping()}

    def _list_events(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = ListEventsRequest.from_mapping(arguments)
        topic_filter = {self._safe_topic(topic) for topic in request.topics} if request.topics else None
        mission_id = self._safe_id(request.mission_id, field_name="mission_id") if request.mission_id else None
        events = []
        for event in self._read_all_events():
            if topic_filter is not None and event.topic not in topic_filter:
                continue
            if mission_id is not None and event.mission_id != mission_id:
                continue
            if request.after_sequence is not None and event.sequence <= request.after_sequence:
                continue
            events.append(event.to_mapping())
            if request.limit is not None and len(events) >= request.limit:
                break
        return {"events": events}

    def _consume_events(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = ConsumeEventsRequest.from_mapping(arguments)
        consumer_id = self._safe_id(request.consumer_id, field_name="consumer_id")
        topic_filter = {self._safe_topic(topic) for topic in request.topics} if request.topics else None
        state = self._load_consumer_state(consumer_id)

        max_limit = self.config.max_consume_limit
        limit = request.limit if request.limit is not None else max_limit
        if limit < 1:
            raise ValueError("limit must be >= 1.")
        limit = min(limit, max_limit)

        events = []
        for event in self._read_all_events():
            if event.sequence <= state.last_acked_sequence:
                continue
            if topic_filter is not None and event.topic not in topic_filter:
                continue
            events.append(event.to_mapping())
            if len(events) >= limit:
                break
        return {
            "consumer_state": state.to_mapping(),
            "events": events,
        }

    def _ack_event(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = AckEventRequest.from_mapping(arguments)
        consumer_id = self._safe_id(request.consumer_id, field_name="consumer_id")
        state = self._load_consumer_state(consumer_id)

        target_sequence = request.sequence
        if target_sequence is None and request.event_id is not None:
            target_sequence = self._sequence_for_event_id(request.event_id)
        if target_sequence is None:
            raise ValueError("Unable to resolve target sequence for ack.")
        if target_sequence < state.last_acked_sequence:
            raise ValueError(
                f"Cannot move consumer offset backwards ({target_sequence} < {state.last_acked_sequence})."
            )

        state.last_acked_sequence = target_sequence
        state.updated_at = self._utc_now()
        self._save_consumer_state(state)
        return {"consumer_state": state.to_mapping()}

    def _get_consumer_state(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = GetConsumerStateRequest.from_mapping(arguments)
        consumer_id = self._safe_id(request.consumer_id, field_name="consumer_id")
        state = self._load_consumer_state(consumer_id)
        return {"consumer_state": state.to_mapping()}

    def _read_all_events(self) -> list[EventRecord]:
        events_file = self._events_file()
        if not events_file.exists():
            return []
        events = []
        for line in events_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            events.append(EventRecord.from_mapping(json.loads(line)))
        return events

    def _append_event(self, event: EventRecord) -> None:
        events_file = self._events_file()
        with events_file.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(event.to_mapping(), ensure_ascii=False))
            handle.write("\n")

    def _sequence_for_event_id(self, event_id: str) -> int:
        safe_id = self._safe_id(event_id, field_name="event_id")
        for event in self._read_all_events():
            if event.event_id == safe_id:
                return event.sequence
        raise ValueError(f"Event id not found: {safe_id}")

    def _load_consumer_state(self, consumer_id: str) -> ConsumerState:
        state_path = self._consumer_state_path(consumer_id)
        if not state_path.exists():
            return ConsumerState(
                consumer_id=consumer_id,
                last_acked_sequence=0,
                updated_at=self._utc_now(),
            )
        raw = json.loads(state_path.read_text(encoding="utf-8"))
        return ConsumerState.from_mapping(raw)

    def _save_consumer_state(self, state: ConsumerState) -> None:
        path = self._consumer_state_path(state.consumer_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state.to_mapping(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _events_file(self) -> Path:
        path = (self.config.root_path / self.config.events_file_name).resolve()
        if not self._is_within_root(path):
            raise ValueError("Events file path is outside configured event bus root.")
        return path

    def _consumer_state_path(self, consumer_id: str) -> Path:
        path = (self.config.root_path / "consumers" / f"{consumer_id}.json").resolve()
        if not self._is_within_root(path):
            raise ValueError("Consumer state path is outside configured event bus root.")
        return path

    def _is_within_root(self, path: Path) -> bool:
        try:
            path.relative_to(self.config.root_path)
            return True
        except ValueError:
            return False

    def _safe_id(self, value: str | None, *, field_name: str) -> str:
        if value is None:
            raise ValueError(f"{field_name} is required.")
        if not SAFE_ID_RE.fullmatch(value):
            raise ValueError(
                f"{field_name} must match {SAFE_ID_RE.pattern} "
                "(letters, numbers, underscore, hyphen; max 64 chars)."
            )
        return value

    def _safe_topic(self, topic: str) -> str:
        if not SAFE_TOPIC_RE.fullmatch(topic):
            raise ValueError(
                f"topic must match {SAFE_TOPIC_RE.pattern} "
                "(letters, numbers, dot, underscore, hyphen; max 128 chars)."
            )
        return topic

    @staticmethod
    def _format_event_id(sequence: int) -> str:
        return f"E-{sequence:08d}"

    def _utc_now(self) -> str:
        return datetime.now(tz=timezone.utc).isoformat()

