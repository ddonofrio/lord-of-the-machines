from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Protocol

from lord_of_the_machines.agent_tools import (
    ArtifactRegistryTool,
    EventBusTool,
    KanbanBoardTool,
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

MAX_PHASE_NOTE_CHARS = 1_500
MAX_FOLLOW_UP_SUMMARY_CHARS = 1_200
MAX_FOLLOW_UP_ITEM_CHARS = 300
MAX_FOLLOW_UP_ITEMS = 8
MAX_FOLLOW_UP_HISTORY = 2
MAX_ARTIFACT_CONTEXT_CONTENT_CHARS = 6_000
MAX_STALE_FOLLOW_UP_REPEAT_COUNT = 2
TASK_ID_VALUE_RE = re.compile(r"^K-\d{6,}$")


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
            "qa": "qa_agent",
        }
    )
    phase_transitions: dict[str, str] = field(
        default_factory=lambda: {
            "product_direction": "product_requirements",
            "product_requirements": "technical_design",
            "technical_design": "development_plan",
            "development_plan": "implementation",
            "implementation": "qa",
            "qa": None,
        }
    )
    auto_schedule_next_phase: bool = True
    enable_implementation_task_queue: bool = True
    implementation_task_metadata_key: str = "implementation_tasks"
    task_board_done_column: str = "90-done"
    task_board_blocked_column: str = "99-blocked"
    task_board_done_statuses: tuple[str, ...] = ("done", "completed", "closed")
    task_board_phase_columns: dict[str, str] = field(
        default_factory=lambda: {
            "product_direction": "01-product-direction",
            "product_requirements": "02-product-requirements",
            "technical_design": "03-technical-design",
            "development_plan": "04-development-plan",
            "implementation": "05-implementation",
            "qa": "90-done",
        }
    )


