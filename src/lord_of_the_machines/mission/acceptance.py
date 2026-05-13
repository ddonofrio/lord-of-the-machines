from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class MissionAcceptanceChecks:
    documentation_file: str | None = None
    required_role_mentions: tuple[str, ...] = ()
    required_files: tuple[str, ...] = ()
    required_file_contains: dict[str, tuple[str, ...]] | None = None
    follow_up_mission_file: str | None = None
    minimum_missions_in_follow_up_file: int = 0
    require_distinct_follow_up_mission: bool = False

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any] | None) -> "MissionAcceptanceChecks | None":
        if not isinstance(metadata, dict):
            return None
        raw = metadata.get("acceptance_checks")
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise ValueError("metadata.acceptance_checks must be an object when provided.")

        documentation_file = _optional_string(raw, "documentation_file")
        follow_up_mission_file = _optional_string(raw, "follow_up_mission_file")
        required_role_mentions = tuple(_optional_string_list(raw, "required_role_mentions"))
        required_files = tuple(_optional_string_list(raw, "required_files"))
        required_file_contains = _optional_required_file_contains(raw, "required_file_contains")
        minimum_missions = raw.get("minimum_missions_in_follow_up_file")
        if minimum_missions is None:
            minimum_missions_int = 0
        elif isinstance(minimum_missions, int) and not isinstance(minimum_missions, bool) and minimum_missions >= 0:
            minimum_missions_int = minimum_missions
        else:
            raise ValueError("minimum_missions_in_follow_up_file must be an integer >= 0.")

        require_distinct = raw.get("require_distinct_follow_up_mission")
        if require_distinct is None:
            require_distinct_bool = False
        elif isinstance(require_distinct, bool):
            require_distinct_bool = require_distinct
        else:
            raise ValueError("require_distinct_follow_up_mission must be a boolean when provided.")

        checks = cls(
            documentation_file=documentation_file,
            required_role_mentions=required_role_mentions,
            required_files=required_files,
            required_file_contains=required_file_contains,
            follow_up_mission_file=follow_up_mission_file,
            minimum_missions_in_follow_up_file=minimum_missions_int,
            require_distinct_follow_up_mission=require_distinct_bool,
        )
        if not any(
            [
                checks.documentation_file,
                checks.required_role_mentions,
                checks.required_files,
                checks.required_file_contains,
                checks.follow_up_mission_file,
                checks.minimum_missions_in_follow_up_file > 0,
                checks.require_distinct_follow_up_mission,
            ]
        ):
            return None
        return checks


def evaluate_mission_acceptance_checks(
    *,
    checks: MissionAcceptanceChecks,
    workspace_root: Path,
    mission_id: str | None,
) -> list[str]:
    errors: list[str] = []
    documentation_text = ""

    if checks.documentation_file:
        documentation_path = _safe_workspace_path(workspace_root, checks.documentation_file)
        if not documentation_path.exists():
            errors.append(f"required documentation file does not exist: {checks.documentation_file}")
        else:
            documentation_text = documentation_path.read_text(encoding="utf-8")
            if not documentation_text.strip():
                errors.append(f"required documentation file is empty: {checks.documentation_file}")

    if checks.required_role_mentions:
        if not checks.documentation_file:
            errors.append("required_role_mentions requires acceptance_checks.documentation_file.")
        elif documentation_text:
            normalized = documentation_text.lower()
            missing_roles = []
            for role in checks.required_role_mentions:
                role_key = role.lower()
                role_alt = role_key.replace("_", " ")
                if role_key not in normalized and role_alt not in normalized:
                    missing_roles.append(role)
            if missing_roles:
                errors.append(
                    "documentation is missing required role mentions: " + ", ".join(sorted(missing_roles))
                )

    if checks.required_files:
        for relative_path in checks.required_files:
            required_path = _safe_workspace_path(workspace_root, relative_path)
            if not required_path.exists():
                errors.append(f"required file does not exist: {relative_path}")

    if checks.required_file_contains:
        for relative_path, required_snippets in checks.required_file_contains.items():
            required_path = _safe_workspace_path(workspace_root, relative_path)
            if not required_path.exists():
                errors.append(f"required file for content check does not exist: {relative_path}")
                continue
            text = required_path.read_text(encoding="utf-8")
            missing_snippets = [snippet for snippet in required_snippets if snippet not in text]
            if missing_snippets:
                errors.append(
                    f"required content missing in {relative_path}: "
                    + ", ".join(repr(item) for item in missing_snippets)
                )

    if checks.follow_up_mission_file:
        mission_file_path = _safe_workspace_path(workspace_root, checks.follow_up_mission_file)
        if not mission_file_path.exists():
            errors.append(f"follow-up mission file does not exist: {checks.follow_up_mission_file}")
        else:
            try:
                missions = _load_missions_from_file(mission_file_path)
            except ValueError as exc:
                errors.append(str(exc))
                missions = []
            if checks.minimum_missions_in_follow_up_file > 0 and len(missions) < checks.minimum_missions_in_follow_up_file:
                errors.append(
                    "follow-up mission file has too few missions: "
                    f"expected at least {checks.minimum_missions_in_follow_up_file}, found {len(missions)}."
                )
            if checks.require_distinct_follow_up_mission:
                has_distinct = any(
                    isinstance(item.get("mission_id"), str)
                    and item.get("mission_id")
                    and item.get("mission_id") != mission_id
                    for item in missions
                )
                if not has_distinct:
                    errors.append("no distinct follow-up mission found in the follow-up mission file.")

    return errors


def _load_missions_from_file(path: Path) -> list[dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"follow-up mission file is not valid JSON: {path}") from exc
    payload: list[Any]
    if isinstance(raw, list):
        payload = raw
    elif isinstance(raw, dict):
        missions = raw.get("missions")
        if not isinstance(missions, list):
            raise ValueError("follow-up mission file must contain a 'missions' list.")
        payload = missions
    else:
        raise ValueError("follow-up mission file must be a JSON list or object.")

    items: list[dict[str, Any]] = []
    for item in payload:
        if isinstance(item, dict):
            items.append(item)
    return items


def _safe_workspace_path(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:  # pragma: no cover - defensive guard
        raise ValueError(f"acceptance check path escapes workspace: {relative_path}") from exc
    return candidate


def _optional_string(values: dict[str, Any], field_name: str) -> str | None:
    value = values.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string when provided.")
    return value


def _optional_string_list(values: dict[str, Any], field_name: str) -> list[str]:
    value = values.get(field_name)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{field_name} must be a list of non-empty strings.")
    return list(value)


def _optional_required_file_contains(
    values: dict[str, Any],
    field_name: str,
) -> dict[str, tuple[str, ...]] | None:
    value = values.get(field_name)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object mapping file path to required snippets.")
    result: dict[str, tuple[str, ...]] = {}
    for raw_path, raw_snippets in value.items():
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise ValueError(f"{field_name} keys must be non-empty strings.")
        if not isinstance(raw_snippets, list) or not raw_snippets:
            raise ValueError(f"{field_name}[{raw_path!r}] must be a non-empty list of strings.")
        snippets: list[str] = []
        for raw_snippet in raw_snippets:
            if not isinstance(raw_snippet, str) or not raw_snippet:
                raise ValueError(f"{field_name}[{raw_path!r}] entries must be non-empty strings.")
            snippets.append(raw_snippet)
        result[raw_path] = tuple(snippets)
    return result
