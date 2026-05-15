from __future__ import annotations

from lord_of_the_machines.llm.tool_definitions import ToolDefinition, ToolMethodDefinition


def build_definition(tool_name: str) -> ToolDefinition:
    path_property = {
        "type": "string",
        "description": "Path relative to the configured workspace root.",
    }
    extensions_property = {
        "type": "array",
        "items": {"type": "string"},
        "description": "Optional list of file extensions such as .py or .md.",
    }
    return ToolDefinition(
        name=tool_name,
        description=(
            "Inspect and manage a software workspace: tree listing, file reads, controlled writes, "
            "precise edits, text search, safe command execution, diagnostics, project context, git status, "
            "and a persisted activity journal."
        ),
        internal=True,
        methods=[
            ToolMethodDefinition(
                name="list_tree",
                description="List a filtered directory tree within the workspace while ignoring heavy generated folders.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "path": path_property,
                        "max_depth": {"type": "integer"},
                        "max_entries": {"type": "integer"},
                        "extensions": extensions_property,
                        "include_files": {"type": "boolean"},
                        "include_directories": {"type": "boolean"},
                    },
                    "required": [],
                },
            ),
            ToolMethodDefinition(
                name="find_files",
                description="Search files by name fragment and optional extension filters.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "path": path_property,
                        "name_contains": {"type": "string"},
                        "extensions": extensions_property,
                        "max_results": {"type": "integer"},
                    },
                    "required": [],
                },
            ),
            ToolMethodDefinition(
                name="read_file",
                description=(
                    "Read a text file fully or by 1-based inclusive line range, including metadata "
                    "and a content hash."
                ),
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "path": path_property,
                        "start_line": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "1-based inclusive start line.",
                        },
                        "end_line": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "1-based inclusive end line.",
                        },
                    },
                    "required": ["path"],
                },
            ),
            ToolMethodDefinition(
                name="read_files",
                description="Read several text files in one call using optional 1-based inclusive line ranges.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "paths": {"type": "array", "items": {"type": "string"}},
                        "start_line": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "1-based inclusive start line applied to each file.",
                        },
                        "end_line": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "1-based inclusive end line applied to each file.",
                        },
                    },
                    "required": ["paths"],
                },
            ),
            ToolMethodDefinition(
                name="file_metadata",
                description="Return size, hash, timestamps and type metadata for one path.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"path": path_property},
                    "required": ["path"],
                },
            ),
            ToolMethodDefinition(
                name="write_file",
                description=(
                    "Create or overwrite a text file, optionally guarded by an expected previous sha256. "
                    "For existing files, prefer targeted edit methods over full rewrites."
                ),
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "path": path_property,
                        "content": {"type": "string"},
                        "expected_sha256": {"type": "string"},
                        "if_missing_only": {"type": "boolean"},
                        "create_directories": {"type": "boolean"},
                        "allow_large_rewrite": {"type": "boolean"},
                        "allow_protected_path": {"type": "boolean"},
                    },
                    "required": ["path", "content"],
                },
            ),
            ToolMethodDefinition(
                name="append_file",
                description="Append text to a file, optionally guarded by an expected previous sha256.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "path": path_property,
                        "content": {"type": "string"},
                        "expected_sha256": {"type": "string"},
                        "create_directories": {"type": "boolean"},
                        "allow_protected_path": {"type": "boolean"},
                    },
                    "required": ["path", "content"],
                },
            ),
            ToolMethodDefinition(
                name="replace_text",
                description="Replace exact text inside a file with match-count validation.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "path": path_property,
                        "old_text": {"type": "string"},
                        "new_text": {"type": "string"},
                        "expected_occurrences": {"type": "integer"},
                        "expected_sha256": {"type": "string"},
                        "allow_large_rewrite": {"type": "boolean"},
                        "allow_protected_path": {"type": "boolean"},
                    },
                    "required": ["path", "old_text", "new_text"],
                },
            ),
            ToolMethodDefinition(
                name="replace_lines",
                description="Replace a 1-based inclusive line range in a file.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "path": path_property,
                        "start_line": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "1-based inclusive start line.",
                        },
                        "end_line": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "1-based inclusive end line.",
                        },
                        "replacement": {"type": "string"},
                        "expected_sha256": {"type": "string"},
                        "allow_large_rewrite": {"type": "boolean"},
                        "allow_protected_path": {"type": "boolean"},
                    },
                    "required": ["path", "start_line", "end_line", "replacement"],
                },
            ),
            ToolMethodDefinition(
                name="insert_text",
                description="Insert text before or after an anchor block with occurrence validation.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "path": path_property,
                        "anchor": {"type": "string"},
                        "text": {"type": "string"},
                        "position": {"type": "string", "enum": ["before", "after"]},
                        "occurrence": {"type": "integer"},
                        "expected_sha256": {"type": "string"},
                        "allow_large_rewrite": {"type": "boolean"},
                        "allow_protected_path": {"type": "boolean"},
                    },
                    "required": ["path", "anchor", "text"],
                },
            ),
            ToolMethodDefinition(
                name="search_text",
                description="Search text or regex patterns across project files under a directory, or inside one specific file path.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "path": path_property,
                        "query": {"type": "string"},
                        "regex": {"type": "boolean"},
                        "case_sensitive": {"type": "boolean"},
                        "extensions": extensions_property,
                        "max_results": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            ),
            ToolMethodDefinition(
                name="move_path",
                description="Move or rename a file or directory. Actual execution requires dry_run=false and confirm=true.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "source_path": path_property,
                        "destination_path": path_property,
                        "overwrite": {"type": "boolean"},
                        "dry_run": {"type": "boolean"},
                        "confirm": {"type": "boolean"},
                        "allow_protected_path": {"type": "boolean"},
                    },
                    "required": ["source_path", "destination_path"],
                },
            ),
            ToolMethodDefinition(
                name="delete_path",
                description="Delete a file or directory. Actual execution requires dry_run=false and confirm=true.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "path": path_property,
                        "recursive": {"type": "boolean"},
                        "dry_run": {"type": "boolean"},
                        "confirm": {"type": "boolean"},
                        "expected_sha256": {"type": "string"},
                        "allow_protected_path": {"type": "boolean"},
                    },
                    "required": ["path"],
                },
            ),
            ToolMethodDefinition(
                name="run_command",
                description="Run an allowed command inside the workspace using argv form, not shell text.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "argv": {"type": "array", "items": {"type": "string"}},
                        "workdir": path_property,
                        "timeout_seconds": {"type": "integer"},
                        "expected_exit_codes": {"type": "array", "items": {"type": "integer"}},
                    },
                    "required": ["argv"],
                },
            ),
            ToolMethodDefinition(
                name="run_diagnostics",
                description="Run project diagnostics such as pytest, ruff, mypy, pyright or bandit when available.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "profiles": {"type": "array", "items": {"type": "string"}},
                        "workdir": path_property,
                        "timeout_seconds": {"type": "integer"},
                    },
                    "required": [],
                },
            ),
            ToolMethodDefinition(
                name="git_status",
                description="Inspect the git state of the workspace: branch, status lines, changed files and recent commits.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "include_diff": {"type": "boolean"},
                        "max_diff_chars": {"type": "integer"},
                        "recent_commit_count": {"type": "integer"},
                    },
                    "required": [],
                },
            ),
            ToolMethodDefinition(
                name="project_context",
                description="Detect project stack, dependency managers, configured tools and likely standard commands.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"path": path_property},
                    "required": [],
                },
            ),
            ToolMethodDefinition(
                name="list_changes",
                description="Summarize what this tool has read, changed and executed during the current session, including journal metadata.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {},
                    "required": [],
                },
            ),
            ToolMethodDefinition(
                name="activity_log",
                description="Return recent entries from the persisted activity journal of this tool session.",
                arguments_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"limit": {"type": "integer"}},
                    "required": [],
                },
            ),
        ],
    )