@dataclass(slots=True)
class MissionRuntime:
    mission_registry: MissionRegistryTool
    event_bus: EventBusTool
    artifact_registry: ArtifactRegistryTool
    role_executors: dict[str, RoleExecutor]
    kanban_board: KanbanBoardTool | None = None
    config: MissionRuntimeConfig = field(default_factory=MissionRuntimeConfig)
    _mission: dict[str, Any] = field(init=False)
    _events: dict[str, Any] = field(init=False)
    _artifacts: dict[str, Any] = field(init=False)
    _kanban: dict[str, Any] | None = field(init=False, default=None)
    _logger: Any = field(init=False)
    _seeded_phase_keys: set[tuple[str, str]] = field(init=False, default_factory=set)

    def __post_init__(self) -> None:
        self._mission = self.mission_registry.handlers()
        self._events = self.event_bus.handlers()
        self._artifacts = self.artifact_registry.handlers()
        self._kanban = self.kanban_board.handlers() if self.kanban_board is not None else None
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
            if (
                phase_to_seed == "implementation"
                and self.config.enable_implementation_task_queue
                and self._kanban is not None
            ):
                seeded_task_event = self._seed_next_implementation_task_event(
                    mission_id=mission_id,
                    mission=mission,
                    phase=phase_to_seed,
                    role=role,
                    objective=objective,
                    round_number=1,
                    claimed_by=role,
                )
                if seeded_task_event is not None:
                    seeded.append(seeded_task_event)
                    self._seeded_phase_keys.add((mission_id, phase_to_seed))
                    continue
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
        task_id_value = payload.get("task_id")
        task_id = str(task_id_value).strip() if isinstance(task_id_value, str) and task_id_value.strip() else None
        context_payload = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        if task_id and isinstance(context_payload, dict):
            task_context = self._board_task_context(task_id)
            if task_context and "board_task" not in context_payload:
                context_payload = dict(context_payload)
                context_payload["board_task"] = task_context

        executor = self.role_executors.get(role)
        if executor is None:
            raise ValueError(f"No role executor registered for role '{role}'.")

        request = RoleTaskRequest.from_mapping(
            {
                "objective": objective,
                "mission_id": mission_id,
                "phase": phase,
                "task_id": task_id,
                "context": context_payload,
                "constraints": payload.get("constraints") if isinstance(payload.get("constraints"), list) else [],
                "max_rounds": payload.get("max_rounds") or 1,
                "continue_previous": bool(payload.get("continue_previous") is True),
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
            if (
                phase == "implementation"
                and self.config.enable_implementation_task_queue
                and self._kanban is not None
                and request.task_id
            ):
                queue_outcome = self._handle_completed_implementation_task(
                    mission_id=mission_id,
                    role=role,
                    request=request,
                    result=result,
                )
                if queue_outcome is not None:
                    return queue_outcome
            phase_summary = self._trim_text(result.summary, MAX_PHASE_NOTE_CHARS)
            self._mission["update_mission_phase"](
                {
                    "mission_id": mission_id,
                    "phase": phase,
                    "status": "completed",
                    "notes": phase_summary,
                }
            )
            self._publish_phase_completed_event(
                mission_id=mission_id,
                phase=phase,
                role=role,
                summary=phase_summary,
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
                    "summary": phase_summary,
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
                    "summary": phase_summary,
                    "artifact_published": artifact is not None,
                    "next_phase_scheduled": next_phase_event is not None,
                },
            )
            return {"status": result.status, "artifact": artifact, "next_phase_event": next_phase_event}

        if result.status == STATUS_NEEDS_FOLLOW_UP:
            result_summary = self._trim_text(
                self._sanitize_follow_up_summary(result),
                MAX_FOLLOW_UP_SUMMARY_CHARS,
            )
            phase_note = self._follow_up_phase_note(
                result=result,
                round_number=round_number,
                summary=result_summary,
            )
            note_with_limit = self._trim_text(phase_note, MAX_PHASE_NOTE_CHARS)
            if round_number >= self.config.max_follow_up_rounds:
                self._mission["update_mission_phase"](
                    {
                        "mission_id": mission_id,
                        "phase": phase,
                        "status": "in_progress",
                        "notes": (
                            f"{note_with_limit}\n\n"
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
                        "summary": result_summary,
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
                        "summary": result_summary,
                    },
                )
                return {
                    "status": "incomplete",
                    "reason": "follow_up_round_limit",
                    "summary": result_summary,
                }

            self._mission["update_mission_phase"](
                {
                    "mission_id": mission_id,
                    "phase": phase,
                    "status": "in_progress",
                    "notes": note_with_limit,
                }
            )
            follow_up_context = dict(request.context) if isinstance(request.context, dict) else {}
            follow_up_history = list(follow_up_context.get("follow_up_history") or [])
            previous_summary = ""
            if follow_up_history:
                previous_entry = follow_up_history[-1]
                if isinstance(previous_entry, dict):
                    previous_summary = str(previous_entry.get("summary") or "").strip()
            stale_repeat_count = int(follow_up_context.get("stale_follow_up_repeat_count") or 0)
            if previous_summary and previous_summary == result_summary:
                stale_repeat_count += 1
            else:
                stale_repeat_count = 0
            if stale_repeat_count >= MAX_STALE_FOLLOW_UP_REPEAT_COUNT:
                self._mission["update_mission_phase"](
                    {
                        "mission_id": mission_id,
                        "phase": phase,
                        "status": "in_progress",
                        "notes": (
                            f"{note_with_limit}\n\n"
                            "Follow-up stalled with repeated outputs; mission is marked as incomplete for this run."
                        ).strip(),
                    }
                )
                self._mission["update_mission_status"](
                    {
                        "mission_id": mission_id,
                        "status": "incomplete",
                        "reason": f"Phase '{phase}' stalled with repeated follow-up outputs.",
                    }
                )
                log_json(
                    self._logger,
                    "mission_runtime.phase_incomplete.stalled_follow_up",
                    {
                        "mission_id": mission_id,
                        "phase": phase,
                        "role": role,
                        "round": round_number,
                        "summary": result_summary,
                        "stale_repeat_count": stale_repeat_count,
                    },
                )
                log_timeline(
                    actor=self.config.consumer_id,
                    action="phase incomplete (stalled follow-up)",
                    mission_id=mission_id,
                    phase=phase,
                    details={
                        "role": role,
                        "round": round_number,
                        "summary": result_summary,
                        "stale_repeat_count": stale_repeat_count,
                    },
                )
                return {
                    "status": "incomplete",
                    "reason": "stalled_follow_up_loop",
                    "summary": result_summary,
                }
            follow_up_feedback = {
                "round": round_number,
                "summary": result_summary,
                "required_changes": self._trim_list(result.required_changes),
                "unresolved_questions": self._trim_list(result.unresolved_questions),
                "follow_ups": self._trim_list(result.follow_ups),
            }
            follow_up_history.append(follow_up_feedback)
            follow_up_context["follow_up_history"] = follow_up_history[-MAX_FOLLOW_UP_HISTORY:]
            follow_up_context["follow_up_feedback"] = follow_up_feedback
            follow_up_context["stale_follow_up_repeat_count"] = stale_repeat_count
            follow_up_payload = {
                "phase": phase,
                "role": role,
                "objective": request.objective,
                "task_id": request.task_id,
                "context": follow_up_context,
                "constraints": request.constraints,
                "max_rounds": request.max_rounds,
                "continue_previous": self._should_continue_previous(
                    result=result,
                    phase=phase,
                    role=role,
                ),
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
                    "summary": result_summary,
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
                    "summary": result_summary,
                },
            )
            return {
                "status": STATUS_NEEDS_FOLLOW_UP,
                "round": round_number + 1,
                "summary": result_summary,
            }

        phase_summary = self._trim_text(result.summary, MAX_PHASE_NOTE_CHARS)
        self._mission["update_mission_phase"](
            {
                "mission_id": mission_id,
                "phase": phase,
                "status": result.status,
                "notes": phase_summary,
            }
        )
        self._mission["update_mission_status"](
            {
                "mission_id": mission_id,
                "status": "blocked" if result.status == STATUS_BLOCKED else "in_progress",
                "reason": phase_summary or f"Phase '{phase}' ended with status '{result.status}'.",
            }
        )
        self._publish_phase_failed_event(
            mission_id=mission_id,
            phase=phase,
            role=role,
            summary=phase_summary or f"Phase returned status '{result.status}'.",
        )
        log_json(
            self._logger,
            "mission_runtime.phase_failed",
            {
                "mission_id": mission_id,
                "phase": phase,
                "role": role,
                "status": result.status,
                "summary": phase_summary,
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
                "summary": phase_summary,
            },
        )
        return {"status": result.status, "summary": phase_summary}

    def _handle_completed_implementation_task(
        self,
        *,
        mission_id: str,
        role: str,
        request: RoleTaskRequest,
        result: RoleTaskResult,
    ) -> dict[str, Any] | None:
        if self._kanban is None:
            return None
        implementation_column = self._implementation_column()
        done_column = self.config.task_board_done_column
        done_status = self._task_board_done_statuses()[0]
        task_id = str(request.task_id or "").strip()
        if not task_id:
            return None

        try:
            self._kanban["move_task"](
                {
                    "task_id": task_id,
                    "to_column": done_column,
                    "actor": role,
                    "status": done_status,
                    "note": f"Completed by {role}. {self._trim_text(result.summary, 400)}",
                }
            )
        except Exception as exc:  # pragma: no cover - defensive guard
            log_json(
                self._logger,
                "mission_runtime.task_queue.complete_move_failed",
                {
                    "mission_id": mission_id,
                    "task_id": task_id,
                    "error": str(exc),
                },
            )

        pending_tasks = self._pending_implementation_tasks(mission_id)
        if not pending_tasks:
            return None

        mission = self._mission["get_mission"]({"mission_id": mission_id})["mission"]
        seeded_event = self._seed_next_implementation_task_event(
            mission_id=mission_id,
            mission=mission,
            phase="implementation",
            role=role,
            objective=self._phase_objective(mission),
            round_number=1,
            claimed_by=role,
        )
        if seeded_event is not None:
            next_task_id = str((seeded_event.get("payload") or {}).get("task_id") or "")
            note = (
                f"Completed task {task_id}. "
                f"Queued next implementation task {next_task_id or '(unknown)'}."
            )
            self._mission["update_mission_phase"](
                {
                    "mission_id": mission_id,
                    "phase": "implementation",
                    "status": "in_progress",
                    "notes": self._trim_text(note, MAX_PHASE_NOTE_CHARS),
                }
            )
            log_timeline(
                actor=self.config.consumer_id,
                action="implementation task queued",
                mission_id=mission_id,
                phase="implementation",
                details={
                    "completed_task_id": task_id,
                    "next_task_id": next_task_id,
                    "remaining_tasks": len(pending_tasks),
                },
            )
            return {
                "status": "in_progress",
                "reason": "implementation_tasks_remaining",
                "completed_task_id": task_id,
                "next_task_event": seeded_event,
            }

        blocked_note = (
            f"Completed task {task_id}. Remaining implementation tasks exist "
            "but no claimable task is ready (likely dependency or status issue)."
        )
        self._mission["update_mission_phase"](
            {
                "mission_id": mission_id,
                "phase": "implementation",
                "status": "in_progress",
                "notes": self._trim_text(blocked_note, MAX_PHASE_NOTE_CHARS),
            }
        )
        self._mission["update_mission_status"](
            {
                "mission_id": mission_id,
                "status": "incomplete",
                "reason": "Implementation queue has pending tasks with no claimable candidate.",
            }
        )
        return {
            "status": "incomplete",
            "reason": "implementation_queue_blocked",
            "completed_task_id": task_id,
            "remaining_tasks": len(pending_tasks),
        }

    def _implementation_column(self) -> str:
        return self.config.task_board_phase_columns.get("implementation", "05-implementation")

    def _task_board_done_statuses(self) -> tuple[str, ...]:
        statuses = [str(item).strip().lower() for item in self.config.task_board_done_statuses if str(item).strip()]
        if not statuses:
            return ("done",)
        return tuple(statuses)

    def _pending_implementation_tasks(self, mission_id: str) -> list[dict[str, Any]]:
        if self._kanban is None:
            return []
        listed = self._kanban["list_tasks"](
            {
                "column": self._implementation_column(),
                "include_body": False,
                "mission_id": mission_id,
            }
        )
        columns = list(listed.get("columns") or [])
        if not columns:
            return []
        tasks = list(columns[0].get("tasks") or [])
        done_statuses = set(self._task_board_done_statuses())
        return [task for task in tasks if str(task.get("status") or "").strip().lower() not in done_statuses]

    def _board_task_context(self, task_id: str) -> dict[str, Any] | None:
        if self._kanban is None:
            return None
        try:
            loaded = self._kanban["get_task"]({"task_id": task_id, "include_body": True})
        except FileNotFoundError:
            return None
        task = loaded.get("task")
        if not isinstance(task, dict):
            return None
        body = str(task.get("body") or "")
        if len(body) > MAX_ARTIFACT_CONTEXT_CONTENT_CHARS:
            task = dict(task)
            task["body"] = (
                body[:MAX_ARTIFACT_CONTEXT_CONTENT_CHARS]
                + "\n\n...[task body truncated by runtime context budget]..."
            )
            task["body_truncated"] = True
        return task

    def _seed_next_implementation_task_event(
        self,
        *,
        mission_id: str,
        mission: dict[str, Any],
        phase: str,
        role: str,
        objective: str,
        round_number: int,
        claimed_by: str,
    ) -> dict[str, Any] | None:
        if self._kanban is None:
            return None
        implementation_column = self._implementation_column()

        in_progress_listed = self._kanban["list_tasks"](
            {
                "column": implementation_column,
                "include_body": True,
                "mission_id": mission_id,
                "statuses": ["in_progress"],
            }
        )
        in_progress_columns = list(in_progress_listed.get("columns") or [])
        in_progress_tasks = list(in_progress_columns[0].get("tasks") or []) if in_progress_columns else []
        in_progress_tasks.sort(
            key=lambda item: (
                self._priority_rank(str(item.get("priority") or "P2")),
                str(item.get("created_at") or ""),
                str(item.get("task_id") or ""),
            )
        )
        task = in_progress_tasks[0] if in_progress_tasks else None
        if task is None:
            claimed = self._kanban["claim_next_task"](
                {
                    "column": implementation_column,
                    "agent_id": claimed_by,
                    "agent_role": role,
                    "statuses": ["ready"],
                    "claimed_status": "in_progress",
                    "respect_dependencies": True,
                    "done_statuses": list(self._task_board_done_statuses()),
                }
            )
            if not claimed.get("claimed"):
                return None
            task = claimed.get("task")
        if not isinstance(task, dict):
            return None

        task_id = str(task.get("task_id") or "").strip()
        if not task_id:
            return None
        task_title = str(task.get("title") or "Implementation task").strip()
        task_body = str(task.get("body") or "").strip()
        task_objective = f"{objective}\n\nTask {task_id}: {task_title}"
        if task_body:
            task_objective = f"{task_objective}\n\nTask details:\n{task_body}"
        context = self._seed_context_for_phase(mission, phase)
        context["task_execution_mode"] = "kanban_ticket"
        context["board_task"] = task

        event_result = self._events["publish_event"](
            {
                "topic": TOPIC_PHASE_REQUESTED,
                "mission_id": mission_id,
                "producer_role": self.config.consumer_id,
                "payload": {
                    "phase": phase,
                    "role": role,
                    "objective": task_objective,
                    "task_id": task_id,
                    "context": context,
                    "round": round_number,
                },
            }
        )
        return event_result["event"]

    def _priority_rank(self, value: str) -> int:
        normalized = value.strip().upper()
        if normalized == "P0":
            return 0
        if normalized == "P1":
            return 1
        if normalized == "P2":
            return 2
        return 3

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

        if (
            current_phase == "development_plan"
            and next_phase == "implementation"
            and self.config.enable_implementation_task_queue
            and self._kanban is not None
        ):
            queue_event = self._seed_implementation_queue_from_metadata(
                mission=mission,
                mission_id=mission_id,
                role=self._role_for_phase(next_phase),
                objective=self._phase_objective(mission),
                completed_result=completed_result,
            )
            if queue_event is not None:
                return queue_event

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

    def _seed_implementation_queue_from_metadata(
        self,
        *,
        mission: dict[str, Any],
        mission_id: str,
        role: str,
        objective: str,
        completed_result: RoleTaskResult,
    ) -> dict[str, Any] | None:
        if self._kanban is None:
            return None
        metadata = completed_result.metadata if isinstance(completed_result.metadata, dict) else {}
        raw_tasks = metadata.get(self.config.implementation_task_metadata_key)
        if not isinstance(raw_tasks, list) or not raw_tasks:
            return None

        created_tasks: list[dict[str, Any]] = []
        key_to_task_id: dict[str, str] = {}
        dependency_keys: dict[str, list[str]] = {}
        implementation_column = self._implementation_column()
        for index, raw_item in enumerate(raw_tasks):
            if not isinstance(raw_item, dict):
                continue
            title = str(raw_item.get("title") or "").strip()
            if not title:
                continue
            description = str(raw_item.get("description") or raw_item.get("details") or "").strip()
            priority = str(raw_item.get("priority") or "P2").strip().upper()
            if priority not in {"P0", "P1", "P2", "P3"}:
                priority = "P2"
            task_type = str(raw_item.get("task_type") or "implementation").strip().lower() or "implementation"
            task_key = str(raw_item.get("key") or raw_item.get("task_key") or f"TASK-{index + 1}").strip()
            created = self._kanban["create_task"](
                {
                    "column": implementation_column,
                    "title": title,
                    "description": description,
                    "status": "ready",
                    "priority": priority,
                    "task_type": task_type,
                    "assignee_role": "software_developer",
                    "metadata": {
                        "mission_id": mission_id,
                        "phase": "implementation",
                        "source_phase": "development_plan",
                        "task_key": task_key,
                    },
                }
            )
            task = created.get("task")
            if isinstance(task, dict):
                created_tasks.append(task)
                created_task_id = str(task.get("task_id") or "").strip()
                if created_task_id:
                    key_to_task_id[task_key] = created_task_id
                    raw_depends_on = raw_item.get("depends_on")
                    if isinstance(raw_depends_on, list):
                        dependency_keys[created_task_id] = [str(item).strip() for item in raw_depends_on if str(item).strip()]

        for task_id, keys in dependency_keys.items():
            resolved_dependencies: list[str] = []
            for key in keys:
                candidate = key.strip().upper()
                if TASK_ID_VALUE_RE.fullmatch(candidate):
                    resolved_dependencies.append(candidate)
                    continue
                mapped = key_to_task_id.get(key)
                if mapped:
                    resolved_dependencies.append(mapped)
            if resolved_dependencies:
                self._kanban["update_task"](
                    {
                        "task_id": task_id,
                        "depends_on": resolved_dependencies,
                        "actor": self.config.consumer_id,
                    }
                )

        if not created_tasks:
            return None

        self._mission["update_mission_phase"](
            {
                "mission_id": mission_id,
                "phase": "implementation",
                "status": "requested",
                "notes": (
                    f"Implementation queue initialized with {len(created_tasks)} tasks "
                    f"from '{self.config.implementation_task_metadata_key}'."
                ),
            }
        )
        seeded_event = self._seed_next_implementation_task_event(
            mission_id=mission_id,
            mission=mission,
            phase="implementation",
            role=role,
            objective=objective,
            round_number=1,
            claimed_by=role,
        )
        if seeded_event is None:
            return {
                "queued_tasks": len(created_tasks),
                "seeded_task_event": None,
            }
        return {
            "queued_tasks": len(created_tasks),
            "seeded_task_event": seeded_event,
        }

    def _artifact_context(self, artifact: dict[str, Any] | None) -> dict[str, Any] | None:
        if not artifact:
            return None
        content = str(artifact.get("content") or "")
        truncated = len(content) > MAX_ARTIFACT_CONTEXT_CONTENT_CHARS
        if truncated:
            content = (
                content[:MAX_ARTIFACT_CONTEXT_CONTENT_CHARS]
                + "\n\n...[artifact content truncated by runtime context budget]..."
            )
        return {
            "artifact_id": artifact.get("artifact_id"),
            "artifact_type": artifact.get("artifact_type"),
            "title": artifact.get("title"),
            "format": artifact.get("format"),
            "content": content,
            "content_truncated": truncated,
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
            "phase_notes": {
                phase_name: self._trim_text(str(note or ""), MAX_PHASE_NOTE_CHARS)
                for phase_name, note in phase_notes.items()
            },
            "resume_phase": phase,
            "resume_phase_status": phase_status.get(phase),
            "resume_phase_notes": self._trim_text(str(phase_notes.get(phase) or ""), MAX_PHASE_NOTE_CHARS),
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
        if mission_id and phase == "implementation" and self._kanban is not None:
            pending_tasks = self._pending_implementation_tasks(mission_id)
            if pending_tasks:
                context["implementation_queue"] = {
                    "pending_count": len(pending_tasks),
                    "pending_task_ids": [str(item.get("task_id") or "") for item in pending_tasks[:10]],
                }
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

    def _follow_up_phase_note(self, *, result: RoleTaskResult, round_number: int, summary: str) -> str:
        lines = [f"Follow-up round {round_number}: {summary}".strip()]
        if result.required_changes:
            lines.append("Required changes: " + "; ".join(result.required_changes))
        if result.follow_ups:
            lines.append("Follow-ups: " + "; ".join(result.follow_ups))
        if result.unresolved_questions:
            lines.append("Open questions: " + "; ".join(result.unresolved_questions))
        return "\n".join(lines)

    def _should_continue_previous(self, *, result: RoleTaskResult, phase: str, role: str) -> bool:
        # Technical design rounds often require many tool calls and can quickly hit
        # context/rate limits. Keep follow-up context explicit in payload, but
        # reset conversation history between rounds for this phase.
        if phase == "technical_design" and role == "software_architect":
            return False
        if phase == "development_plan" and role == "software_development_manager":
            return False
        if phase == "implementation" and role == "software_developer":
            return False
        if self._is_recoverable_limit_result(result):
            return False
        return True

    def _sanitize_follow_up_summary(self, result: RoleTaskResult) -> str:
        summary = str(result.summary or "").strip()
        if not summary:
            return summary
        if self._is_recoverable_limit_result(result):
            return (
                "Previous round hit a recoverable execution/context limit. "
                "Continue from the current workspace state with fewer, more focused tool calls, "
                "and submit concrete output for this phase."
            )
        return summary

    def _is_recoverable_limit_result(self, result: RoleTaskResult) -> bool:
        metadata = result.metadata if isinstance(result.metadata, dict) else {}
        if metadata.get("forced_structured_submit"):
            return True
        if not metadata.get("normalized_from_failed"):
            return False
        summary = str(result.summary or "").lower()
        signals = (
            "maximum tool rounds",
            "tool rounds",
            "request too large",
            "context window",
            "rate limit",
            "no additional exploration",
            "recoverable execution limit",
        )
        return any(signal in summary for signal in signals)

    def _trim_text(self, value: str, max_chars: int) -> str:
        if max_chars <= 0:
            return ""
        if len(value) <= max_chars:
            return value
        suffix = "...[truncated]"
        if max_chars <= len(suffix):
            return suffix[:max_chars]
        return value[: max_chars - len(suffix)] + suffix

    def _trim_list(self, items: list[str]) -> list[str]:
        trimmed: list[str] = []
        for item in list(items)[:MAX_FOLLOW_UP_ITEMS]:
            trimmed.append(self._trim_text(str(item), MAX_FOLLOW_UP_ITEM_CHARS))
        return trimmed

    def _phase_to_seed_for_mission(self, mission: dict[str, Any]) -> str | None:
        phase_status = dict(mission.get("phase_status") or {})
        initial_status = str(phase_status.get(self.config.initial_phase) or "").strip().lower()
        if not initial_status:
            return self.config.initial_phase

        mission_status = str(mission.get("status") or "").strip().lower()
        if mission_status not in {"in_progress", "incomplete"}:
            return None

        ordered_phases = list(self.config.phase_roles.keys())
        active_statuses = {"requested", "in_progress", "needs_follow_up", "failed"}
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
