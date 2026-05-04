from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from lord_of_the_machines.agent_tools import (
    ArtifactRegistryTool,
    EventBusTool,
    MissionRegistryTool,
)
from lord_of_the_machines.mission.contracts import RoleTaskRequest, RoleTaskResult
from lord_of_the_machines.mission.events import (
    STATUS_BLOCKED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_NEEDS_FOLLOW_UP,
    TOPIC_ARTIFACT_PUBLISHED,
    TOPIC_PHASE_COMPLETED,
    TOPIC_PHASE_FAILED,
    TOPIC_PHASE_REQUESTED,
)
from lord_of_the_machines.runtime import get_logger, log_json


class RoleExecutor(Protocol):
    def execute_task(self, request: RoleTaskRequest) -> RoleTaskResult | dict[str, Any]:
        ...


@dataclass(slots=True)
class MissionRuntimeConfig:
    consumer_id: str = "mission_runtime"
    initial_phase: str = "product_direction"
    initial_role: str = "product_director"
    max_events_per_run: int = 20
    max_follow_up_rounds: int = 3
    include_topics: tuple[str, ...] = (TOPIC_PHASE_REQUESTED,)


@dataclass(slots=True)
class MissionRuntime:
    mission_registry: MissionRegistryTool
    event_bus: EventBusTool
    artifact_registry: ArtifactRegistryTool
    role_executors: dict[str, RoleExecutor]
    config: MissionRuntimeConfig = field(default_factory=MissionRuntimeConfig)
    _mission: dict[str, Any] = field(init=False)
    _events: dict[str, Any] = field(init=False)
    _artifacts: dict[str, Any] = field(init=False)
    _logger: Any = field(init=False)

    def __post_init__(self) -> None:
        self._mission = self.mission_registry.handlers()
        self._events = self.event_bus.handlers()
        self._artifacts = self.artifact_registry.handlers()
        self._logger = get_logger("mission.runtime")

    def seed_pending_missions(self, *, limit: int | None = None) -> dict[str, Any]:
        max_limit = limit if limit is not None else self.config.max_events_per_run
        listed = self._mission["list_missions"](
            {
                "statuses": ["new", "in_progress"],
                "limit": max_limit,
            }
        )
        seeded = []
        for mission in listed["missions"]:
            mission_id = str(mission["mission_id"])
            phase_status = dict(mission.get("phase_status") or {})
            if phase_status.get(self.config.initial_phase):
                continue
            objective = self._phase_objective(mission)
            self._mission["update_mission_phase"](
                {
                    "mission_id": mission_id,
                    "phase": self.config.initial_phase,
                    "status": "requested",
                    "notes": "Seeded by runtime.",
                }
            )
            self._mission["update_mission_status"](
                {
                    "mission_id": mission_id,
                    "status": "in_progress",
                    "reason": f"Phase '{self.config.initial_phase}' requested.",
                }
            )
            payload = {
                "phase": self.config.initial_phase,
                "role": self.config.initial_role,
                "objective": objective,
                "context": {
                    "mission_title": mission.get("title"),
                    "mission_description": mission.get("description"),
                    "metadata": mission.get("metadata") or {},
                },
                "round": 1,
            }
            event_result = self._events["publish_event"](
                {
                    "topic": TOPIC_PHASE_REQUESTED,
                    "mission_id": mission_id,
                    "producer_role": self.config.consumer_id,
                    "payload": payload,
                }
            )
            seeded.append(event_result["event"])
            log_json(
                self._logger,
                "mission_runtime.seeded",
                {"mission_id": mission_id, "payload": payload},
            )
        return {"seeded_events": seeded}

    def run_once(self, *, max_events: int | None = None) -> dict[str, Any]:
        limit = max_events if max_events is not None else self.config.max_events_per_run
        consumed = self._events["consume_events"](
            {
                "consumer_id": self.config.consumer_id,
                "topics": list(self.config.include_topics),
                "limit": limit,
            }
        )
        processed = []
        for event in consumed["events"]:
            event_id = str(event["event_id"])
            sequence = int(event["sequence"])
            try:
                outcome = self._process_event(event)
                processed.append({"event_id": event_id, "ok": True, "outcome": outcome})
            except Exception as exc:  # pragma: no cover - defensive guard
                self._publish_phase_failed_event(
                    mission_id=event.get("mission_id"),
                    phase=str((event.get("payload") or {}).get("phase") or self.config.initial_phase),
                    role=str((event.get("payload") or {}).get("role") or "unknown"),
                    summary=f"Runtime error while processing {event_id}: {exc}",
                )
                processed.append({"event_id": event_id, "ok": False, "error": str(exc)})
            finally:
                self._events["ack_event"](
                    {
                        "consumer_id": self.config.consumer_id,
                        "sequence": sequence,
                    }
                )
        return {
            "processed": processed,
            "consumer_state": self._events["get_consumer_state"]({"consumer_id": self.config.consumer_id})[
                "consumer_state"
            ],
        }

    def _process_event(self, event: dict[str, Any]) -> dict[str, Any]:
        topic = str(event.get("topic") or "")
        if topic != TOPIC_PHASE_REQUESTED:
            return {"ignored": True, "reason": f"Unsupported topic: {topic}"}

        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            raise ValueError("Event payload must be an object.")
        mission_id = str(event.get("mission_id") or payload.get("mission_id") or "")
        if not mission_id:
            raise ValueError("mission_id is required for phase execution.")
        phase = str(payload.get("phase") or self.config.initial_phase)
        role = str(payload.get("role") or self.config.initial_role)
        objective = str(payload.get("objective") or "").strip()
        if not objective:
            mission = self._mission["get_mission"]({"mission_id": mission_id})["mission"]
            objective = self._phase_objective(mission)

        executor = self.role_executors.get(role)
        if executor is None:
            raise ValueError(f"No role executor registered for role '{role}'.")

        request = RoleTaskRequest.from_mapping(
            {
                "objective": objective,
                "mission_id": mission_id,
                "phase": phase,
                "context": payload.get("context") if isinstance(payload.get("context"), dict) else {},
                "constraints": payload.get("constraints") if isinstance(payload.get("constraints"), list) else [],
                "max_rounds": payload.get("max_rounds") or 1,
                "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
            }
        )

        raw_result = executor.execute_task(request)
        result = raw_result if isinstance(raw_result, RoleTaskResult) else RoleTaskResult.from_mapping(raw_result)
        return self._apply_role_result(
            mission_id=mission_id,
            phase=phase,
            role=role,
            request=request,
            result=result,
            round_number=int(payload.get("round") or 1),
        )

    def _apply_role_result(
        self,
        *,
        mission_id: str,
        phase: str,
        role: str,
        request: RoleTaskRequest,
        result: RoleTaskResult,
        round_number: int,
    ) -> dict[str, Any]:
        if result.status == STATUS_COMPLETED:
            self._mission["update_mission_phase"](
                {
                    "mission_id": mission_id,
                    "phase": phase,
                    "status": "completed",
                    "notes": result.summary,
                }
            )
            self._publish_phase_completed_event(
                mission_id=mission_id,
                phase=phase,
                role=role,
                summary=result.summary,
            )
            artifact = self._publish_artifact_if_present(
                mission_id=mission_id,
                phase=phase,
                role=role,
                result=result,
            )
            self._update_mission_lifecycle_on_completion(mission_id)
            return {"status": result.status, "artifact": artifact}

        if result.status == STATUS_NEEDS_FOLLOW_UP:
            if round_number >= self.config.max_follow_up_rounds:
                self._mission["update_mission_phase"](
                    {
                        "mission_id": mission_id,
                        "phase": phase,
                        "status": "blocked",
                        "notes": "Follow-up round limit reached.",
                    }
                )
                self._mission["update_mission_status"](
                    {
                        "mission_id": mission_id,
                        "status": "blocked",
                        "reason": f"Phase '{phase}' exceeded follow-up round limit.",
                    }
                )
                self._publish_phase_failed_event(
                    mission_id=mission_id,
                    phase=phase,
                    role=role,
                    summary="Follow-up round limit reached.",
                )
                return {"status": STATUS_BLOCKED, "reason": "follow_up_round_limit"}

            self._mission["update_mission_phase"](
                {
                    "mission_id": mission_id,
                    "phase": phase,
                    "status": "in_progress",
                    "notes": result.summary,
                }
            )
            follow_up_payload = {
                "phase": phase,
                "role": role,
                "objective": request.objective,
                "context": request.context,
                "constraints": request.constraints,
                "max_rounds": request.max_rounds,
                "metadata": request.metadata,
                "round": round_number + 1,
            }
            self._events["publish_event"](
                {
                    "topic": TOPIC_PHASE_REQUESTED,
                    "mission_id": mission_id,
                    "producer_role": self.config.consumer_id,
                    "payload": follow_up_payload,
                }
            )
            return {"status": STATUS_NEEDS_FOLLOW_UP, "round": round_number + 1}

        self._mission["update_mission_phase"](
            {
                "mission_id": mission_id,
                "phase": phase,
                "status": result.status,
                "notes": result.summary,
            }
        )
        self._mission["update_mission_status"](
            {
                "mission_id": mission_id,
                "status": "blocked" if result.status == STATUS_BLOCKED else "in_progress",
                "reason": result.summary or f"Phase '{phase}' ended with status '{result.status}'.",
            }
        )
        self._publish_phase_failed_event(
            mission_id=mission_id,
            phase=phase,
            role=role,
            summary=result.summary or f"Phase returned status '{result.status}'.",
        )
        return {"status": result.status}

    def _publish_artifact_if_present(
        self,
        *,
        mission_id: str,
        phase: str,
        role: str,
        result: RoleTaskResult,
    ) -> dict[str, Any] | None:
        if not result.artifact_content:
            return None
        artifact = self._artifacts["publish_artifact"](
            {
                "mission_id": mission_id,
                "phase": phase,
                "artifact_type": result.artifact_type or phase,
                "title": result.artifact_title or f"{phase} output",
                "content": result.artifact_content,
                "format": result.artifact_format,
                "producer_role": role,
                "tags": result.tags,
                "metadata": result.metadata,
            }
        )["artifact"]
        self._events["publish_event"](
            {
                "topic": TOPIC_ARTIFACT_PUBLISHED,
                "mission_id": mission_id,
                "producer_role": self.config.consumer_id,
                "payload": {
                    "phase": phase,
                    "artifact_id": artifact["artifact_id"],
                    "artifact_type": artifact["artifact_type"],
                    "title": artifact["title"],
                },
            }
        )
        return artifact

    def _publish_phase_completed_event(self, *, mission_id: str, phase: str, role: str, summary: str) -> None:
        self._events["publish_event"](
            {
                "topic": TOPIC_PHASE_COMPLETED,
                "mission_id": mission_id,
                "producer_role": self.config.consumer_id,
                "payload": {
                    "phase": phase,
                    "role": role,
                    "summary": summary,
                },
            }
        )

    def _publish_phase_failed_event(self, *, mission_id: str | None, phase: str, role: str, summary: str) -> None:
        self._events["publish_event"](
            {
                "topic": TOPIC_PHASE_FAILED,
                "mission_id": mission_id,
                "producer_role": self.config.consumer_id,
                "payload": {
                    "phase": phase,
                    "role": role,
                    "summary": summary,
                },
            }
        )

    def _update_mission_lifecycle_on_completion(self, mission_id: str) -> None:
        mission = self._mission["get_mission"]({"mission_id": mission_id})["mission"]
        phase_status = dict(mission.get("phase_status") or {})
        if phase_status and all(status == "completed" for status in phase_status.values()):
            self._mission["update_mission_status"](
                {
                    "mission_id": mission_id,
                    "status": "completed",
                    "reason": "All mission phases are completed.",
                }
            )
        else:
            self._mission["update_mission_status"](
                {
                    "mission_id": mission_id,
                    "status": "in_progress",
                    "reason": "Phase completed, mission still has pending phases.",
                }
            )

    def _phase_objective(self, mission: dict[str, Any]) -> str:
        title = str(mission.get("title") or "").strip()
        description = str(mission.get("description") or "").strip()
        if title and description:
            return f"{title}: {description}"
        return title or description or "Complete the mission."
