from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lord_of_the_machines.agent_tools import (
    ArtifactRegistryTool,
    ArtifactRegistryToolConfig,
    EventBusTool,
    EventBusToolConfig,
    MissionRegistryTool,
    MissionRegistryToolConfig,
)
from lord_of_the_machines.mission import MissionRuntime, MissionRuntimeConfig, RoleTaskRequest, RoleTaskResult


class FakeRoleExecutor:
    def __init__(self, result: RoleTaskResult) -> None:
        self.result = result
        self.calls: list[RoleTaskRequest] = []

    def execute_task(self, request: RoleTaskRequest) -> RoleTaskResult:
        self.calls.append(request)
        return self.result


class MissionRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        self.mission_registry = MissionRegistryTool(
            root / "missions",
            config=MissionRegistryToolConfig(root_path=root / "missions"),
        )
        self.event_bus = EventBusTool(
            root / "events",
            config=EventBusToolConfig(root_path=root / "events"),
        )
        self.artifact_registry = ArtifactRegistryTool(
            root / "artifacts",
            config=ArtifactRegistryToolConfig(root_path=root / "artifacts"),
        )

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def test_seed_pending_missions_creates_phase_requested_event(self) -> None:
        self.mission_registry.handlers()["create_mission"](
            {
                "mission_id": "mission_alpha",
                "title": "Alpha",
                "description": "Build first loop",
            }
        )
        runtime = MissionRuntime(
            mission_registry=self.mission_registry,
            event_bus=self.event_bus,
            artifact_registry=self.artifact_registry,
            role_executors={},
        )

        seeded = runtime.seed_pending_missions()

        self.assertEqual(len(seeded["seeded_events"]), 1)
        listed = self.event_bus.handlers()["list_events"]({"topics": ["mission.phase.requested"]})
        self.assertEqual(len(listed["events"]), 1)
        self.assertEqual(listed["events"][0]["mission_id"], "mission_alpha")

    def test_run_once_executes_role_updates_phase_and_publishes_artifact(self) -> None:
        self.mission_registry.handlers()["create_mission"](
            {
                "mission_id": "mission_beta",
                "title": "Beta",
                "description": "Deliver product direction",
            }
        )
        executor = FakeRoleExecutor(
            RoleTaskResult(
                status="completed",
                summary="HLR completed",
                artifact_type="hlr",
                artifact_title="High Level Product Requirement",
                artifact_content="# HLR",
                tags=["product_direction"],
            )
        )
        runtime = MissionRuntime(
            mission_registry=self.mission_registry,
            event_bus=self.event_bus,
            artifact_registry=self.artifact_registry,
            role_executors={"product_director": executor},
            config=MissionRuntimeConfig(max_events_per_run=5, phase_transitions={}),
        )

        runtime.seed_pending_missions()
        result = runtime.run_once()

        self.assertEqual(len(result["processed"]), 1)
        self.assertTrue(result["processed"][0]["ok"])
        mission = self.mission_registry.handlers()["get_mission"]({"mission_id": "mission_beta"})["mission"]
        self.assertEqual(mission["phase_status"]["product_direction"], "completed")
        self.assertEqual(mission["status"], "completed")

        artifacts = self.artifact_registry.handlers()["list_artifacts"]({"mission_id": "mission_beta"})
        self.assertEqual(len(artifacts["artifacts"]), 1)
        self.assertEqual(artifacts["artifacts"][0]["artifact_type"], "hlr")

    def test_needs_follow_up_requeues_phase_until_completion(self) -> None:
        self.mission_registry.handlers()["create_mission"](
            {
                "mission_id": "mission_gamma",
                "title": "Gamma",
                "description": "Iterate requirements",
            }
        )

        class FollowUpExecutor:
            def __init__(self) -> None:
                self.count = 0

            def execute_task(self, request: RoleTaskRequest) -> RoleTaskResult:
                self.count += 1
                if self.count == 1:
                    return RoleTaskResult(status="needs_follow_up", summary="Need one more round")
                return RoleTaskResult(status="completed", summary="Done after follow-up")

        executor = FollowUpExecutor()
        runtime = MissionRuntime(
            mission_registry=self.mission_registry,
            event_bus=self.event_bus,
            artifact_registry=self.artifact_registry,
            role_executors={"product_director": executor},
            config=MissionRuntimeConfig(max_events_per_run=5, max_follow_up_rounds=3),
        )

        runtime.seed_pending_missions()
        first_pass = runtime.run_once()
        second_pass = runtime.run_once()

        self.assertEqual(first_pass["processed"][0]["outcome"]["status"], "needs_follow_up")
        self.assertEqual(second_pass["processed"][0]["outcome"]["status"], "completed")

    def test_follow_up_payload_includes_feedback_and_continue_previous(self) -> None:
        self.mission_registry.handlers()["create_mission"](
            {
                "mission_id": "mission_followup_payload",
                "title": "Follow-Up Payload",
                "description": "Ensure follow-up context carries actionable feedback.",
            }
        )
        executor = FakeRoleExecutor(
            RoleTaskResult(
                status="needs_follow_up",
                summary="Acceptance checks failed.",
                required_changes=["Add follow-up mission to config/missions.json."],
                follow_ups=["Update missions file and rerun checks."],
            )
        )
        runtime = MissionRuntime(
            mission_registry=self.mission_registry,
            event_bus=self.event_bus,
            artifact_registry=self.artifact_registry,
            role_executors={"product_director": executor},
            config=MissionRuntimeConfig(max_events_per_run=5, max_follow_up_rounds=3, phase_transitions={}),
        )

        runtime.seed_pending_missions()
        runtime.run_once()

        events = self.event_bus.handlers()["list_events"](
            {"topics": ["mission.phase.requested"], "mission_id": "mission_followup_payload"}
        )["events"]
        self.assertEqual(len(events), 2)
        follow_up_payload = events[-1]["payload"]
        self.assertEqual(follow_up_payload["round"], 2)
        self.assertTrue(follow_up_payload["continue_previous"])
        self.assertEqual(
            follow_up_payload["context"]["follow_up_feedback"]["required_changes"],
            ["Add follow-up mission to config/missions.json."],
        )

        mission = self.mission_registry.handlers()["get_mission"]({"mission_id": "mission_followup_payload"})[
            "mission"
        ]
        self.assertIn("Required changes:", mission["phase_notes"]["product_direction"])

    def test_follow_up_second_execution_uses_continue_previous(self) -> None:
        self.mission_registry.handlers()["create_mission"](
            {
                "mission_id": "mission_followup_continue_previous",
                "title": "Follow-Up Continue Previous",
                "description": "Second follow-up run should preserve prior model context.",
            }
        )

        class TwoStepExecutor:
            def __init__(self) -> None:
                self.calls: list[RoleTaskRequest] = []

            def execute_task(self, request: RoleTaskRequest) -> RoleTaskResult:
                self.calls.append(request)
                if len(self.calls) == 1:
                    return RoleTaskResult(status="needs_follow_up", summary="Need another round.")
                return RoleTaskResult(status="completed", summary="Done.")

        executor = TwoStepExecutor()
        runtime = MissionRuntime(
            mission_registry=self.mission_registry,
            event_bus=self.event_bus,
            artifact_registry=self.artifact_registry,
            role_executors={"product_director": executor},
            config=MissionRuntimeConfig(max_events_per_run=5, max_follow_up_rounds=3, phase_transitions={}),
        )

        runtime.seed_pending_missions()
        runtime.run_once()
        runtime.run_once()

        self.assertEqual(len(executor.calls), 2)
        self.assertFalse(executor.calls[0].continue_previous)
        self.assertTrue(executor.calls[1].continue_previous)

    def test_contract_violation_forces_follow_up(self) -> None:
        self.mission_registry.handlers()["create_mission"](
            {
                "mission_id": "mission_contract",
                "title": "Contract",
                "description": "Ensure role output contract enforcement",
            }
        )
        runtime = MissionRuntime(
            mission_registry=self.mission_registry,
            event_bus=self.event_bus,
            artifact_registry=self.artifact_registry,
            role_executors={
                "product_director": FakeRoleExecutor(RoleTaskResult(status="completed", summary=""))
            },
            config=MissionRuntimeConfig(max_events_per_run=5, max_follow_up_rounds=3, phase_transitions={}),
        )

        runtime.seed_pending_missions()
        first_pass = runtime.run_once()

        self.assertEqual(first_pass["processed"][0]["outcome"]["status"], "needs_follow_up")
        follow_up_events = self.event_bus.handlers()["list_events"]({"topics": ["mission.phase.requested"]})["events"]
        self.assertEqual(len(follow_up_events), 2)
        self.assertEqual(follow_up_events[-1]["payload"]["round"], 2)

    def test_repeated_follow_up_summary_marks_phase_incomplete(self) -> None:
        self.mission_registry.handlers()["create_mission"](
            {
                "mission_id": "mission_stalled_follow_up",
                "title": "Stalled Follow-Up",
                "description": "Detect repeated follow-up outputs and stop looping in the same run.",
            }
        )
        repeated_summary = "Need more time to inspect files."
        executor = FakeRoleExecutor(RoleTaskResult(status="needs_follow_up", summary=repeated_summary))
        runtime = MissionRuntime(
            mission_registry=self.mission_registry,
            event_bus=self.event_bus,
            artifact_registry=self.artifact_registry,
            role_executors={"product_director": executor},
            config=MissionRuntimeConfig(max_events_per_run=5, max_follow_up_rounds=6, phase_transitions={}),
        )

        runtime.seed_pending_missions()
        first_pass = runtime.run_once()
        second_pass = runtime.run_once()
        third_pass = runtime.run_once()

        self.assertEqual(first_pass["processed"][0]["outcome"]["status"], "needs_follow_up")
        self.assertEqual(second_pass["processed"][0]["outcome"]["status"], "needs_follow_up")
        self.assertEqual(third_pass["processed"][0]["outcome"]["status"], "incomplete")
        self.assertEqual(third_pass["processed"][0]["outcome"]["reason"], "stalled_follow_up_loop")

        mission = self.mission_registry.handlers()["get_mission"]({"mission_id": "mission_stalled_follow_up"})[
            "mission"
        ]
        self.assertEqual(mission["status"], "incomplete")
        self.assertEqual(mission["phase_status"]["product_direction"], "in_progress")

    def test_completed_phase_schedules_next_phase_when_transition_exists(self) -> None:
        self.mission_registry.handlers()["create_mission"](
            {
                "mission_id": "mission_delta",
                "title": "Delta",
                "description": "From product direction to product requirements",
            }
        )
        runtime = MissionRuntime(
            mission_registry=self.mission_registry,
            event_bus=self.event_bus,
            artifact_registry=self.artifact_registry,
            role_executors={
                "product_director": FakeRoleExecutor(
                    RoleTaskResult(status="completed", summary="Direction ready")
                )
            },
            config=MissionRuntimeConfig(max_events_per_run=5),
        )

        runtime.seed_pending_missions()
        pass_one = runtime.run_once()

        outcome = pass_one["processed"][0]["outcome"]
        self.assertEqual(outcome["status"], "completed")
        self.assertIsNotNone(outcome["next_phase_event"])
        self.assertEqual(outcome["next_phase_event"]["payload"]["phase"], "product_requirements")
        self.assertEqual(outcome["next_phase_event"]["payload"]["role"], "product_manager")

        mission = self.mission_registry.handlers()["get_mission"]({"mission_id": "mission_delta"})["mission"]
        self.assertEqual(mission["phase_status"]["product_direction"], "completed")
        self.assertEqual(mission["phase_status"]["product_requirements"], "requested")
        self.assertEqual(mission["status"], "in_progress")

    def test_seed_pending_missions_resumes_in_progress_phase_without_pending_event(self) -> None:
        self.mission_registry.handlers()["create_mission"](
            {
                "mission_id": "mission_resume",
                "title": "Resume",
                "description": "Resume from an in-progress phase",
            }
        )
        self.mission_registry.handlers()["update_mission_phase"](
            {
                "mission_id": "mission_resume",
                "phase": "product_direction",
                "status": "completed",
                "notes": "Done",
            }
        )
        self.mission_registry.handlers()["update_mission_phase"](
            {
                "mission_id": "mission_resume",
                "phase": "product_requirements",
                "status": "in_progress",
                "notes": "Working",
            }
        )
        self.mission_registry.handlers()["update_mission_status"](
            {
                "mission_id": "mission_resume",
                "status": "in_progress",
                "reason": "Waiting to continue.",
            }
        )
        runtime = MissionRuntime(
            mission_registry=self.mission_registry,
            event_bus=self.event_bus,
            artifact_registry=self.artifact_registry,
            role_executors={},
            config=MissionRuntimeConfig(max_events_per_run=5),
        )

        seeded = runtime.seed_pending_missions()

        self.assertEqual(len(seeded["seeded_events"]), 1)
        self.assertEqual(seeded["seeded_events"][0]["payload"]["phase"], "product_requirements")
        self.assertEqual(seeded["seeded_events"][0]["payload"]["role"], "product_manager")

    def test_seed_pending_missions_resumes_failed_phase_without_pending_event(self) -> None:
        self.mission_registry.handlers()["create_mission"](
            {
                "mission_id": "mission_resume_failed",
                "title": "Resume Failed",
                "description": "Retry failed phase on next run.",
            }
        )
        self.mission_registry.handlers()["update_mission_phase"](
            {
                "mission_id": "mission_resume_failed",
                "phase": "product_direction",
                "status": "completed",
                "notes": "Done",
            }
        )
        self.mission_registry.handlers()["update_mission_phase"](
            {
                "mission_id": "mission_resume_failed",
                "phase": "product_requirements",
                "status": "failed",
                "notes": "Transient failure",
            }
        )
        self.mission_registry.handlers()["update_mission_status"](
            {
                "mission_id": "mission_resume_failed",
                "status": "in_progress",
                "reason": "Should retry failed phase.",
            }
        )
        runtime = MissionRuntime(
            mission_registry=self.mission_registry,
            event_bus=self.event_bus,
            artifact_registry=self.artifact_registry,
            role_executors={},
            config=MissionRuntimeConfig(max_events_per_run=5),
        )

        seeded = runtime.seed_pending_missions()

        self.assertEqual(len(seeded["seeded_events"]), 1)
        self.assertEqual(seeded["seeded_events"][0]["payload"]["phase"], "product_requirements")
        self.assertEqual(seeded["seeded_events"][0]["payload"]["role"], "product_manager")

    def test_seed_pending_missions_includes_resume_context_and_previous_artifact(self) -> None:
        self.mission_registry.handlers()["create_mission"](
            {
                "mission_id": "mission_resume_context",
                "title": "Resume Context",
                "description": "Seed should include previous artifact and phase notes.",
            }
        )
        self.mission_registry.handlers()["update_mission_phase"](
            {
                "mission_id": "mission_resume_context",
                "phase": "product_direction",
                "status": "completed",
                "notes": "Direction done.",
            }
        )
        self.artifact_registry.handlers()["publish_artifact"](
            {
                "mission_id": "mission_resume_context",
                "phase": "product_direction",
                "artifact_type": "product_direction",
                "title": "Direction Artifact",
                "content": "# Direction",
                "producer_role": "product_director",
            }
        )
        self.mission_registry.handlers()["update_mission_phase"](
            {
                "mission_id": "mission_resume_context",
                "phase": "product_requirements",
                "status": "in_progress",
                "notes": "Continue from previous run.",
            }
        )
        self.mission_registry.handlers()["update_mission_status"](
            {
                "mission_id": "mission_resume_context",
                "status": "in_progress",
                "reason": "Waiting for next cycle.",
            }
        )
        runtime = MissionRuntime(
            mission_registry=self.mission_registry,
            event_bus=self.event_bus,
            artifact_registry=self.artifact_registry,
            role_executors={},
            config=MissionRuntimeConfig(max_events_per_run=5),
        )

        seeded = runtime.seed_pending_missions()

        self.assertEqual(len(seeded["seeded_events"]), 1)
        payload = seeded["seeded_events"][0]["payload"]
        context = payload["context"]
        self.assertEqual(context["resume_phase"], "product_requirements")
        self.assertEqual(context["resume_phase_notes"], "Continue from previous run.")
        self.assertEqual(context["previous_phase"], "product_direction")
        self.assertEqual(context["previous_artifact"]["title"], "Direction Artifact")

    def test_seed_pending_missions_avoids_duplicate_phase_request_events(self) -> None:
        self.mission_registry.handlers()["create_mission"](
            {
                "mission_id": "mission_no_duplicate",
                "title": "No Duplicate",
                "description": "Do not duplicate pending phase requests",
            }
        )
        self.mission_registry.handlers()["update_mission_phase"](
            {
                "mission_id": "mission_no_duplicate",
                "phase": "product_direction",
                "status": "completed",
                "notes": "Done",
            }
        )
        self.mission_registry.handlers()["update_mission_phase"](
            {
                "mission_id": "mission_no_duplicate",
                "phase": "product_requirements",
                "status": "in_progress",
                "notes": "Working",
            }
        )
        self.mission_registry.handlers()["update_mission_status"](
            {
                "mission_id": "mission_no_duplicate",
                "status": "in_progress",
                "reason": "Waiting to continue.",
            }
        )
        self.event_bus.handlers()["publish_event"](
            {
                "topic": "mission.phase.requested",
                "mission_id": "mission_no_duplicate",
                "producer_role": "mission_runtime",
                "payload": {
                    "phase": "product_requirements",
                    "role": "product_manager",
                    "objective": "Continue",
                    "round": 2,
                },
            }
        )
        runtime = MissionRuntime(
            mission_registry=self.mission_registry,
            event_bus=self.event_bus,
            artifact_registry=self.artifact_registry,
            role_executors={},
            config=MissionRuntimeConfig(max_events_per_run=5),
        )

        seeded = runtime.seed_pending_missions()

        self.assertEqual(len(seeded["seeded_events"]), 0)


if __name__ == "__main__":
    unittest.main()
