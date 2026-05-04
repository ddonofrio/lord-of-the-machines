from __future__ import annotations

import json
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
from lord_of_the_machines.mission import (
    MissionRunner,
    MissionRunnerConfig,
    MissionRuntime,
    MissionRuntimeConfig,
    RoleTaskRequest,
    RoleTaskResult,
)


class StaticExecutor:
    def __init__(self, result: RoleTaskResult) -> None:
        self.result = result
        self.calls: list[RoleTaskRequest] = []

    def execute_task(self, request: RoleTaskRequest) -> RoleTaskResult:
        self.calls.append(request)
        return self.result


class MissionRunnerTests(unittest.TestCase):
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

    def test_runner_creates_and_executes_single_phase_mission(self) -> None:
        runtime = MissionRuntime(
            mission_registry=self.mission_registry,
            event_bus=self.event_bus,
            artifact_registry=self.artifact_registry,
            role_executors={
                "product_director": StaticExecutor(RoleTaskResult(status="completed", summary="done"))
            },
            config=MissionRuntimeConfig(phase_transitions={}),
        )
        runner = MissionRunner(
            mission_registry=self.mission_registry,
            runtime=runtime,
            config=MissionRunnerConfig(max_cycles=5, idle_cycles_to_stop=1, bootstrap_missions_from_file=False),
        )
        runner.create_mission(
            mission_id="m_runner_1",
            title="Runner Mission",
            description="Single phase mission",
        )

        outcome = runner.run()

        final = {mission["mission_id"]: mission for mission in outcome["final_missions"]}
        self.assertEqual(final["m_runner_1"]["status"], "completed")

    def test_runner_progresses_two_phase_default_workflow(self) -> None:
        runtime = MissionRuntime(
            mission_registry=self.mission_registry,
            event_bus=self.event_bus,
            artifact_registry=self.artifact_registry,
            role_executors={
                "product_director": StaticExecutor(RoleTaskResult(status="completed", summary="direction done")),
                "software_developer": StaticExecutor(RoleTaskResult(status="completed", summary="implementation done")),
            },
            config=MissionRuntimeConfig(max_events_per_run=5),
        )
        runner = MissionRunner(
            mission_registry=self.mission_registry,
            runtime=runtime,
            config=MissionRunnerConfig(max_cycles=8, idle_cycles_to_stop=2, bootstrap_missions_from_file=False),
        )
        runner.create_mission(
            mission_id="m_runner_2",
            title="Two Phase Mission",
            description="Run direction then implementation",
        )

        outcome = runner.run()
        final = {mission["mission_id"]: mission for mission in outcome["final_missions"]}

        self.assertEqual(final["m_runner_2"]["status"], "completed")
        phase_status = final["m_runner_2"]["phase_status"]
        self.assertEqual(phase_status["product_direction"], "completed")
        self.assertEqual(phase_status["implementation"], "completed")

    def test_runner_loads_mission_list_from_json_file(self) -> None:
        mission_file = self._write_missions_file(
            {
                "missions": [
                    {
                        "mission_id": "m_from_json_1",
                        "title": "From JSON 1",
                        "description": "Seeded from mission file",
                    },
                    {
                        "mission_id": "m_from_json_2",
                        "title": "From JSON 2",
                        "description": "Second seeded mission",
                    },
                ]
            }
        )
        runtime = MissionRuntime(
            mission_registry=self.mission_registry,
            event_bus=self.event_bus,
            artifact_registry=self.artifact_registry,
            role_executors={},
            config=MissionRuntimeConfig(max_events_per_run=1),
        )
        runner = MissionRunner(
            mission_registry=self.mission_registry,
            runtime=runtime,
            config=MissionRunnerConfig(
                max_cycles=1,
                seed_each_cycle=False,
                bootstrap_missions_from_file=False,
            ),
        )

        result = runner.create_missions_from_file(mission_file)

        self.assertEqual(result["loaded"], 2)
        self.assertEqual(len(result["created"]), 2)
        missions = self.mission_registry.handlers()["list_missions"]({})
        mission_ids = {mission["mission_id"] for mission in missions["missions"]}
        self.assertIn("m_from_json_1", mission_ids)
        self.assertIn("m_from_json_2", mission_ids)

    def _write_missions_file(self, payload: dict[str, object]) -> Path:
        path = self.artifact_registry.config.root_path.parent / "missions.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path


if __name__ == "__main__":
    unittest.main()
