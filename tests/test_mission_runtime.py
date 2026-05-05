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


if __name__ == "__main__":
    unittest.main()
