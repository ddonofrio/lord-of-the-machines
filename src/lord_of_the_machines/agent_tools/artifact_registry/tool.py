from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lord_of_the_machines.agent_tools.artifact_registry.config import ArtifactRegistryToolConfig
from lord_of_the_machines.agent_tools.artifact_registry.contracts import (
    ArtifactRecord,
    GetArtifactRequest,
    ListArtifactsRequest,
    PublishArtifactRequest,
    UpdateArtifactRequest,
)
from lord_of_the_machines.agent_tools.artifact_registry.definition import build_definition
from lord_of_the_machines.llm.base_agent import BaseAgent
from lord_of_the_machines.llm.tool_definitions import ToolDefinition
from lord_of_the_machines.llm.tools import ToolHandler


SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


class ArtifactRegistryTool:
    TOOL_NAME = "artifact_registry"

    def __init__(self, root_path: str | Path, *, config: ArtifactRegistryToolConfig | None = None) -> None:
        self.config = config or ArtifactRegistryToolConfig(root_path=Path(root_path))

    def install(self, agent: BaseAgent) -> None:
        agent.add_tool(self.definition(), handlers=self.handlers())

    def definition(self) -> ToolDefinition:
        return build_definition(self.TOOL_NAME)

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "publish_artifact": self._publish_artifact,
            "list_artifacts": self._list_artifacts,
            "get_artifact": self._get_artifact,
            "update_artifact": self._update_artifact,
        }

    def _publish_artifact(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = PublishArtifactRequest.from_mapping(arguments)
        mission_id = self._safe_id(request.mission_id, field_name="mission_id")
        phase = self._safe_id(request.phase, field_name="phase")
        artifact_type = self._safe_id(request.artifact_type, field_name="artifact_type")
        status = self._validated_status(request.status)
        producer_role = self._safe_id(request.producer_role, field_name="producer_role") if request.producer_role else None

        now = self._utc_now()
        artifact_id = self._new_artifact_id(mission_id, phase, artifact_type)
        artifact = ArtifactRecord(
            artifact_id=artifact_id,
            mission_id=mission_id,
            phase=phase,
            artifact_type=artifact_type,
            title=request.title,
            status=status,
            version=1,
            format=request.format,
            content=request.content,
            producer_role=producer_role,
            created_at=now,
            updated_at=now,
            tags=request.tags,
            metadata=dict(request.metadata),
        )
        self._save_artifact(artifact)
        return {"artifact": artifact.to_mapping()}

    def _list_artifacts(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = ListArtifactsRequest.from_mapping(arguments)
        mission_id = self._safe_id(request.mission_id, field_name="mission_id") if request.mission_id else None
        phase = self._safe_id(request.phase, field_name="phase") if request.phase else None
        artifact_type = self._safe_id(request.artifact_type, field_name="artifact_type") if request.artifact_type else None
        statuses = {self._validated_status(status) for status in request.statuses} if request.statuses else None
        tags = set(request.tags) if request.tags else None

        artifacts = []
        for artifact in self._iter_artifacts():
            if mission_id is not None and artifact.mission_id != mission_id:
                continue
            if phase is not None and artifact.phase != phase:
                continue
            if artifact_type is not None and artifact.artifact_type != artifact_type:
                continue
            if statuses is not None and artifact.status not in statuses:
                continue
            if tags is not None and not tags.issubset(set(artifact.tags)):
                continue
            artifacts.append(artifact.to_mapping())
        return {"artifacts": artifacts}

    def _get_artifact(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = GetArtifactRequest.from_mapping(arguments)
        artifact = self._load_artifact(request.artifact_id)
        return {"artifact": artifact.to_mapping()}

    def _update_artifact(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = UpdateArtifactRequest.from_mapping(arguments)
        current = self._load_artifact(request.artifact_id)

        now = self._utc_now()
        updated = ArtifactRecord(
            artifact_id=current.artifact_id,
            mission_id=current.mission_id,
            phase=current.phase,
            artifact_type=current.artifact_type,
            title=request.title if request.title is not None else current.title,
            status=self._validated_status(request.status) if request.status is not None else current.status,
            version=current.version + 1,
            format=current.format,
            content=request.content if request.content is not None else current.content,
            producer_role=current.producer_role,
            created_at=current.created_at,
            updated_at=now,
            tags=request.tags if request.has_tags else current.tags,
            metadata=request.metadata if request.has_metadata else current.metadata,
        )
        self._save_artifact(updated)
        return {"artifact": updated.to_mapping()}

    def _iter_artifacts(self) -> list[ArtifactRecord]:
        artifacts = []
        for path in sorted(self.config.root_path.rglob("*.json"), key=lambda item: item.name.lower()):
            raw = json.loads(path.read_text(encoding="utf-8"))
            artifacts.append(ArtifactRecord.from_mapping(raw))
        return artifacts

    def _load_artifact(self, artifact_id: str) -> ArtifactRecord:
        safe_id = self._safe_id(artifact_id, field_name="artifact_id")
        path = self._artifact_path_from_id(safe_id)
        if path is None:
            raise FileNotFoundError(f"Artifact not found: {safe_id}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        return ArtifactRecord.from_mapping(raw)

    def _save_artifact(self, artifact: ArtifactRecord) -> None:
        path = self._artifact_path(artifact.mission_id, artifact.artifact_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(artifact.to_mapping(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _artifact_path(self, mission_id: str, artifact_id: str) -> Path:
        path = (self.config.root_path / mission_id / f"{artifact_id}.json").resolve()
        if not self._is_within_root(path):
            raise ValueError("Artifact path is outside configured artifact root.")
        return path

    def _artifact_path_from_id(self, artifact_id: str) -> Path | None:
        for path in self.config.root_path.rglob(f"{artifact_id}.json"):
            resolved = path.resolve()
            if self._is_within_root(resolved):
                return resolved
        return None

    def _new_artifact_id(self, mission_id: str, phase: str, artifact_type: str) -> str:
        prefix = f"{mission_id}_{phase}_{artifact_type}"
        safe_prefix = re.sub(r"[^a-zA-Z0-9_-]+", "_", prefix).strip("_")[:40] or "artifact"
        return f"{safe_prefix}_{datetime.now(tz=timezone.utc).strftime('%Y%m%d%H%M%S%f')}"

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
            raise ValueError(f"Invalid artifact status '{status}'. Allowed statuses: {allowed}.")
        return normalized

    def _safe_id(self, value: str | None, *, field_name: str) -> str:
        if value is None:
            raise ValueError(f"{field_name} is required.")
        if not SAFE_ID_RE.fullmatch(value):
            raise ValueError(
                f"{field_name} must match {SAFE_ID_RE.pattern} "
                "(letters, numbers, underscore, hyphen; max 64 chars)."
            )
        return value

    def _utc_now(self) -> str:
        return datetime.now(tz=timezone.utc).isoformat()
