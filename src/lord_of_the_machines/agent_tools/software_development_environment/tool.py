from __future__ import annotations

from pathlib import Path

from lord_of_the_machines.agent_tools.software_development_environment.commands import (
    CommandOperationsMixin,
)
from lord_of_the_machines.agent_tools.software_development_environment.config import (
    SoftwareDevelopmentEnvironmentToolConfig,
)
from lord_of_the_machines.agent_tools.software_development_environment.definition import (
    build_definition,
)
from lord_of_the_machines.agent_tools.software_development_environment.editing import (
    EditingOperationsMixin,
)
from lord_of_the_machines.agent_tools.software_development_environment.support import (
    SoftwareDevelopmentEnvironmentSupport,
)
from lord_of_the_machines.agent_tools.software_development_environment.workspace import (
    WorkspaceOperationsMixin,
)
from lord_of_the_machines.llm.base_agent import BaseAgent
from lord_of_the_machines.llm.tool_definitions import ToolDefinition
from lord_of_the_machines.llm.tools import ToolHandler


class SoftwareDevelopmentEnvironmentTool(
    WorkspaceOperationsMixin,
    EditingOperationsMixin,
    CommandOperationsMixin,
    SoftwareDevelopmentEnvironmentSupport,
):
    TOOL_NAME = "software_development_environment"

    def __init__(
        self,
        root_path: str | Path,
        *,
        config: SoftwareDevelopmentEnvironmentToolConfig | None = None,
    ) -> None:
        resolved_config = config or SoftwareDevelopmentEnvironmentToolConfig(root_path=Path(root_path))
        super().__init__(resolved_config)

    def install(self, agent: BaseAgent) -> None:
        agent.add_tool(self.definition(), handlers=self.handlers())

    def definition(self) -> ToolDefinition:
        definition = build_definition(self.TOOL_NAME)
        allowed = self._allowed_method_names()
        definition.methods = [method for method in definition.methods if method.name in allowed]
        return definition

    def handlers(self) -> dict[str, ToolHandler]:
        handlers = {
            "list_tree": self._list_tree,
            "find_files": self._find_files,
            "read_file": self._read_file,
            "read_files": self._read_files,
            "file_metadata": self._file_metadata,
            "write_file": self._write_file,
            "append_file": self._append_file,
            "replace_text": self._replace_text,
            "replace_lines": self._replace_lines,
            "insert_text": self._insert_text,
            "search_text": self._search_text,
            "move_path": self._move_path,
            "delete_path": self._delete_path,
            "run_command": self._run_command,
            "run_diagnostics": self._run_diagnostics,
            "git_status": self._git_status,
            "project_context": self._project_context,
            "list_changes": self._list_changes,
            "activity_log": self._activity,
        }
        return self._instrument_handlers(handlers)

    def _allowed_method_names(self) -> set[str]:
        policy = self.config.permission_policy
        allowed: set[str] = set()
        if policy.allow_read_operations:
            allowed.update(
                {
                    "list_tree",
                    "find_files",
                    "read_file",
                    "read_files",
                    "file_metadata",
                    "search_text",
                    "project_context",
                    "list_changes",
                    "activity_log",
                }
            )
        else:
            allowed.update({"list_changes", "activity_log"})
        if policy.allow_write_operations:
            allowed.update({"write_file", "append_file", "replace_text", "replace_lines", "insert_text"})
        if policy.allow_move_operations:
            allowed.add("move_path")
        if policy.allow_delete_operations:
            allowed.add("delete_path")
        if policy.allow_command_execution:
            allowed.add("run_command")
        if policy.allow_diagnostics:
            allowed.add("run_diagnostics")
        if policy.allow_git_inspection:
            allowed.add("git_status")
        return allowed
