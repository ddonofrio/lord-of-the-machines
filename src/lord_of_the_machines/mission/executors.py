from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

from lord_of_the_machines.agent_tools import (
    SoftwareDevelopmentEnvironmentExecutionPolicy,
    SoftwareDevelopmentEnvironmentPermissionPolicy,
    SoftwareDevelopmentEnvironmentTool,
    SoftwareDevelopmentEnvironmentToolConfig,
)
from lord_of_the_machines.llm import BaseAgent
from lord_of_the_machines.mission.acceptance import (
    MissionAcceptanceChecks,
    evaluate_mission_acceptance_checks,
)
from lord_of_the_machines.mission.agent_as_tool import AgentAsToolBridge, AgentAsToolConfig
from lord_of_the_machines.mission.contracts import RoleTaskRequest, RoleTaskResult
from lord_of_the_machines.mission.events import STATUS_BLOCKED, STATUS_COMPLETED, STATUS_NEEDS_FOLLOW_UP
from lord_of_the_machines.runtime import log_timeline

IMPLEMENTATION_TASKS_CODE_BLOCK_RE = re.compile(
    r"```(?:json)?\s*(\[[\s\S]*?\])\s*```",
    re.IGNORECASE,
)


@dataclass(slots=True)
class BaseAgentRoleExecutorConfig:
    role_name: str
    tool_name: str | None = None
    method_name: str = "run_task"


class BaseAgentRoleExecutor:
    def __init__(self, agent: BaseAgent, *, config: BaseAgentRoleExecutorConfig) -> None:
        self._agent = agent
        self._config = config
        tool_name = config.tool_name or f"{config.role_name}_agent"
        bridge_config = AgentAsToolConfig(
            role_name=config.role_name,
            tool_name=tool_name,
            method_name=config.method_name,
        )
        self._bridge = AgentAsToolBridge(agent, config=bridge_config)

    def execute_task(self, request: RoleTaskRequest) -> RoleTaskResult:
        log_timeline(
            actor=self._config.role_name,
            action="started task",
            mission_id=request.mission_id,
            phase=request.phase,
            details=task_start_details(request),
        )
        result = self._bridge.execute_task(request)
        result.metadata = dict(result.metadata)
        usage = self._agent.last_query_usage
        cost = self._agent.last_query_cost
        if usage:
            result.metadata["agent_usage"] = dict(usage)
        if cost:
            result.metadata["agent_cost"] = dict(cost)
        log_timeline(
            actor=self._config.role_name,
            action=f"finished task ({result.status})",
            mission_id=request.mission_id,
            phase=request.phase,
            details={"summary": result.summary},
            usage=usage,
            cost=cost,
        )
        return result


def task_start_details(request: RoleTaskRequest) -> dict[str, Any]:
    details: dict[str, Any] = {
        "objective": request.objective,
        "constraints_count": len(request.constraints),
    }
    context = request.context if isinstance(request.context, dict) else {}
    previous_phase = context.get("previous_phase")
    if previous_phase:
        details["previous_phase"] = previous_phase
    previous_summary = context.get("previous_phase_summary")
    if previous_summary:
        details["previous_phase_summary"] = previous_summary
    previous_artifact = context.get("previous_artifact")
    if isinstance(previous_artifact, dict):
        artifact_details = {
            "artifact_id": previous_artifact.get("artifact_id"),
            "artifact_type": previous_artifact.get("artifact_type"),
            "title": previous_artifact.get("title"),
            "producer_role": previous_artifact.get("producer_role"),
            "content_chars": len(str(previous_artifact.get("content") or "")),
        }
        details["previous_artifact"] = {
            key: value
            for key, value in artifact_details.items()
            if value not in {None, ""}
        }
    return details


def install_read_only_software_workspace_tool(
    agent: BaseAgent,
    *,
    workspace_root: Path,
) -> SoftwareDevelopmentEnvironmentTool:
    tool = SoftwareDevelopmentEnvironmentTool(
        workspace_root,
        config=SoftwareDevelopmentEnvironmentToolConfig(
            root_path=workspace_root,
            read_char_limit=3_000,
            default_search_max_results=80,
            default_tree_max_entries=250,
            permission_policy=SoftwareDevelopmentEnvironmentPermissionPolicy.read_only(),
            execution_policy=SoftwareDevelopmentEnvironmentExecutionPolicy(
                require_confirmation_for_destructive_operations=True,
                require_dry_run_for_move=True,
                require_dry_run_for_delete=True,
                max_destructive_entries=10,
                max_command_timeout_seconds=30,
            ),
        ),
    )
    tool.install(agent)
    return tool


