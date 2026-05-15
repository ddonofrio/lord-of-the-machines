from __future__ import annotations

import re
import tomllib
from pathlib import Path

from lord_of_the_machines.agent_tools.software_development_environment.contracts import (
    ActivityLogRequest,
    ActivityLogResult,
    FileMatch,
    FileMetadataRequest,
    FindFilesRequest,
    FindFilesResult,
    ListChangesRequest,
    ListChangesResult,
    ListTreeRequest,
    ListTreeResult,
    ProjectContextRequest,
    ProjectContextResult,
    ReadFileRequest,
    ReadFilesRequest,
    ReadFilesResult,
    SearchMatch,
    SearchTextRequest,
    SearchTextResult,
    TreeEntry,
)


class WorkspaceOperationsMixin:
    def _list_tree(self, arguments: dict[str, object]) -> dict[str, object]:
        request = ListTreeRequest.from_mapping(arguments)
        self._assert_read_allowed("list_tree")
        start_path = self._resolve_path(request.path, allow_missing=False)
        if not start_path.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {self._relative_path(start_path)}")

        max_depth = self._int_argument(request.max_depth, self.config.default_tree_max_depth, minimum=0)
        max_entries = self._int_argument(request.max_entries, self.config.default_tree_max_entries, minimum=1)
        extensions = self._normalized_extensions(request.extensions)
        include_files = request.include_files
        include_directories = request.include_directories

        base_depth = len(start_path.relative_to(self.config.root_path).parts)
        entries: list[TreeEntry] = []
        for current_path in self._iter_paths(start_path):
            relative = current_path.relative_to(self.config.root_path)
            depth = max(0, len(relative.parts) - base_depth)
            if depth > max_depth:
                continue
            if current_path.is_file() and not include_files:
                continue
            if current_path.is_dir() and not include_directories:
                continue
            if current_path.is_file() and extensions and current_path.suffix.lower() not in extensions:
                continue
            entries.append(
                TreeEntry(
                    path=self._relative_path(current_path),
                    type="directory" if current_path.is_dir() else "file",
                    depth=depth,
                    size=current_path.stat().st_size if current_path.is_file() else None,
                )
            )
            if len(entries) >= max_entries:
                break

        self._record_activity(
            "list_tree_scan",
            {"path": self._relative_path(start_path), "entries": len(entries)},
            status="ok",
            category="workspace",
        )
        return ListTreeResult(
            root=self._relative_path(start_path),
            entries=entries,
            max_depth=max_depth,
            max_entries=max_entries,
            truncated=len(entries) >= max_entries,
        ).to_mapping()

    def _find_files(self, arguments: dict[str, object]) -> dict[str, object]:
        request = FindFilesRequest.from_mapping(arguments)
        self._assert_read_allowed("find_files")
        start_path = self._resolve_path(request.path, allow_missing=False)
        if not start_path.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {self._relative_path(start_path)}")

        name_contains = (request.name_contains or "").lower()
        extensions = self._normalized_extensions(request.extensions)
        max_results = self._int_argument(request.max_results, self.config.default_search_max_results, minimum=1)

        matches: list[FileMatch] = []
        for current_path in self._iter_paths(start_path):
            if not current_path.is_file():
                continue
            if name_contains and name_contains not in current_path.name.lower():
                continue
            if extensions and current_path.suffix.lower() not in extensions:
                continue
            matches.append(
                FileMatch(
                    path=self._relative_path(current_path),
                    extension=current_path.suffix.lower(),
                    size=current_path.stat().st_size,
                )
            )
            if len(matches) >= max_results:
                break

        self._record_activity(
            "find_files_scan",
            {"path": self._relative_path(start_path), "matches": len(matches)},
            status="ok",
            category="workspace",
        )
        return FindFilesResult(
            root=self._relative_path(start_path),
            matches=matches,
            truncated=len(matches) >= max_results,
        ).to_mapping()

    def _read_file(self, arguments: dict[str, object]) -> dict[str, object]:
        request = ReadFileRequest.from_mapping(arguments)
        self._assert_read_allowed("read_file")
        path = self._resolve_path(request.path, allow_missing=False)
        result = self._read_text_file(
            path,
            start_line=request.start_line,
            end_line=request.end_line,
        )
        self._read_paths.append(result.path)
        self._record_activity(
            "read_file_content",
            {"path": result.path, "line_range": result.line_range.to_mapping()},
            status="ok",
            category="read",
        )
        return result.to_mapping()

    def _read_files(self, arguments: dict[str, object]) -> dict[str, object]:
        request = ReadFilesRequest.from_mapping(arguments)
        self._assert_read_allowed("read_files")
        results = []
        for raw_path in request.paths:
            result = self._read_text_file(
                self._resolve_path(raw_path, allow_missing=False),
                start_line=request.start_line,
                end_line=request.end_line,
            )
            self._read_paths.append(result.path)
            results.append(result)
        self._record_activity(
            "read_files_batch",
            {"count": len(results), "paths": [item.path for item in results]},
            status="ok",
            category="read",
        )
        return ReadFilesResult(files=results).to_mapping()

    def _file_metadata(self, arguments: dict[str, object]) -> dict[str, object]:
        request = FileMetadataRequest.from_mapping(arguments)
        self._assert_read_allowed("file_metadata")
        path = self._resolve_path(request.path, allow_missing=False)
        result = self._metadata_for_path(path)
        self._record_activity(
            "file_metadata_lookup",
            {"path": result.path},
            status="ok",
            category="workspace",
        )
        return result.to_mapping()

    def _search_text(self, arguments: dict[str, object]) -> dict[str, object]:
        request = SearchTextRequest.from_mapping(arguments)
        self._assert_read_allowed("search_text")
        start_path = self._resolve_path(request.path, allow_missing=False)
        if not start_path.is_dir() and not start_path.is_file():
            raise FileNotFoundError(f"Path does not exist: {self._relative_path(start_path)}")

        query = request.query
        regex_mode = request.regex
        case_sensitive = request.case_sensitive
        extensions = self._normalized_extensions(request.extensions)
        max_results = self._int_argument(request.max_results, self.config.default_search_max_results, minimum=1)

        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = re.compile(query if regex_mode else re.escape(query), flags)

        matches: list[SearchMatch] = []
        candidate_paths = [start_path] if start_path.is_file() else self._iter_paths(start_path)
        for current_path in candidate_paths:
            if not current_path.is_file():
                continue
            if extensions and current_path.suffix.lower() not in extensions:
                continue
            try:
                text = self._safe_read_text(current_path)
            except ValueError:
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                match = pattern.search(line)
                if not match:
                    continue
                matches.append(
                    SearchMatch(
                        path=self._relative_path(current_path),
                        line_number=line_number,
                        column=match.start() + 1,
                        line=line,
                    )
                )
                if len(matches) >= max_results:
                    self._record_activity(
                        "search_text_scan",
                        {
                            "query": query,
                            "path": self._relative_path(start_path),
                            "matches": len(matches),
                        },
                        status="ok",
                        category="search",
                    )
                    return SearchTextResult(matches=matches, truncated=True).to_mapping()

        self._record_activity(
            "search_text_scan",
            {
                "query": query,
                "path": self._relative_path(start_path),
                "matches": len(matches),
            },
            status="ok",
            category="search",
        )
        return SearchTextResult(matches=matches, truncated=False).to_mapping()

    def _project_context(self, arguments: dict[str, object]) -> dict[str, object]:
        request = ProjectContextRequest.from_mapping(arguments)
        self._assert_read_allowed("project_context")
        path = self._resolve_path(request.path, allow_missing=False)
        context_root = path if path.is_dir() else path.parent
        top_level_names = sorted(child.name for child in context_root.iterdir() if not self._is_ignored(child))

        stack: list[str] = []
        package_managers: list[str] = []
        likely_commands: list[list[str]] = []
        configured_tools: list[str] = []
        requires_python: str | None = None

        pyproject_path = context_root / "pyproject.toml"
        if pyproject_path.exists():
            stack.append("python")
            project_data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
            project_section = project_data.get("project") or {}
            tool_section = project_data.get("tool") or {}
            requires_python = project_section.get("requires-python")
            configured_tools = sorted(tool_section)
            if (context_root / "uv.lock").exists():
                package_managers.append("uv")
                likely_commands.append(["uv", "run", "python", "-m", "unittest", "discover", "-s", "tests"])
            if (context_root / "poetry.lock").exists():
                package_managers.append("poetry")
                likely_commands.append(["poetry", "run", "python", "-m", "unittest", "discover", "-s", "tests"])

        if (context_root / "requirements.txt").exists():
            stack.append("python")
            if "pip" not in package_managers:
                package_managers.append("pip")
            likely_commands.append(["python", "-m", "unittest", "discover", "-s", "tests"])

        if (context_root / "package.json").exists():
            stack.append("node")
            package_managers.append(self._detect_node_manager(context_root))

        if (context_root / "tests").exists():
            likely_commands.append(["python", "-m", "unittest", "discover", "-s", "tests"])

        self._record_activity(
            "project_context_detected",
            {"path": self._relative_path(context_root), "stack": sorted(set(stack))},
            status="ok",
            category="workspace",
        )
        return ProjectContextResult(
            root=self._relative_path(context_root),
            stack=sorted(set(stack)),
            package_managers=package_managers,
            configured_tools=configured_tools,
            requires_python=requires_python,
            top_level_names=top_level_names,
            likely_commands=likely_commands,
        ).to_mapping()

    def _list_changes(self, arguments: dict[str, object]) -> dict[str, object]:
        ListChangesRequest.from_mapping(arguments)
        self._assert_read_allowed("list_changes")
        return ListChangesResult(
            read_paths=self._unique_preserving_order(self._read_paths),
            changed_paths=self._unique_preserving_order(self._changed_paths),
            executed_commands=list(self._executed_commands),
            activity_count=self._journal.total_entries(),
            journal=self._journal.summary(),
        ).to_mapping()

    def _activity(self, arguments: dict[str, object]) -> dict[str, object]:
        request = ActivityLogRequest.from_mapping(arguments)
        self._assert_read_allowed("activity_log")
        limit = self._int_argument(request.limit, 50, minimum=1)
        return ActivityLogResult(
            entries=self._journal.recent(limit),
            total_entries=self._journal.total_entries(),
            journal=self._journal.summary(),
        ).to_mapping()
