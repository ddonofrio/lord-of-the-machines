from __future__ import annotations

import difflib
import hashlib
import importlib.util
import re
import shutil
import subprocess
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lord_of_the_machines.agent_tools.software_development_environment.config import (
    SoftwareDevelopmentEnvironmentToolConfig,
)
from lord_of_the_machines.agent_tools.software_development_environment.contracts import (
    ChangeResult,
    FileMetadataResult,
    LineRange,
    ReadFileResult,
    RunCommandResult,
)
from lord_of_the_machines.agent_tools.software_development_environment.journal import (
    ToolActivityJournal,
    ToolActivityJournalConfig,
)
from lord_of_the_machines.agent_tools.software_development_environment.policy import (
    SoftwareDevelopmentEnvironmentPolicyError,
)
from lord_of_the_machines.llm.tools import ToolHandler


class SoftwareDevelopmentEnvironmentSupport:
    TOOL_NAME = "software_development_environment"

    def __init__(self, config: SoftwareDevelopmentEnvironmentToolConfig) -> None:
        self.config = config
        self._read_paths: list[str] = []
        self._changed_paths: list[str] = []
        self._executed_commands: list[RunCommandResult] = []
        self._journal = ToolActivityJournal(
            tool_name=self.TOOL_NAME,
            workspace_root=self.config.root_path,
            config=ToolActivityJournalConfig(
                enabled=self.config.journal_enabled,
                log_dir=self.config.journal_log_dir,
                file_prefix=self.config.journal_file_prefix,
                max_entries=self.config.activity_memory_limit,
                text_preview_chars=self.config.journal_text_preview_chars,
            ),
        )

    def _instrument_handlers(self, handlers: dict[str, ToolHandler]) -> dict[str, ToolHandler]:
        return {
            method_name: self._instrument_handler(method_name, handler)
            for method_name, handler in handlers.items()
        }

    def _instrument_handler(self, method_name: str, handler: ToolHandler) -> ToolHandler:
        def wrapped(arguments: dict[str, Any]) -> Any:
            self._record_activity(
                method_name,
                {
                    "phase": "started",
                    "arguments": arguments,
                },
                status="started",
                category="operation",
            )
            try:
                result = handler(arguments)
            except Exception as exc:
                self._record_activity(
                    method_name,
                    {
                        "phase": "failed",
                        "arguments": arguments,
                        "error": str(exc),
                    },
                    status="failed",
                    category="operation",
                )
                raise
            self._record_activity(
                method_name,
                {
                    "phase": "finished",
                    "result": result,
                },
                status="succeeded",
                category="operation",
            )
            return result

        return wrapped

    def _record_activity(
        self,
        action: str,
        details: dict[str, Any],
        *,
        status: str = "info",
        category: str = "activity",
    ) -> None:
        self._journal.record(action=action, details=details, status=status, category=category)

    def _record_change(self, path: Path, action: str) -> None:
        self._changed_paths.append(self._relative_path(path))
        self._record_activity(
            action,
            {
                "path": self._relative_path(path),
                "changed_paths": self._unique_preserving_order(self._changed_paths),
            },
            status="ok",
            category="mutation",
        )

    def _iter_paths(self, start_path: Path):
        for current_path in sorted(start_path.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
            if self._is_ignored(current_path):
                continue
            yield current_path
            if current_path.is_dir():
                yield from self._iter_paths(current_path)

    def _read_text_file(self, path: Path, *, start_line: Any = None, end_line: Any = None) -> ReadFileResult:
        text = self._safe_read_text(path)
        lines = text.splitlines()
        total_lines = len(lines)

        start = self._int_argument(start_line, 1, minimum=1) if start_line is not None else 1
        end = self._int_argument(end_line, total_lines, minimum=start) if end_line is not None else total_lines
        if start > total_lines and total_lines > 0:
            raise ValueError(f"start_line {start} exceeds file length {total_lines}.")
        if end > total_lines and total_lines > 0:
            raise ValueError(f"end_line {end} exceeds file length {total_lines}.")

        selected_lines = lines[start - 1 : end] if total_lines else []
        selected_text = "\n".join(selected_lines)
        metadata = self._metadata_for_path(path)
        return ReadFileResult(
            path=metadata.path,
            type=metadata.type,
            size=metadata.size,
            sha256=metadata.sha256,
            modified_at=metadata.modified_at,
            text=self._clip_text(selected_text, limit=self.config.read_char_limit),
            encoding="utf-8",
            line_range=LineRange(start_line=start, end_line=end if total_lines else 0),
            total_lines=total_lines,
            truncated=len(selected_text) > self.config.read_char_limit,
        )

    def _safe_read_text(self, path: Path) -> str:
        if path.is_dir():
            raise IsADirectoryError(f"Expected a file, got directory: {self._relative_path(path)}")
        raw = path.read_bytes()
        if b"\x00" in raw:
            raise ValueError(f"Refusing to read binary file as text: {self._relative_path(path)}")
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"File is not valid UTF-8 text: {self._relative_path(path)}") from exc

    def _metadata_for_path(self, path: Path) -> FileMetadataResult:
        stat_result = path.stat()
        return FileMetadataResult(
            path=self._relative_path(path),
            type="directory" if path.is_dir() else "file",
            size=stat_result.st_size,
            sha256=self._sha256(path) if path.is_file() else None,
            modified_at=datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc).isoformat(),
        )

    def _read_existing_text(self, path: Path, *, require_exists: bool = False) -> tuple[str, str | None]:
        if not path.exists():
            if require_exists:
                raise FileNotFoundError(f"Path does not exist: {self._relative_path(path)}")
            return "", None
        return self._safe_read_text(path), self._sha256(path)

    def _assert_expected_sha256(self, path: Path, expected_sha256: Any, *, current_sha256: str | None = None) -> None:
        if expected_sha256 is None:
            return
        actual_sha256 = current_sha256
        if actual_sha256 is None and path.exists() and path.is_file():
            actual_sha256 = self._sha256(path)
        if expected_sha256 != actual_sha256:
            raise ValueError(
                f"File changed since last read for {self._relative_path(path)}: expected sha256 {expected_sha256}, got {actual_sha256}."
            )

    def _assert_no_large_truncation(
        self,
        path: Path,
        *,
        before_text: str,
        after_text: str,
        operation_name: str,
        allow_large_rewrite: bool,
    ) -> None:
        if allow_large_rewrite:
            return
        if not self.config.truncation_guard_enabled:
            return
        before_length = len(before_text)
        if before_length <= 0:
            return
        after_length = len(after_text)
        removed_chars = before_length - after_length
        if removed_chars <= 0:
            return
        removed_ratio = removed_chars / before_length
        if removed_chars < self.config.max_file_shrink_chars:
            return
        if removed_ratio < self.config.max_file_shrink_ratio:
            return
        raise SoftwareDevelopmentEnvironmentPolicyError(
            (
                f"{operation_name} blocked by truncation guard for {self._relative_path(path)}: "
                f"removed {removed_chars} chars ({removed_ratio:.1%}). "
                "Use a targeted edit method (replace_text/replace_lines/insert_text) or set allow_large_rewrite=true "
                "for an intentional full rewrite."
            )
        )

    def _change_result(self, path: Path, before_text: str, after_text: str, action: str) -> ChangeResult:
        diff = self._unified_diff(before_text, after_text, self._relative_path(path))
        return ChangeResult(
            action=action,
            path=self._relative_path(path),
            sha256=self._sha256(path),
            diff=self._clip_text(diff),
            created=not before_text and path.exists(),
            changed=before_text != after_text,
        )

    def _unified_diff(self, before_text: str, after_text: str, relative_path: str) -> str:
        diff_lines = difflib.unified_diff(
            before_text.splitlines(),
            after_text.splitlines(),
            fromfile=f"a/{relative_path}",
            tofile=f"b/{relative_path}",
            lineterm="",
        )
        return "\n".join(diff_lines)

    def _run_git(self, argv: list[str]) -> RunCommandResult:
        completed = subprocess.run(
            ["git", *argv],
            cwd=str(self.config.root_path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=self.config.default_command_timeout_seconds,
            shell=False,
        )
        return RunCommandResult(
            argv=["git", *argv],
            workdir=".",
            exit_code=completed.returncode,
            ok=completed.returncode == 0,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def _diagnostic_commands(self, profiles: list[Any]) -> list[tuple[str, list[str] | None]]:
        commands: list[tuple[str, list[str] | None]] = []
        for raw_profile in profiles:
            profile = str(raw_profile).lower()
            if profile == "pytest":
                commands.append(("pytest", self._python_module_command("pytest", ["python", "-m", "pytest"])))
            elif profile == "ruff":
                commands.append(("ruff", self._python_module_command("ruff", ["python", "-m", "ruff", "check", "."])))
            elif profile == "mypy":
                commands.append(("mypy", self._python_module_command("mypy", ["python", "-m", "mypy", "."])))
            elif profile == "pyright":
                commands.append(("pyright", ["pyright"] if shutil.which("pyright") else None))
            elif profile == "bandit":
                commands.append(("bandit", self._python_module_command("bandit", ["python", "-m", "bandit", "-r", "."])))
            elif profile == "unittest":
                commands.append(("unittest", ["python", "-m", "unittest", "discover", "-s", "tests"]))
            else:
                commands.append((profile, None))
        return commands

    def _python_module_command(self, module_name: str, argv: list[str]) -> list[str] | None:
        return argv if importlib.util.find_spec(module_name) is not None else None

    def _detect_node_manager(self, root: Path) -> str:
        if (root / "pnpm-lock.yaml").exists():
            return "pnpm"
        if (root / "yarn.lock").exists():
            return "yarn"
        return "npm"

    def _resolve_path(self, raw_path: Any, *, allow_missing: bool) -> Path:
        if raw_path in (None, "", "."):
            path = self.config.root_path
        else:
            candidate = Path(str(raw_path))
            path = candidate.resolve() if candidate.is_absolute() else (self.config.root_path / candidate).resolve()
        if not self._is_within_root(path):
            raise ValueError(f"Path is outside the workspace root: {raw_path}")
        if not allow_missing and not path.exists():
            raise FileNotFoundError(f"Path does not exist: {self._relative_path(path)}")
        return path

    def _relative_path(self, path: Path) -> str:
        if path == self.config.root_path:
            return "."
        return path.relative_to(self.config.root_path).as_posix()

    def _is_within_root(self, path: Path) -> bool:
        try:
            path.relative_to(self.config.root_path)
            return True
        except ValueError:
            return False

    def _is_ignored(self, path: Path) -> bool:
        try:
            relative_parts = path.relative_to(self.config.root_path).parts
        except ValueError:
            return True
        return any(part in self.config.ignore_names for part in relative_parts)

    def _assert_writable_path(self, path: Path, *, allow_protected: bool) -> None:
        if not self._is_within_root(path):
            raise ValueError(f"Path is outside the workspace root: {path}")
        if self._is_protected_path(path) and not (allow_protected and self.config.permission_policy.allow_protected_path_writes):
            raise ValueError(
                f"Refusing to modify protected path {self._relative_path(path)} without allow_protected_path=true."
            )

    def _is_protected_path(self, path: Path) -> bool:
        name = path.name.lower()
        if name in self.config.protected_file_names:
            return True
        return any(name.endswith(suffix) for suffix in self.config.protected_suffixes)

    def _sha256(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _ensure_allowed_command(self, executable: str) -> None:
        normalized = Path(executable).name.lower()
        for suffix in (".exe", ".cmd", ".bat"):
            if normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)]
        if normalized not in self.config.allowed_command_names:
            allowed = ", ".join(sorted(self.config.allowed_command_names))
            raise ValueError(f"Command '{executable}' is not allowed. Allowed commands: {allowed}.")

    def _clip_text(self, value: str, *, limit: int | None = None) -> str:
        max_chars = limit or self.config.command_output_char_limit
        if len(value) <= max_chars:
            return value
        return value[: max(0, max_chars - 3)].rstrip() + "..."

    def _path_entry_count(self, path: Path) -> int:
        if path.is_file():
            return 1
        count = 0
        for current_path in path.rglob("*"):
            if self._is_ignored(current_path):
                continue
            count += 1
        return count

    def _normalized_extensions(self, raw_extensions: Any) -> set[str]:
        if not raw_extensions:
            return set()
        extensions = set()
        for raw_extension in raw_extensions:
            extension = str(raw_extension).strip().lower()
            if not extension:
                continue
            extensions.add(extension if extension.startswith(".") else f".{extension}")
        return extensions

    def _int_argument(self, value: Any, default: int | None = None, *, minimum: int | None = None) -> int:
        if value is None:
            if default is None:
                raise ValueError("Missing integer argument.")
            number = int(default)
        else:
            number = int(value)
        if minimum is not None and number < minimum:
            raise ValueError(f"Expected integer >= {minimum}, got {number}.")
        return number

    def _assert_read_allowed(self, operation_name: str) -> None:
        if not self.config.permission_policy.allow_read_operations:
            raise SoftwareDevelopmentEnvironmentPolicyError(f"{operation_name} is disabled by permission policy.")

    def _assert_write_allowed(self, operation_name: str) -> None:
        if not self.config.permission_policy.allow_write_operations:
            raise SoftwareDevelopmentEnvironmentPolicyError(f"{operation_name} is disabled by permission policy.")

    def _assert_command_allowed(self, operation_name: str, *, timeout_seconds: int | None = None) -> None:
        if not self.config.permission_policy.allow_command_execution:
            raise SoftwareDevelopmentEnvironmentPolicyError(f"{operation_name} is disabled by permission policy.")
        max_timeout = self.config.execution_policy.max_command_timeout_seconds
        if max_timeout is not None and timeout_seconds is not None and timeout_seconds > max_timeout:
            raise SoftwareDevelopmentEnvironmentPolicyError(
                f"{operation_name} timeout {timeout_seconds}s exceeds execution policy limit {max_timeout}s."
            )

    def _assert_diagnostics_allowed(self) -> None:
        if not self.config.permission_policy.allow_diagnostics:
            raise SoftwareDevelopmentEnvironmentPolicyError("run_diagnostics is disabled by permission policy.")

    def _assert_git_allowed(self) -> None:
        if not self.config.permission_policy.allow_git_inspection:
            raise SoftwareDevelopmentEnvironmentPolicyError("git_status is disabled by permission policy.")

    def _assert_move_allowed(self, *, dry_run: bool, entries_affected: int) -> None:
        if dry_run:
            self._assert_read_allowed("move_path")
            return
        self._assert_write_allowed("move_path")
        if not self.config.permission_policy.allow_move_operations:
            raise SoftwareDevelopmentEnvironmentPolicyError("move_path is disabled by permission policy.")
        self._assert_destructive_scope("move_path", entries_affected)

    def _assert_delete_allowed(self, *, dry_run: bool, entries_affected: int) -> None:
        if dry_run:
            self._assert_read_allowed("delete_path")
            return
        self._assert_write_allowed("delete_path")
        if not self.config.permission_policy.allow_delete_operations:
            raise SoftwareDevelopmentEnvironmentPolicyError("delete_path is disabled by permission policy.")
        self._assert_destructive_scope("delete_path", entries_affected)

    def _assert_destructive_scope(self, operation_name: str, entries_affected: int) -> None:
        max_entries = self.config.execution_policy.max_destructive_entries
        if max_entries is not None and entries_affected > max_entries:
            raise SoftwareDevelopmentEnvironmentPolicyError(
                f"{operation_name} affects {entries_affected} entries, above the execution policy limit {max_entries}."
            )

    @staticmethod
    def _unique_preserving_order(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result