@dataclass(slots=True)
class SoftwareDeveloperRoleExecutorConfig:
    workspace_root: Path
    role_name: str = "software_developer"
    diagnostics_profiles: tuple[str, ...] = ("unittest",)
    diagnostics_timeout_seconds: int = 180
    allowed_write_prefixes: tuple[str, ...] = (
        "src/lord_of_the_machines/mission/",
        "tests/",
    )
    require_changed_files: bool = False


@dataclass(slots=True)
class SoftwareDevelopmentManagerRoleExecutorConfig:
    role_name: str = "software_development_manager"
    implementation_task_metadata_key: str = "implementation_tasks"
    minimum_implementation_tasks: int = 1


class SoftwareDevelopmentManagerRoleExecutor:
    def __init__(
        self,
        agent: BaseAgent,
        *,
        config: SoftwareDevelopmentManagerRoleExecutorConfig | None = None,
    ) -> None:
        self.config = config or SoftwareDevelopmentManagerRoleExecutorConfig()
        self._base = BaseAgentRoleExecutor(
            agent,
            config=BaseAgentRoleExecutorConfig(
                role_name=self.config.role_name,
                tool_name=f"{self.config.role_name}_agent",
            ),
        )

    def execute_task(self, request: RoleTaskRequest) -> RoleTaskResult:
        result = self._base.execute_task(request)
        if request.phase != "development_plan":
            return result
        if result.status != STATUS_COMPLETED:
            return result

        metadata = dict(result.metadata) if isinstance(result.metadata, dict) else {}
        raw_tasks = metadata.get(self.config.implementation_task_metadata_key)
        normalized_tasks = self._normalize_tasks(raw_tasks)
        if not normalized_tasks:
            normalized_tasks = self._extract_tasks_from_artifact_content(result.artifact_content or "")

        if len(normalized_tasks) < self.config.minimum_implementation_tasks:
            return RoleTaskResult(
                status=STATUS_NEEDS_FOLLOW_UP,
                summary=(
                    "Development plan is missing structured implementation task metadata. "
                    "Provide metadata.implementation_tasks so runtime can schedule ticket-driven implementation."
                ),
                required_changes=[
                    "Return metadata.implementation_tasks as a non-empty list of structured tasks.",
                    "Each task must include key, title, description, priority, task_type, and depends_on.",
                ],
                follow_ups=[
                    "Regenerate the development plan with explicit structured metadata for the implementation queue."
                ],
                metadata={"original_result": result.to_mapping()},
            )

        metadata[self.config.implementation_task_metadata_key] = normalized_tasks
        result.metadata = metadata
        return result

    def _extract_tasks_from_artifact_content(self, content: str) -> list[dict[str, Any]]:
        if not content.strip():
            return []
        for match in IMPLEMENTATION_TASKS_CODE_BLOCK_RE.finditer(content):
            block = match.group(1).strip()
            try:
                parsed = json.loads(block)
            except json.JSONDecodeError:
                continue
            normalized = self._normalize_tasks(parsed)
            if normalized:
                return normalized
        return []

    def _normalize_tasks(self, raw_tasks: Any) -> list[dict[str, Any]]:
        if not isinstance(raw_tasks, list):
            return []
        normalized: list[dict[str, Any]] = []
        for index, raw_item in enumerate(raw_tasks):
            if not isinstance(raw_item, dict):
                continue
            title = str(raw_item.get("title") or "").strip()
            if not title:
                continue
            key = str(raw_item.get("key") or raw_item.get("task_key") or f"TASK-{index + 1}").strip()
            description = str(raw_item.get("description") or raw_item.get("details") or title).strip()
            priority = str(raw_item.get("priority") or "P2").strip().upper()
            if priority not in {"P0", "P1", "P2", "P3"}:
                priority = "P2"
            task_type = str(raw_item.get("task_type") or "implementation").strip().lower()
            if task_type not in {"implementation", "research", "qa", "ops", "documentation"}:
                task_type = "implementation"
            raw_depends_on = raw_item.get("depends_on")
            depends_on: list[str] = []
            if isinstance(raw_depends_on, list):
                depends_on = [str(item).strip() for item in raw_depends_on if str(item).strip()]
            normalized.append(
                {
                    "key": key,
                    "title": title,
                    "description": description,
                    "priority": priority,
                    "task_type": task_type,
                    "depends_on": depends_on,
                }
            )
        return normalized


