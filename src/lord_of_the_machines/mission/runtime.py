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
    STATUS_NEEDS_FOLLOW_UP,
    TOPIC_ARTIFACT_PUBLISHED,
    TOPIC_PHASE_COMPLETED,
    TOPIC_PHASE_FAILED,
    TOPIC_PHASE_REQUESTED,
)
from lord_of_the_machines.runtime import get_logger, log_json, log_timeline


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
    phase_roles: dict[str, str] = field(
        default_factory=lambda: {
            "product_direction": "product_director",
            "product_requirements": "product_manager",
            "technical_design": "software_architect",
            "development_plan": "software_development_manager",
            "implementation": "software_developer",
        }
    )
    phase_transitions: dict[str, str] = field(
        default_factory=lambda: {
            "product_direction": "product_requirements",
            "product_requirements": "technical_design",
            "technical_design": "development_plan",
            "development_plan": "implementation",
        }
    )
    auto_schedule_next_phase: bool = True


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
    _seeded_phase_keys: set[tuple[str, str]] = field(init=False, default_factory=set)

    def __post_init__(self) -> None:
        self._mission = self.mission_registry.handlers()
        self._events = self.event_bus.handlers()
        self._artifacts = self.artifact_registry.handlers()
        self._logger = get_logger("mission.runtime")
        self._seeded_phase_keys = set()

    def seed_pending_missions(self, *, limit: int | None = None) -> dict[str, Any]:
        max_limit = limit if limit is not None else self.config.max_events_per_run
        pending_phase_requests = self._pending_phase_request_keys()
        listed = self._mission["list_missions"](
            {
                "statuses": ["new", "in_progress", "incomplete"],
                "limit": max_limit,
            }
        )
        seeded = []
        for mission in listed["missions"]:
            mission_id = str(mission["mission_id"])
            phase_to_seed = self._phase_to_seed_for_mission(mission)
            if not phase_to_seed:
                continue
            if (mission_id, phase_to_seed) in self._seeded_phase_keys:
                continue
            if (mission_id, phase_to_seed) in pending_phase_requests:
                continue

            role = self._role_for_phase(phase_to_seed)
            objective = self._phase_objective(mission)
            phase_status = dict(mission.get("phase_status") or {})
            existing_phase_status = str(phase_status.get(phase_to_seed) or "").strip().lower()
            if not existing_phase_status:
                self._mission["update_mission_phase"](
                    {
                        "mission_id": mission_id,
                        "phase": phase_to_seed,
                        "status": "requested",
                        "notes": "Seeded by runtime.",
                    }
                )
            self._mission["update_mission_status"](
                {
                    "mission_id": mission_id,
                    "status": "in_progress",
                    "reason": f"Phase '{phase_to_seed}' requested.",
                }
            )
            round_number = self._next_round_for_seed(mission_id, phase_to_seed)
            payload = {
                "phase": phase_to_seed,
                "role": role,
                "objective": objective,
                "context": self._seed_context_for_phase(mission, phase_to_seed),
                "round": round_number,
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
            self._seeded_phase_keys.add((mission_id, phase_to_seed))
            log_json(
                self._logger,
                "mission_runtime.seeded",
                {"mission_id": mission_id, "payload": payload},
            )
            log_timeline(
                actor=self.config.consumer_id,
                action="seeded phase request",
                mission_id=mission_id,
                phase=phase_to_seed,
                details={
                    "role": role,
                    "objective": objective,
                    "round": round_number,
                },
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
        role = str(payload.get("role") or self._role_for_phase(phase))
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
        contract_errors = result.contract_errors()
        if contract_errors:
            log_json(
                self._logger,
                "mission_runtime.role_result.contract_violation",
                {
                    "mission_id": mission_id,
                    "phase": phase,
                    "role": role,
                    "status": result.status,
                    "errors": contract_errors,
                },
            )
            log_timeline(
                actor=self.config.consumer_id,
                action="role result rejected (contract violation)",
                mission_id=mission_id,
                phase=phase,
                details={
                    "role": role,
                    "errors": contract_errors,
                },
            )
            result = RoleTaskResult(
                status=STATUS_NEEDS_FOLLOW_UP,
                summary="Role result did not satisfy the required output contract.",
                required_changes=list(contract_errors),
                follow_ups=list(contract_errors),
                metadata={"contract_errors": list(contract_errors)},
            )
        usage = result.metadata.get("agent_usage") if isinstance(result.metadata, dict) else None
        cost = result.metadata.get("agent_cost") if isinstance(result.metadata, dict) else None
        log_json(
            self._logger,
            "mission_runtime.role_result",
            {
                "mission_id": mission_id,
                "phase": phase,
                "role": role,
                "round": int(payload.get("round") or 1),
                "status": result.status,
                "summary": result.summary,
                "has_artifact_content": bool(result.artifact_content),
                "usage": usage,
                "cost": cost,
            },
        )
        log_timeline(
            actor=role,
            action=f"reported result ({result.status})",
            mission_id=mission_id,
            phase=phase,
            details={"summary": result.summary},
            usage=usage if isinstance(usage, dict) else None,
            cost=cost if isinstance(cost, dict) else None,
        )
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
            next_phase_event = self._schedule_next_phase_if_needed(
                mission_id=mission_id,
                current_phase=phase,
                completed_result=result,
                artifact=artifact,
            )
            self._update_mission_lifecycle_on_completion(mission_id)
            log_json(
                self._logger,
                "mission_runtime.phase_completed",
                {
                    "mission_id": mission_id,
                    "phase": phase,
                    "role": role,
                    "summary": result.summary,
                    "has_artifact": artifact is not None,
                    "next_phase_scheduled": next_phase_event is not None,
                },
            )
            log_timeline(
                actor=self.config.consumer_id,
                action="phase completed",
                mission_id=mission_id,
                phase=phase,
                details={
                    "role": role,
                    "summary": result.summary,
                    "artifact_published": artifact is not None,
                    "next_phase_scheduled": next_phase_event is not None,
                },
            )
            return {"status": result.status, "artifact": artifact, "next_phase_event": next_phase_event}

        if result.status == STATUS_NEEDS_FOLLOW_UP:
            phase_note = self._follow_up_phase_note(result=result, round_number=round_number)
            if round_number >= self.config.max_follow_up_rounds:
                self._mission["update_mission_phase"](
                    {
                        "mission_id": mission_id,
                        "phase": phase,
                        "status": "in_progress",
                        "notes": (
                            f"{phase_note}\n\n"
                            "Follow-up round limit reached for this run; mission is marked as incomplete."
                        ).strip(),
                    }
                )
                self._mission["update_mission_status"](
                    {
                        "mission_id": mission_id,
                        "status": "incomplete",
                        "reason": f"Phase '{phase}' reached follow-up round limit for this run.",
                    }
                )
                log_json(
                    self._logger,
                    "mission_runtime.phase_incomplete.follow_up_limit",
                    {
                        "mission_id": mission_id,
                        "phase": phase,
                        "role": role,
                        "round": round_number,
                        "summary": result.summary,
                    },
                )
                log_timeline(
                    actor=self.config.consumer_id,
                    action="phase incomplete (follow-up limit)",
                    mission_id=mission_id,
                    phase=phase,
                    details={
                        "role": role,
                        "round": round_number,
                        "summary": result.summary,
                    },
                )
                return {
                    "status": "incomplete",
                    "reason": "follow_up_round_limit",
                    "summary": result.summary,
                }

            self._mission["update_mission_phase"](
                {
                    "mission_id": mission_id,
                    "phase": phase,
                    "status": "in_progress",
                    "notes": phase_note,
                }
            )
            follow_up_context = dict(request.context) if isinstance(request.context, dict) else {}
            follow_up_history = list(follow_up_context.get("follow_up_history") or [])
            follow_up_feedback = {
                "round": round_number,
                "summary": result.summary,
                "required_changes": list(result.required_changes),
                "unresolved_questions": list(result.unresolved_questions),
                "follow_ups": list(result.follow_ups),
            }
            follow_up_history.append(follow_up_feedback)
            follow_up_context["follow_up_history"] = follow_up_history[-3:]
            follow_up_context["follow_up_feedback"] = follow_up_feedback
            follow_up_payload = {
                "phase": phase,
                "role": role,
                "objective": request.objective,
                "context": follow_up_context,
                "constraints": request.constraints,
                "max_rounds": request.max_rounds,
                "continue_previous": True,
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
            log_json(
                self._logger,
                "mission_runtime.phase_follow_up_scheduled",
                {
                    "mission_id": mission_id,
                    "phase": phase,
                    "role": role,
                    "next_round": round_number + 1,
                    "summary": result.summary,
                },
            )
            log_timeline(
                actor=self.config.consumer_id,
                action="scheduled follow-up round",
                mission_id=mission_id,
                phase=phase,
                details={
                    "role": role,
                    "next_round": round_number + 1,
                    "summary": result.summary,
                },
            )
            return {
                "status": STATUS_NEEDS_FOLLOW_UP,
                "round": round_number + 1,
                "summary": result.summary,
            }

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
        log_json(
            self._logger,
            "mission_runtime.phase_failed",
            {
                "mission_id": mission_id,
                "phase": phase,
                "role": role,
                "status": result.status,
                "summary": result.summary,
            },
        )
        log_timeline(
            actor=self.config.consumer_id,
            action="phase failed",
            mission_id=mission_id,
            phase=phase,
            details={
                "role": role,
                "status": result.status,
                "summary": result.summary,
            },
        )
        return {"status": result.status, "summary": result.summary}

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

    def _schedule_next_phase_if_needed(
        self,
        *,
        mission_id: str,
        current_phase: str,
        completed_result: RoleTaskResult,
        artifact: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not self.config.auto_schedule_next_phase:
            return None
        next_phase = self.config.phase_transitions.get(current_phase)
        if not next_phase:
            return None

        mission = self._mission["get_mission"]({"mission_id": mission_id})["mission"]
        phase_status = dict(mission.get("phase_status") or {})
        if phase_status.get(next_phase):
            return None

        role = self._role_for_phase(next_phase)
        objective = self._phase_objective(mission)
        self._mission["update_mission_phase"](
            {
                "mission_id": mission_id,
                "phase": next_phase,
                "status": "requested",
                "notes": f"Scheduled automatically after phase '{current_phase}'.",
            }
        )
        event_result = self._events["publish_event"](
            {
                "topic": TOPIC_PHASE_REQUESTED,
                "mission_id": mission_id,
                "producer_role": self.config.consumer_id,
                "payload": {
                    "phase": next_phase,
                    "role": role,
                    "objective": objective,
                    "context": {
                        "mission_title": mission.get("title"),
                        "mission_description": mission.get("description"),
                        "metadata": mission.get("metadata") or {},
                        "previous_phase": current_phase,
                        "previous_phase_summary": completed_result.summary,
                        "previous_artifact": self._artifact_context(artifact),
                    },
                    "round": 1,
                },
            }
        )
        return event_result["event"]

    def _artifact_context(self, artifact: dict[str, Any] | None) -> dict[str, Any] | None:
        if not artifact:
            return None
        return {
            "artifact_id": artifact.get("artifact_id"),
            "artifact_type": artifact.get("artifact_type"),
            "title": artifact.get("title"),
            "format": artifact.get("format"),
            "content": artifact.get("content"),
            "producer_role": artifact.get("producer_role"),
        }

    def _role_for_phase(self, phase: str) -> str:
        return self.config.phase_roles.get(phase, self.config.initial_role)

    def _seed_context_for_phase(self, mission: dict[str, Any], phase: str) -> dict[str, Any]:
        phase_status = dict(mission.get("phase_status") or {})
        phase_notes = dict(mission.get("phase_notes") or {})
        context: dict[str, Any] = {
            "mission_title": mission.get("title"),
            "mission_description": mission.get("description"),
            "metadata": mission.get("metadata") or {},
            "phase_status": phase_status,
            "phase_notes": phase_notes,
            "resume_phase": phase,
            "resume_phase_status": phase_status.get(phase),
            "resume_phase_notes": phase_notes.get(phase),
            "resume_guidance": (
                "This is a continuation of an in-progress phase. Reuse existing workspace outputs and "
                "focus on unresolved required changes instead of restarting already completed work."
            ),
        }
        mission_id = str(mission.get("mission_id") or "")
        previous_phase = self._nearest_completed_previous_phase(phase, phase_status)
        if mission_id and previous_phase:
            artifact = self._latest_artifact_for_phase(mission_id, previous_phase)
            artifact_context = self._artifact_context(artifact)
            if artifact_context:
                context["previous_phase"] = previous_phase
                context["previous_artifact"] = artifact_context
        return context

    def _nearest_completed_previous_phase(self, phase: str, phase_status: dict[str, Any]) -> str | None:
        ordered_phases = list(self.config.phase_roles.keys())
        if phase not in ordered_phases:
            return None
        phase_index = ordered_phases.index(phase)
        for index in range(phase_index - 1, -1, -1):
            candidate_phase = ordered_phases[index]
            candidate_status = str(phase_status.get(candidate_phase) or "").strip().lower()
            if candidate_status == "completed":
                return candidate_phase
        return None

    def _latest_artifact_for_phase(self, mission_id: str, phase: str) -> dict[str, Any] | None:
        listed = self._artifacts["list_artifacts"]({"mission_id": mission_id, "phase": phase})
        artifacts = list(listed.get("artifacts") or [])
        if not artifacts:
            return None

        def sort_key(item: dict[str, Any]) -> tuple[str, str]:
            return (str(item.get("updated_at") or ""), str(item.get("created_at") or ""))

        artifacts.sort(key=sort_key)
        return artifacts[-1]

    def _next_round_for_seed(self, mission_id: str, phase: str) -> int:
        listed = self._events["list_events"](
            {
                "topics": [TOPIC_PHASE_REQUESTED],
                "mission_id": mission_id,
            }
        )
        max_round = 0
        for event in listed.get("events") or []:
            payload = event.get("payload") or {}
            if not isinstance(payload, dict):
                continue
            if str(payload.get("phase") or "") != phase:
                continue
            round_value = payload.get("round")
            if isinstance(round_value, int) and not isinstance(round_value, bool):
                max_round = max(max_round, round_value)
        return max_round + 1 if max_round > 0 else 1

    def _follow_up_phase_note(self, *, result: RoleTaskResult, round_number: int) -> str:
        lines = [f"Follow-up round {round_number}: {result.summary}".strip()]
        if result.required_changes:
            lines.append("Required changes: " + "; ".join(result.required_changes))
        if result.follow_ups:
            lines.append("Follow-ups: " + "; ".join(result.follow_ups))
        if result.unresolved_questions:
            lines.append("Open questions: " + "; ".join(result.unresolved_questions))
        return "\n".join(lines)

    def _phase_to_seed_for_mission(self, mission: dict[str, Any]) -> str | None:
        phase_status = dict(mission.get("phase_status") or {})
        initial_status = str(phase_status.get(self.config.initial_phase) or "").strip().lower()
        if not initial_status:
            return self.config.initial_phase

        mission_status = str(mission.get("status") or "").strip().lower()
        if mission_status not in {"in_progress", "incomplete"}:
            return None

        ordered_phases = list(self.config.phase_roles.keys())
        active_statuses = {"requested", "in_progress", "needs_follow_up"}
        for phase in ordered_phases:
            status = str(phase_status.get(phase) or "").strip().lower()
            if status in active_statuses:
                return phase

        all_previous_completed = True
        for phase in ordered_phases:
            status = str(phase_status.get(phase) or "").strip().lower()
            if not status:
                if all_previous_completed:
                    return phase
                return None
            if status != "completed":
                all_previous_completed = False
        return None

    def _pending_phase_request_keys(self) -> set[tuple[str, str]]:
        state = self._events["get_consumer_state"]({"consumer_id": self.config.consumer_id})["consumer_state"]
        last_acked_sequence = int(state.get("last_acked_sequence") or 0)
        listed = self._events["list_events"](
            {
                "topics": [TOPIC_PHASE_REQUESTED],
                "after_sequence": last_acked_sequence,
            }
        )
        keys: set[tuple[str, str]] = set()
        for event in listed.get("events") or []:
            mission_id = event.get("mission_id")
            payload = event.get("payload") or {}
            phase = payload.get("phase") if isinstance(payload, dict) else None
            if isinstance(mission_id, str) and mission_id and isinstance(phase, str) and phase:
                keys.add((mission_id, phase))
        return keys

    def _phase_objective(self, mission: dict[str, Any]) -> str:
        title = str(mission.get("title") or "").strip()
        description = str(mission.get("description") or "").strip()
        if title and description:
            return f"{title}: {description}"
        return title or description or "Complete the mission."
