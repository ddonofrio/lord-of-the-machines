from __future__ import annotations

from dataclasses import dataclass


DEFAULT_MAX_DESTRUCTIVE_ENTRIES = 25
DEFAULT_MAX_COMMAND_TIMEOUT_SECONDS = 120


class SoftwareDevelopmentEnvironmentPolicyError(PermissionError):
    pass


@dataclass(slots=True)
class SoftwareDevelopmentEnvironmentPermissionPolicy:
    allow_read_operations: bool = True
    allow_write_operations: bool = True
    allow_move_operations: bool = True
    allow_delete_operations: bool = True
    allow_command_execution: bool = True
    allow_diagnostics: bool = True
    allow_git_inspection: bool = True
    allow_protected_path_writes: bool = False

    @classmethod
    def read_only(cls) -> SoftwareDevelopmentEnvironmentPermissionPolicy:
        return cls(
            allow_read_operations=True,
            allow_write_operations=False,
            allow_move_operations=False,
            allow_delete_operations=False,
            allow_command_execution=False,
            allow_diagnostics=False,
            allow_git_inspection=True,
            allow_protected_path_writes=False,
        )


@dataclass(slots=True)
class SoftwareDevelopmentEnvironmentExecutionPolicy:
    require_confirmation_for_destructive_operations: bool = True
    require_dry_run_for_move: bool = True
    require_dry_run_for_delete: bool = True
    max_destructive_entries: int | None = DEFAULT_MAX_DESTRUCTIVE_ENTRIES
    max_command_timeout_seconds: int | None = DEFAULT_MAX_COMMAND_TIMEOUT_SECONDS