class SoftwareDeveloperRoleExecutor:
    def __init__(
        self,
        agent: BaseAgent,
        *,
        config: SoftwareDeveloperRoleExecutorConfig,
        tool_config: SoftwareDevelopmentEnvironmentToolConfig | None = None,
    ) -> None:
        self.config = config
        policy = SoftwareDevelopmentEnvironmentPermissionPolicy(
            allow_read_operations=True,
            allow_write_operations=True,
            allow_move_operations=False,
            allow_delete_operations=False,
            allow_command_execution=True,
            allow_diagnostics=True,
            allow_git_inspection=True,
            allow_protected_path_writes=False,
        )
        execution_policy = SoftwareDevelopmentEnvironmentExecutionPolicy(
            require_confirmation_for_destructive_operations=True,
            require_dry_run_for_move=True,
            require_dry_run_for_delete=True,
            max_destructive_entries=10,
            max_command_timeout_seconds=max(30, int(config.diagnostics_timeout_seconds)),
        )
        resolved_tool_config = tool_config or SoftwareDevelopmentEnvironmentToolConfig(
            root_path=config.workspace_root,
            permission_policy=policy,
            execution_policy=execution_policy,
        )
        self._tool = SoftwareDevelopmentEnvironmentTool(config.workspace_root, config=resolved_tool_config)
        self._tool.install(agent)
        self._tool_handlers = self._tool.handlers()
        self._base = BaseAgentRoleExecutor(
            agent,
            config=BaseAgentRoleExecutorConfig(
                role_name=config.role_name,
                tool_name=f"{config.role_name}_agent",
            ),
        )

    def execute_task(self, request: RoleTaskRequest) -> RoleTaskResult:
        constrained_request = RoleTaskRequest(
            objective=request.objective,
            mission_id=request.mission_id,
            phase=request.phase,
            task_id=request.task_id,
            context=dict(request.context),
            constraints=[
                *request.constraints,
                f"Allowed write prefixes: {', '.join(self.config.allowed_write_prefixes)}",
                f"Required diagnostics profiles after edits: {', '.join(self.config.diagnostics_profiles)}",
                "Use the safest edit method possible: prefer replace_text/replace_lines/insert_text on existing files.",
                "Do not overwrite entire existing files unless intentionally rewriting all content.",
                "If you must do a large rewrite, set allow_large_rewrite=true explicitly and explain why in the summary.",
                "If a suggested target file does not exist, create it in an allowed write prefix or adapt the nearest existing module.",
                "Do not report blocked due missing files unless list_tree over allowed prefixes proves there are zero writable project files.",
                (
                    f"Current board task id: {request.task_id}. Complete this task scope first and report clear evidence."
                    if request.task_id
                    else "If board_task context exists, treat it as the primary scope source for this run."
                ),
            ],
            max_rounds=request.max_rounds,
            continue_previous=request.continue_previous,
            metadata=dict(request.metadata),
        )
        result = self._base.execute_task(constrained_request)
        corrected_result = self._correct_false_workspace_block(result)
        if corrected_result is not None:
            return corrected_result
        if result.status != STATUS_COMPLETED:
            return result

        changes = self._tool_handlers["list_changes"]({})
        changed_paths = list(changes.get("changed_paths") or [])
        if self.config.require_changed_files and not changed_paths:
            return RoleTaskResult(
                status=STATUS_NEEDS_FOLLOW_UP,
                summary="No files were changed during implementation.",
                follow_ups=["Apply at least one scoped code change and retry."],
                metadata={"changes": changes},
            )

        invalid_paths = [path for path in changed_paths if not self._is_allowed_path(path)]
        if invalid_paths:
            return RoleTaskResult(
                status=STATUS_BLOCKED,
                summary=(
                    "Implementation changed files outside allowed prefixes: "
                    + ", ".join(invalid_paths)
                ),
                follow_ups=["Restrict edits to allowed prefixes and retry."],
                metadata={"changes": changes, "invalid_paths": invalid_paths},
            )

        diagnostics = self._tool_handlers["run_diagnostics"](
            {
                "profiles": list(self.config.diagnostics_profiles),
                "timeout_seconds": self.config.diagnostics_timeout_seconds,
                "workdir": ".",
            }
        )
        failed_profiles = [
            profile
            for profile in list(diagnostics.get("results") or [])
            if profile.get("ok") is False
        ]
        if failed_profiles:
            return RoleTaskResult(
                status=STATUS_NEEDS_FOLLOW_UP,
                summary=(
                    "Implementation diagnostics failed: "
                    + ", ".join(str(profile.get("profile")) for profile in failed_profiles)
                ),
                required_changes=["Fix failing diagnostics before marking implementation completed."],
                follow_ups=[
                    f"Resolve diagnostic failure in profile '{profile.get('profile')}'."
                    for profile in failed_profiles
                ],
                metadata={"changes": changes, "diagnostics": diagnostics},
            )

        acceptance_metadata = request.context.get("metadata") if isinstance(request.context, dict) else None
        try:
            acceptance_checks = MissionAcceptanceChecks.from_metadata(acceptance_metadata)
        except ValueError as exc:
            return RoleTaskResult(
                status=STATUS_BLOCKED,
                summary=f"Invalid mission acceptance configuration: {exc}",
                follow_ups=["Fix mission metadata.acceptance_checks and rerun."],
                metadata={"changes": changes, "diagnostics": diagnostics},
            )
        if acceptance_checks is not None:
            acceptance_errors = evaluate_mission_acceptance_checks(
                checks=acceptance_checks,
                workspace_root=self.config.workspace_root,
                mission_id=request.mission_id,
            )
            if acceptance_errors:
                return RoleTaskResult(
                    status=STATUS_NEEDS_FOLLOW_UP,
                    summary="Mission acceptance checks are not satisfied yet.",
                    required_changes=list(acceptance_errors),
                    follow_ups=list(acceptance_errors),
                    metadata={"changes": changes, "diagnostics": diagnostics},
                )

        if not result.artifact_content:
            result.artifact_type = "implementation_report"
            result.artifact_title = result.artifact_title or "Implementation Report"
            result.artifact_format = "markdown"
            result.artifact_content = self._build_artifact_content(changed_paths, diagnostics)
        return result

    def _correct_false_workspace_block(self, result: RoleTaskResult) -> RoleTaskResult | None:
        if result.status not in {STATUS_BLOCKED, STATUS_NEEDS_FOLLOW_UP}:
            return None
        summary = (result.summary or "").lower()
        workspace_missing_signals = (
            "no writable source files",
            "required deliverables",
            "not found in the workspace",
            "ensure the project files exist",
            "source files are present and unlocked",
        )
        if not any(signal in summary for signal in workspace_missing_signals):
            return None
        existing_targets = self._existing_allowed_write_targets()
        if not existing_targets:
            return None
        return RoleTaskResult(
            status=STATUS_NEEDS_FOLLOW_UP,
            summary=(
                "Workspace is available and writable under allowed prefixes. "
                "Continue implementation: edit existing modules and create missing files when required."
            ),
            required_changes=[
                "Implement QA integration changes directly in available mission modules.",
                "Create missing deliverables (for example docs/qa-agent-integration.md) instead of blocking.",
                "Run required diagnostics and resubmit a structured completed result when done.",
            ],
            follow_ups=[
                "Use list_tree and find_files to choose concrete targets in allowed prefixes.",
                "Apply write_file/replace_text/replace_lines/insert_text and verify list_changes reports edits.",
            ],
            metadata={
                "corrected_false_workspace_block": True,
                "existing_allowed_targets": existing_targets,
                "original_result": result.to_mapping(),
            },
        )

    def _existing_allowed_write_targets(self) -> list[str]:
        targets: list[str] = []
        for prefix in self.config.allowed_write_prefixes:
            raw = prefix.strip()
            if not raw:
                continue
            candidate = (self.config.workspace_root / raw).resolve()
            if candidate.exists():
                targets.append(raw.replace("\\", "/"))
        return targets

    def _is_allowed_path(self, path: str) -> bool:
        normalized = path.replace("\\", "/")
        return any(normalized.startswith(prefix) for prefix in self.config.allowed_write_prefixes)

    def _build_artifact_content(self, changed_paths: list[str], diagnostics: dict[str, Any]) -> str:
        lines = [
            "# Implementation Report",
            "",
            "## Changed Paths",
        ]
        if changed_paths:
            lines.extend(f"- {path}" for path in changed_paths)
        else:
            lines.append("- None")
        lines.extend(["", "## Diagnostics"])
        results = list(diagnostics.get("results") or [])
        if not results:
            lines.append("- No diagnostics results.")
        else:
            for item in results:
                profile = str(item.get("profile") or "unknown")
                if item.get("ok") is True:
                    status = "passed"
                elif item.get("ok") is False:
                    status = "failed"
                else:
                    status = "skipped"
                lines.append(f"- {profile}: {status}")
        return "\n".join(lines)
