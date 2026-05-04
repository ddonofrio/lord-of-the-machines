from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Self


class MappingModel:
    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)


def _ensure_mapping(value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Tool arguments must be a JSON object.")
    return value


def _require_string(values: dict[str, Any], field_name: str) -> str:
    value = values.get(field_name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string.")
    return value


def _require_text(values: dict[str, Any], field_name: str) -> str:
    value = values.get(field_name)
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    return value


def _optional_string(values: dict[str, Any], field_name: str) -> str | None:
    value = values.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string.")
    return value


def _optional_bool(values: dict[str, Any], field_name: str, default: bool) -> bool:
    value = values.get(field_name)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean.")
    return value


def _optional_int(values: dict[str, Any], field_name: str) -> int | None:
    value = values.get(field_name)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer.")
    return value


def _optional_string_list(values: dict[str, Any], field_name: str) -> list[str]:
    value = values.get(field_name)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must be a list of strings.")
    return list(value)


def _optional_int_list(values: dict[str, Any], field_name: str, default: list[int] | None = None) -> list[int]:
    value = values.get(field_name)
    if value is None:
        return list(default or [])
    if not isinstance(value, list) or not all(isinstance(item, int) and not isinstance(item, bool) for item in value):
        raise ValueError(f"{field_name} must be a list of integers.")
    return list(value)


@dataclass(slots=True)
class LineRange(MappingModel):
    start_line: int
    end_line: int


@dataclass(slots=True)
class TreeEntry(MappingModel):
    path: str
    type: str
    depth: int
    size: int | None = None


@dataclass(slots=True)
class FileMatch(MappingModel):
    path: str
    extension: str
    size: int


@dataclass(slots=True)
class SearchMatch(MappingModel):
    path: str
    line_number: int
    column: int
    line: str


@dataclass(slots=True)
class JournalSummary(MappingModel):
    session_id: str
    journal_path: str | None
    entries_in_memory: int
    persist_error: str | None


@dataclass(slots=True)
class ActivityEntry(MappingModel):
    event_id: str
    timestamp: str
    session_id: str
    tool: str
    workspace_root: str
    category: str
    action: str
    status: str
    details: dict[str, Any]


@dataclass(slots=True)
class FileMetadataResult(MappingModel):
    path: str
    type: str
    size: int
    sha256: str | None
    modified_at: str


@dataclass(slots=True)
class ReadFileResult(FileMetadataResult):
    text: str
    encoding: str
    line_range: LineRange
    total_lines: int
    truncated: bool


@dataclass(slots=True)
class ChangeResult(MappingModel):
    action: str
    path: str
    sha256: str
    diff: str
    created: bool
    changed: bool
    replacements: int | None = None
    replaced_line_range: LineRange | None = None
    anchor_occurrence: int | None = None
    position: str | None = None


@dataclass(slots=True)
class MovePathResult(MappingModel):
    action: str
    source_path: str
    destination_path: str
    dry_run: bool
    entries_affected: int
    ok: bool = False


@dataclass(slots=True)
class DeletePathResult(MappingModel):
    action: str
    path: str
    recursive: bool
    dry_run: bool
    entries_affected: int
    ok: bool = False


@dataclass(slots=True)
class RunCommandResult(MappingModel):
    argv: list[str]
    workdir: str
    exit_code: int
    ok: bool
    stdout: str
    stderr: str


@dataclass(slots=True)
class DiagnosticProfileResult(MappingModel):
    profile: str
    ok: bool | None
    skipped: bool = False
    reason: str | None = None
    argv: list[str] | None = None
    workdir: str | None = None
    exit_code: int | None = None
    stdout: str | None = None
    stderr: str | None = None


@dataclass(slots=True)
class GitStatusResult(MappingModel):
    available: bool
    reason: str | None = None
    branch: str | None = None
    status_lines: list[str] = field(default_factory=list)
    working_tree_files: list[str] = field(default_factory=list)
    staged_files: list[str] = field(default_factory=list)
    recent_commits: list[str] = field(default_factory=list)
    diff: str | None = None


@dataclass(slots=True)
class ListTreeResult(MappingModel):
    root: str
    entries: list[TreeEntry]
    max_depth: int
    max_entries: int
    truncated: bool


@dataclass(slots=True)
class FindFilesResult(MappingModel):
    root: str
    matches: list[FileMatch]
    truncated: bool


@dataclass(slots=True)
class ReadFilesResult(MappingModel):
    files: list[ReadFileResult]


@dataclass(slots=True)
class SearchTextResult(MappingModel):
    matches: list[SearchMatch]
    truncated: bool


@dataclass(slots=True)
class ProjectContextResult(MappingModel):
    root: str
    stack: list[str]
    package_managers: list[str]
    configured_tools: list[str]
    requires_python: str | None
    top_level_names: list[str]
    likely_commands: list[list[str]]


@dataclass(slots=True)
class ListChangesResult(MappingModel):
    read_paths: list[str]
    changed_paths: list[str]
    executed_commands: list[RunCommandResult]
    activity_count: int
    journal: JournalSummary


@dataclass(slots=True)
class ActivityLogResult(MappingModel):
    entries: list[ActivityEntry]
    total_entries: int
    journal: JournalSummary


@dataclass(slots=True)
class RunDiagnosticsResult(MappingModel):
    results: list[DiagnosticProfileResult]


@dataclass(slots=True)
class ListTreeRequest:
    path: str | None = None
    max_depth: int | None = None
    max_entries: int | None = None
    extensions: list[str] = field(default_factory=list)
    include_files: bool = True
    include_directories: bool = True

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(
            path=_optional_string(values, "path"),
            max_depth=_optional_int(values, "max_depth"),
            max_entries=_optional_int(values, "max_entries"),
            extensions=_optional_string_list(values, "extensions"),
            include_files=_optional_bool(values, "include_files", True),
            include_directories=_optional_bool(values, "include_directories", True),
        )


@dataclass(slots=True)
class FindFilesRequest:
    path: str | None = None
    name_contains: str | None = None
    extensions: list[str] = field(default_factory=list)
    max_results: int | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(
            path=_optional_string(values, "path"),
            name_contains=_optional_string(values, "name_contains"),
            extensions=_optional_string_list(values, "extensions"),
            max_results=_optional_int(values, "max_results"),
        )


@dataclass(slots=True)
class ReadFileRequest:
    path: str
    start_line: int | None = None
    end_line: int | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(
            path=_require_string(values, "path"),
            start_line=_optional_int(values, "start_line"),
            end_line=_optional_int(values, "end_line"),
        )


@dataclass(slots=True)
class ReadFilesRequest:
    paths: list[str]
    start_line: int | None = None
    end_line: int | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        paths = _optional_string_list(values, "paths")
        if not paths:
            raise ValueError("paths must be a non-empty list of strings.")
        return cls(
            paths=paths,
            start_line=_optional_int(values, "start_line"),
            end_line=_optional_int(values, "end_line"),
        )


@dataclass(slots=True)
class FileMetadataRequest:
    path: str

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(path=_require_string(values, "path"))


@dataclass(slots=True)
class SearchTextRequest:
    query: str
    path: str | None = None
    regex: bool = False
    case_sensitive: bool = False
    extensions: list[str] = field(default_factory=list)
    max_results: int | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(
            query=_require_string(values, "query"),
            path=_optional_string(values, "path"),
            regex=_optional_bool(values, "regex", False),
            case_sensitive=_optional_bool(values, "case_sensitive", False),
            extensions=_optional_string_list(values, "extensions"),
            max_results=_optional_int(values, "max_results"),
        )


@dataclass(slots=True)
class ProjectContextRequest:
    path: str | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(path=_optional_string(values, "path"))


@dataclass(slots=True)
class ListChangesRequest:
    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        _ensure_mapping(value)
        return cls()


@dataclass(slots=True)
class ActivityLogRequest:
    limit: int | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(limit=_optional_int(values, "limit"))


@dataclass(slots=True)
class WriteFileRequest:
    path: str
    content: str
    expected_sha256: str | None = None
    if_missing_only: bool = False
    create_directories: bool = True
    allow_protected_path: bool = False

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(
            path=_require_string(values, "path"),
            content=_require_text(values, "content"),
            expected_sha256=_optional_string(values, "expected_sha256"),
            if_missing_only=_optional_bool(values, "if_missing_only", False),
            create_directories=_optional_bool(values, "create_directories", True),
            allow_protected_path=_optional_bool(values, "allow_protected_path", False),
        )


@dataclass(slots=True)
class AppendFileRequest:
    path: str
    content: str
    expected_sha256: str | None = None
    create_directories: bool = True
    allow_protected_path: bool = False

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(
            path=_require_string(values, "path"),
            content=_require_text(values, "content"),
            expected_sha256=_optional_string(values, "expected_sha256"),
            create_directories=_optional_bool(values, "create_directories", True),
            allow_protected_path=_optional_bool(values, "allow_protected_path", False),
        )


@dataclass(slots=True)
class ReplaceTextRequest:
    path: str
    old_text: str
    new_text: str
    expected_occurrences: int | None = None
    expected_sha256: str | None = None
    allow_protected_path: bool = False

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(
            path=_require_string(values, "path"),
            old_text=_require_string(values, "old_text"),
            new_text=_require_text(values, "new_text"),
            expected_occurrences=_optional_int(values, "expected_occurrences"),
            expected_sha256=_optional_string(values, "expected_sha256"),
            allow_protected_path=_optional_bool(values, "allow_protected_path", False),
        )


@dataclass(slots=True)
class ReplaceLinesRequest:
    path: str
    start_line: int
    end_line: int
    replacement: str
    expected_sha256: str | None = None
    allow_protected_path: bool = False

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        start_line = _optional_int(values, "start_line")
        end_line = _optional_int(values, "end_line")
        if start_line is None or end_line is None:
            raise ValueError("start_line and end_line are required integers.")
        return cls(
            path=_require_string(values, "path"),
            start_line=start_line,
            end_line=end_line,
            replacement=_require_text(values, "replacement"),
            expected_sha256=_optional_string(values, "expected_sha256"),
            allow_protected_path=_optional_bool(values, "allow_protected_path", False),
        )


@dataclass(slots=True)
class InsertTextRequest:
    path: str
    anchor: str
    text: str
    position: str = "after"
    occurrence: int = 1
    expected_sha256: str | None = None
    allow_protected_path: bool = False

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        occurrence = _optional_int(values, "occurrence")
        return cls(
            path=_require_string(values, "path"),
            anchor=_require_string(values, "anchor"),
            text=_require_text(values, "text"),
            position=_optional_string(values, "position") or "after",
            occurrence=occurrence if occurrence is not None else 1,
            expected_sha256=_optional_string(values, "expected_sha256"),
            allow_protected_path=_optional_bool(values, "allow_protected_path", False),
        )


@dataclass(slots=True)
class MovePathRequest:
    source_path: str
    destination_path: str
    overwrite: bool = False
    dry_run: bool = True
    confirm: bool = False
    allow_protected_path: bool = False

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(
            source_path=_require_string(values, "source_path"),
            destination_path=_require_string(values, "destination_path"),
            overwrite=_optional_bool(values, "overwrite", False),
            dry_run=_optional_bool(values, "dry_run", True),
            confirm=_optional_bool(values, "confirm", False),
            allow_protected_path=_optional_bool(values, "allow_protected_path", False),
        )


@dataclass(slots=True)
class DeletePathRequest:
    path: str
    recursive: bool = False
    dry_run: bool = True
    confirm: bool = False
    expected_sha256: str | None = None
    allow_protected_path: bool = False

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(
            path=_require_string(values, "path"),
            recursive=_optional_bool(values, "recursive", False),
            dry_run=_optional_bool(values, "dry_run", True),
            confirm=_optional_bool(values, "confirm", False),
            expected_sha256=_optional_string(values, "expected_sha256"),
            allow_protected_path=_optional_bool(values, "allow_protected_path", False),
        )


@dataclass(slots=True)
class RunCommandRequest:
    argv: list[str]
    workdir: str | None = None
    timeout_seconds: int | None = None
    expected_exit_codes: list[int] = field(default_factory=lambda: [0])

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        argv = _optional_string_list(values, "argv")
        if not argv:
            raise ValueError("argv must be a non-empty list of strings.")
        return cls(
            argv=argv,
            workdir=_optional_string(values, "workdir"),
            timeout_seconds=_optional_int(values, "timeout_seconds"),
            expected_exit_codes=_optional_int_list(values, "expected_exit_codes", [0]),
        )


@dataclass(slots=True)
class RunDiagnosticsRequest:
    profiles: list[str] = field(default_factory=lambda: ["pytest", "ruff", "mypy", "pyright", "bandit"])
    workdir: str | None = None
    timeout_seconds: int | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        profiles = _optional_string_list(values, "profiles")
        return cls(
            profiles=profiles or ["pytest", "ruff", "mypy", "pyright", "bandit"],
            workdir=_optional_string(values, "workdir"),
            timeout_seconds=_optional_int(values, "timeout_seconds"),
        )


@dataclass(slots=True)
class GitStatusRequest:
    include_diff: bool = False
    recent_commit_count: int | None = None
    max_diff_chars: int | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> Self:
        values = _ensure_mapping(value)
        return cls(
            include_diff=_optional_bool(values, "include_diff", False),
            recent_commit_count=_optional_int(values, "recent_commit_count"),
            max_diff_chars=_optional_int(values, "max_diff_chars"),
        )
