from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lord_of_the_machines.agent_tools.mission_registry.config import MissionRegistryToolConfig
from lord_of_the_machines.agent_tools.mission_registry.contracts import (
    AssignMissionRoleRequest,
    CreateMissionRequest,
    GetMissionRequest,
    ListMissionsRequest,
    MissionRecord,
    UnassignMissionRoleRequest,
    UpdateMissionPhaseRequest,
    UpdateMissionStatusRequest,
)
from lord_of_the_machines.agent_tools.mission_registry.definition import build_definition
from lord_of_the_machines.llm.base_agent import BaseAgent
from lord_of_the_machines.llm.tool_definitions import ToolDefinition
from lord_of_the_machines.llm.tools import ToolHandler


SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


class MissionRegistryTool:
    TOOL_NAME = "mission_registry"

    def __init__(self, root_path: str | Path, *, config: MissionRegistryToolConfig | None = None) -> None:
        self.config = config or MissionRegistryToolConfig(root_path=Path(root_path))

    def install(self, agent: BaseAgent) -> None:
        agent.add_tool(self.definition(), handlers=self.handlers())

    def definition(self) -> ToolDefinition:
        return build_definition(self.TOOL_NAME)

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "create_mission": self._create_mission,
            "list_missions": self._list_missions,
            "get_mission": self._get_mission,
            "update_mission_status": self._update_mission_status,
            "update_mission_phase": self._update_mission_phase,
            "assign_mission_role": self._assign_mission_role,
            "unassign_mission_role": self._unassign_mission_role,
        }

    def _create_mission(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = CreateMissionRequest.from_mapping(arguments)
        mission_id = self._safe_id(request.mission_id or self._generate_mission_id(request.title), field_name="mission_id")
        initial_status = self._validated_status(request.initial_status)
        mission_path = self._mission_path(mission_id)
        if mission_path.exists():
            raise FileExistsError(f"Mission already exists: {mission_id}")

        now = self._utc_now()
        mission = MissionRecord(
            mission_id=mission_id,
            title=request.title,
            description=request.description,
            status=initial_status,
            created_at=now,
            updated_at=now,
            metadata=dict(request.metadata),
        )
        self._save_mission(mission)
        return {"created": True, "mission": mission.to_mapping()}

    def _list_missions(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = ListMissionsRequest.from_mapping(arguments)
        status_filter = {self._validated_status(status) for status in request.statuses} if request.statuses else None
        missions = []
        for mission in self._iter_missions():
            if status_filter is not None and mission.status not in status_filter:
                continue
            missions.append(mission.to_mapping())
            if request.limit is not None and len(missions) >= request.limit:
                break
        return {"missions": missions}

    def _get_mission(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = GetMissionRequest.from_mapping(arguments)
        mission = self._load_mission(request.mission_id)
        return {"mission": mission.to_mapping()}

    def _update_mission_status(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = UpdateMissionStatusRequest.from_mapping(arguments)
        mission = self._load_mission(request.mission_id)
        mission.status = self._validated_status(request.status)
        mission.updated_at = self._utc_now()
        if request.reason:
            mission.metadata["last_status_reason"] = request.reason
        self._save_mission(mission)
        return {"mission": mission.to_mapping()}

    def _update_mission_phase(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = UpdateMissionPhaseRequest.from_mapping(arguments)
        mission = self._load_mission(request.mission_id)
        mission.phase_status[request.phase] = request.status
        if request.notes:
            mission.phase_notes[request.phase] = request.notes
        mission.updated_at = self._utc_now()
        self._save_mission(mission)
        return {"mission": mission.to_mapping()}

    def _assign_mission_role(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = AssignMissionRoleRequest.from_mapping(arguments)
        mission = self._load_mission(request.mission_id)
        assigned = mission.role_assignments.setdefault(request.role, [])
        if request.agent_id not in assigned:
            assigned.append(request.agent_id)
        mission.updated_at = self._utc_now()
        self._save_mission(mission)
        return {"mission": mission.to_mapping()}

    def _unassign_mission_role(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = UnassignMissionRoleRequest.from_mapping(arguments)
        mission = self._load_mission(request.mission_id)
        assigned = mission.role_assignments.get(request.role) or []
        mission.role_assignments[request.role] = [agent_id for agent_id in assigned if agent_id != request.agent_id]
        mission.updated_at = self._utc_now()
        self._save_mission(mission)
        return {"mission": mission.to_mapping()}

    def _iter_missions(self) -> list[MissionRecord]:
        missions = []
        for mission_path in sorted(self.config.root_path.glob("*.json"), key=lambda path: path.name.lower()):
            missions.append(self._load_mission(mission_path.stem))
        return missions

    def _load_mission(self, mission_id: str) -> MissionRecord:
        safe_id = self._safe_id(mission_id, field_name="mission_id")
        path = self._mission_path(safe_id)
        if not path.exists():
            raise FileNotFoundError(f"Mission does not exist: {safe_id}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        return MissionRecord.from_mapping(raw)

    def _save_mission(self, mission: MissionRecord) -> None:
        path = self._mission_path(mission.mission_id)
        path.write_text(json.dumps(mission.to_mapping(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _mission_path(self, mission_id: str) -> Path:
        path = (self.config.root_path / f"{mission_id}.json").resolve()
        if not self._is_within_root(path):
            raise ValueError("Mission path is outside configured mission root.")
        return path

    def _is_within_root(self, path: Path) -> bool:
        try:
            path.relative_to(self.config.root_path)
            return True
        except ValueError:
            return False

    def _validated_status(self, status: str) -> str:
        normalized = status.strip().lower()
        if normalized not in self.config.allowed_statuses:
            allowed = ", ".join(self.config.allowed_statuses)
            raise ValueError(f"Invalid mission status '{status}'. Allowed statuses: {allowed}.")
        return normalized

    def _safe_id(self, value: str, *, field_name: str) -> str:
        if not SAFE_ID_RE.fullmatch(value):
            raise ValueError(
                f"{field_name} must match {SAFE_ID_RE.pattern} "
                "(letters, numbers, underscore, hyphen; max 64 chars)."
            )
        return value

    def _generate_mission_id(self, title: str) -> str:
        base = re.sub(r"[^a-zA-Z0-9]+", "_", title.strip().lower()).strip("_") or "mission"
        base = base[:40]
        return f"{base}_{datetime.now(tz=timezone.utc).strftime('%Y%m%d%H%M%S')}"

    def _utc_now(self) -> str:
        return datetime.now(tz=timezone.utc).isoformat()

