from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lord_of_the_machines.agent_tools import MissionRegistryTool
from lord_of_the_machines.mission.runtime import MissionRuntime
from lord_of_the_machines.runtime.paths import CONFIG_DIR


MISSIONS_FILE_ENV_VAR = "LORD_OF_THE_MACHINES_MISSIONS_FILE"
DEFAULT_MISSIONS_FILE_PATH = CONFIG_DIR / "missions.json"


@dataclass(slots=True)
class MissionSeed:
    title: str
    description: str
    mission_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> MissionSeed:
        if not isinstance(value, dict):
            raise ValueError("Each mission seed must be a JSON object.")
        title = value.get("title")
        description = value.get("description")
        mission_id = value.get("mission_id")
        metadata = value.get("metadata") or {}
        if not isinstance(title, str) or not title.strip():
            raise ValueError("Mission seed requires a non-empty string title.")
        if not isinstance(description, str) or not description.strip():
            raise ValueError("Mission seed requires a non-empty string description.")
        if mission_id is not None and not isinstance(mission_id, str):
            raise ValueError("mission_id must be a string when provided.")
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be a JSON object when provided.")
        return cls(
            title=title.strip(),
            description=description.strip(),
            mission_id=mission_id.strip() if isinstance(mission_id, str) and mission_id.strip() else None,
            metadata=dict(metadata),
        )


@dataclass(slots=True)
class MissionRunnerConfig:
    max_cycles: int = 25
    max_events_per_cycle: int = 20
    idle_cycles_to_stop: int = 2
    seed_each_cycle: bool = True
    bootstrap_missions_from_file: bool = True
    missions_file_path: str | Path | None = None
    skip_existing_missions_on_bootstrap: bool = True


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

    def create_missions_from_file(
        self,
        mission_file_path: str | Path | None = None,
        *,
        skip_existing: bool = True,
    ) -> dict[str, Any]:
        source_path = self._resolve_missions_file_path(mission_file_path)
        seeds = self._load_mission_seeds(source_path)
        created: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for seed in seeds:
            if skip_existing and seed.mission_id and self._mission_exists(seed.mission_id):
                skipped.append(
                    {
                        "mission_id": seed.mission_id,
                        "reason": "already_exists",
                    }
                )
                continue
            created.append(
                self.create_mission(
                    mission_id=seed.mission_id,
                    title=seed.title,
                    description=seed.description,
                    metadata=seed.metadata,
                )
            )
        return {
            "source_path": str(source_path),
            "loaded": len(seeds),
            "created": created,
            "skipped": skipped,
        }

    def run(self) -> dict[str, Any]:
        bootstrap: dict[str, Any] | None = None
        if self.config.bootstrap_missions_from_file:
            bootstrap = self.create_missions_from_file(
                self.config.missions_file_path,
                skip_existing=self.config.skip_existing_missions_on_bootstrap,
            )

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
            "bootstrap": bootstrap,
            "cycles": cycles,
            "final_missions": final_missions["missions"],
        }

    def _resolve_missions_file_path(self, mission_file_path: str | Path | None) -> Path:
        if mission_file_path is not None:
            return Path(mission_file_path).resolve()
        if self.config.missions_file_path is not None:
            return Path(self.config.missions_file_path).resolve()
        if os.getenv(MISSIONS_FILE_ENV_VAR):
            return Path(str(os.getenv(MISSIONS_FILE_ENV_VAR))).resolve()
        return DEFAULT_MISSIONS_FILE_PATH.resolve()

    def _load_mission_seeds(self, source_path: Path) -> list[MissionSeed]:
        if not source_path.exists():
            raise FileNotFoundError(f"Missions file does not exist: {source_path}")
        raw = json.loads(source_path.read_text(encoding="utf-8"))
        payload: list[Any]
        if isinstance(raw, list):
            payload = raw
        elif isinstance(raw, dict):
            missions = raw.get("missions")
            if not isinstance(missions, list):
                raise ValueError("Missions file must contain a top-level list or an object with a 'missions' list.")
            payload = missions
        else:
            raise ValueError("Missions file must be a JSON list or object.")
        return [MissionSeed.from_mapping(item) for item in payload]

    def _mission_exists(self, mission_id: str) -> bool:
        try:
            self._mission_handlers["get_mission"]({"mission_id": mission_id})
            return True
        except FileNotFoundError:
            return False
