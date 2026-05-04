from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lord_of_the_machines.agent_tools import (
    SoftwareDevelopmentEnvironmentExecutionPolicy,
    SoftwareDevelopmentEnvironmentPermissionPolicy,
    SoftwareDevelopmentEnvironmentTool,
    SoftwareDevelopmentEnvironmentToolConfig,
)
from lord_of_the_machines.llm import BaseAgent
from lord_of_the_machines.mission.agent_as_tool import AgentAsToolBridge, AgentAsToolConfig
from lord_of_the_machines.mission.contracts import RoleTaskRequest, RoleTaskResult
from lord_of_the_machines.mission.events import STATUS_BLOCKED, STATUS_COMPLETED, STATUS_NEEDS_FOLLOW_UP


@dataclass(slots=True)
class BaseAgentRoleExecutorConfig:
    role_name: str
    tool_name: str | None = None
    method_name: str = "run_task"


class BaseAgentRoleExecutor:
    def __init__(self, agent: BaseAgent, *, config: BaseAgentRoleExecutorConfig) -> None:
        tool_name = config.tool_name or f"{config.role_name}_agent"
        bridge_config = AgentAsToolConfig(
            role_name=config.role_name,
            tool_name=tool_name,
            method_name=config.method_name,
        )
        self._bridge = AgentAsToolBridge(agent, config=bridge_config)

    def execute_task(self, request: RoleTaskRequest) -> RoleTaskResult:
        return self._bridge.execute_task(request)


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
    require_changed_files: bool = True


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
            ],
            max_rounds=request.max_rounds,
            continue_previous=request.continue_previous,
            metadata=dict(request.metadata),
        )
        result = self._base.execute_task(constrained_request)
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

        if not result.artifact_content:
            result.artifact_type = "implementation_report"
            result.artifact_title = result.artifact_title or "Implementation Report"
            result.artifact_format = "markdown"
            result.artifact_content = self._build_artifact_content(changed_paths, diagnostics)
        return result

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
