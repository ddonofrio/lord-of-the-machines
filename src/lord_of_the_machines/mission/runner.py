from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lord_of_the_machines.agent_tools import MissionRegistryTool
from lord_of_the_machines.mission.runtime import MissionRuntime


@dataclass(slots=True)
class MissionRunnerConfig:
    max_cycles: int = 25
    max_events_per_cycle: int = 20
    idle_cycles_to_stop: int = 2
    seed_each_cycle: bool = True


@dataclass(slots=True)
class MissionRunner:
    mission_registry: MissionRegistryTool
    runtime: MissionRuntime
    config: MissionRunnerConfig = field(default_factory=MissionRunnerConfig)
    _mission_handlers: dict[str, Any] = field(init=False)

    def __post_init__(self) -> None:
        self._mission_handlers = self.mission_registry.handlers()

    def create_mission(
        self,
        *,
        title: str,
        description: str,
        mission_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._mission_handlers["create_mission"](
            {
                "mission_id": mission_id,
                "title": title,
                "description": description,
                "metadata": dict(metadata or {}),
            }
        )["mission"]

    def run(self) -> dict[str, Any]:
        cycles: list[dict[str, Any]] = []
        idle_cycles = 0
        for cycle_index in range(1, self.config.max_cycles + 1):
            seeded_events = []
            if self.config.seed_each_cycle:
                seeded_events = list(self.runtime.seed_pending_missions()["seeded_events"])

            run_result = self.runtime.run_once(max_events=self.config.max_events_per_cycle)
            processed = list(run_result.get("processed") or [])
            cycle_summary = {
                "cycle": cycle_index,
                "seeded_events": seeded_events,
                "processed": processed,
                "consumer_state": run_result.get("consumer_state"),
            }
            cycles.append(cycle_summary)

            if not seeded_events and not processed:
                idle_cycles += 1
            else:
                idle_cycles = 0

            if idle_cycles >= self.config.idle_cycles_to_stop:
                break

        final_missions = self._mission_handlers["list_missions"]({})
        return {
            "cycles": cycles,
            "final_missions": final_missions["missions"],
        }


DEFAULT_SELF_EVOLUTION_MISSION_TITLE = "Self Evolution MVP"
DEFAULT_SELF_EVOLUTION_MISSION_DESCRIPTION = (
    "Improve maintainability in the mission runtime code by reducing duplication, "
    "keeping behavior stable, and validating with tests."
)
