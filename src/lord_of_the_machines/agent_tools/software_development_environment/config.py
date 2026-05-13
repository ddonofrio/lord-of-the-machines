from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lord_of_the_machines.agent_tools.software_development_environment.policy import (
    SoftwareDevelopmentEnvironmentExecutionPolicy,
    SoftwareDevelopmentEnvironmentPermissionPolicy,
)


DEFAULT_IGNORE_NAMES = (
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".coverage",
    ".idea",
    ".vscode",
)
DEFAULT_PROTECTED_FILE_NAMES = (
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    ".env.test",
    ".git-credentials",
)
DEFAULT_PROTECTED_SUFFIXES = (
    ".pem",
    ".key",
    ".p12",
    ".pfx",
)
DEFAULT_ALLOWED_COMMANDS = (
    "python",
    "py",
    "pytest",
    "ruff",
    "mypy",
    "pyright",
    "coverage",
    "bandit",
    "uv",
    "pip",
    "poetry",
    "git",
    "npm",
    "pnpm",
    "yarn",
    "node",
)
DEFAULT_TREE_MAX_DEPTH = 4
DEFAULT_TREE_MAX_ENTRIES = 500
DEFAULT_SEARCH_MAX_RESULTS = 200
DEFAULT_COMMAND_TIMEOUT_SECONDS = 120
DEFAULT_OUTPUT_CHAR_LIMIT = 12_000
DEFAULT_READ_CHAR_LIMIT = 8_000
DEFAULT_LARGE_CHANGE_FILE_THRESHOLD = 25
DEFAULT_ACTIVITY_MEMORY_LIMIT = 500
DEFAULT_JOURNAL_TEXT_PREVIEW_CHARS = 240
DEFAULT_JOURNAL_FILE_PREFIX = "software-development-environment"
DEFAULT_TRUNCATION_GUARD_ENABLED = True
DEFAULT_MAX_FILE_SHRINK_RATIO = 0.35
DEFAULT_MAX_FILE_SHRINK_CHARS = 2000


@dataclass(slots=True)
class SoftwareDevelopmentEnvironmentToolConfig:
    root_path: Path
    ignore_names: tuple[str, ...] = DEFAULT_IGNORE_NAMES
    protected_file_names: tuple[str, ...] = DEFAULT_PROTECTED_FILE_NAMES
    protected_suffixes: tuple[str, ...] = DEFAULT_PROTECTED_SUFFIXES
    allowed_command_names: tuple[str, ...] = DEFAULT_ALLOWED_COMMANDS
    default_tree_max_depth: int = DEFAULT_TREE_MAX_DEPTH
    default_tree_max_entries: int = DEFAULT_TREE_MAX_ENTRIES
    default_search_max_results: int = DEFAULT_SEARCH_MAX_RESULTS
    default_command_timeout_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS
    command_output_char_limit: int = DEFAULT_OUTPUT_CHAR_LIMIT
    read_char_limit: int = DEFAULT_READ_CHAR_LIMIT
    large_change_file_threshold: int = DEFAULT_LARGE_CHANGE_FILE_THRESHOLD
    journal_enabled: bool = True
    journal_log_dir: Path | None = None
    journal_file_prefix: str = DEFAULT_JOURNAL_FILE_PREFIX
    activity_memory_limit: int = DEFAULT_ACTIVITY_MEMORY_LIMIT
    journal_text_preview_chars: int = DEFAULT_JOURNAL_TEXT_PREVIEW_CHARS
    truncation_guard_enabled: bool = DEFAULT_TRUNCATION_GUARD_ENABLED
    max_file_shrink_ratio: float = DEFAULT_MAX_FILE_SHRINK_RATIO
    max_file_shrink_chars: int = DEFAULT_MAX_FILE_SHRINK_CHARS
    permission_policy: SoftwareDevelopmentEnvironmentPermissionPolicy = field(
        default_factory=SoftwareDevelopmentEnvironmentPermissionPolicy
    )
    execution_policy: SoftwareDevelopmentEnvironmentExecutionPolicy = field(
        default_factory=SoftwareDevelopmentEnvironmentExecutionPolicy
    )

    def __post_init__(self) -> None:
        self.root_path = Path(self.root_path).resolve()
        if self.journal_log_dir is not None:
            self.journal_log_dir = Path(self.journal_log_dir).resolve()
        if not self.root_path.exists():
            raise FileNotFoundError(f"Workspace root does not exist: {self.root_path}")
        if not self.root_path.is_dir():
            raise NotADirectoryError(f"Workspace root must be a directory: {self.root_path}")
        if self.execution_policy.max_destructive_entries is not None and self.execution_policy.max_destructive_entries < 1:
            raise ValueError("execution_policy.max_destructive_entries must be >= 1 when set.")
        if self.execution_policy.max_command_timeout_seconds is not None and self.execution_policy.max_command_timeout_seconds < 1:
            raise ValueError("execution_policy.max_command_timeout_seconds must be >= 1 when set.")
        if not (0.0 <= float(self.max_file_shrink_ratio) <= 1.0):
            raise ValueError("max_file_shrink_ratio must be between 0.0 and 1.0.")
        if int(self.max_file_shrink_chars) < 0:
            raise ValueError("max_file_shrink_chars must be >= 0.")
