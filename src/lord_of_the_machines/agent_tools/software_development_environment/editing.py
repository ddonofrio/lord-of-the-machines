from __future__ import annotations

import re
import shutil

from lord_of_the_machines.agent_tools.software_development_environment.contracts import (
    AppendFileRequest,
    DeletePathRequest,
    DeletePathResult,
    InsertTextRequest,
    LineRange,
    MovePathRequest,
    MovePathResult,
    ReplaceLinesRequest,
    ReplaceTextRequest,
    WriteFileRequest,
)


class EditingOperationsMixin:
    def _write_file(self, arguments: dict[str, object]) -> dict[str, object]:
        request = WriteFileRequest.from_mapping(arguments)
        self._assert_write_allowed("write_file")
        path = self._resolve_path(request.path, allow_missing=True)
        self._assert_writable_path(path, allow_protected=request.allow_protected_path)
        if request.create_directories:
            path.parent.mkdir(parents=True, exist_ok=True)
        if request.if_missing_only and path.exists():
            raise FileExistsError(f"File already exists: {self._relative_path(path)}")

        before_text, before_sha256 = self._read_existing_text(path)
        self._assert_expected_sha256(path, request.expected_sha256, current_sha256=before_sha256)

        path.write_text(request.content, encoding="utf-8", newline="")
        after_text = path.read_text(encoding="utf-8")
        result = self._change_result(path, before_text, after_text, "write_file")
        self._record_change(path, "write_file")
        return result.to_mapping()

    def _append_file(self, arguments: dict[str, object]) -> dict[str, object]:
        request = AppendFileRequest.from_mapping(arguments)
        self._assert_write_allowed("append_file")
        path = self._resolve_path(request.path, allow_missing=True)
        self._assert_writable_path(path, allow_protected=request.allow_protected_path)
        if request.create_directories:
            path.parent.mkdir(parents=True, exist_ok=True)

        before_text, before_sha256 = self._read_existing_text(path)
        self._assert_expected_sha256(path, request.expected_sha256, current_sha256=before_sha256)

        with path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(request.content)
        after_text = path.read_text(encoding="utf-8")
        result = self._change_result(path, before_text, after_text, "append_file")
        self._record_change(path, "append_file")
        return result.to_mapping()

    def _replace_text(self, arguments: dict[str, object]) -> dict[str, object]:
        request = ReplaceTextRequest.from_mapping(arguments)
        self._assert_write_allowed("replace_text")
        path = self._resolve_path(request.path, allow_missing=False)
        self._assert_writable_path(path, allow_protected=request.allow_protected_path)
        before_text, before_sha256 = self._read_existing_text(path, require_exists=True)
        self._assert_expected_sha256(path, request.expected_sha256, current_sha256=before_sha256)

        old_text = request.old_text
        new_text = request.new_text
        occurrences = before_text.count(old_text)
        expected_occurrences = self._int_argument(request.expected_occurrences, 1, minimum=0)
        if occurrences != expected_occurrences:
            raise ValueError(
                f"Expected {expected_occurrences} occurrence(s) of the target text in {self._relative_path(path)}, found {occurrences}."
            )

        after_text = before_text.replace(old_text, new_text)
        path.write_text(after_text, encoding="utf-8", newline="")
        result = self._change_result(path, before_text, after_text, "replace_text")
        result.replacements = occurrences
        self._record_change(path, "replace_text")
        return result.to_mapping()

    def _replace_lines(self, arguments: dict[str, object]) -> dict[str, object]:
        request = ReplaceLinesRequest.from_mapping(arguments)
        self._assert_write_allowed("replace_lines")
        path = self._resolve_path(request.path, allow_missing=False)
        self._assert_writable_path(path, allow_protected=request.allow_protected_path)
        before_text, before_sha256 = self._read_existing_text(path, require_exists=True)
        self._assert_expected_sha256(path, request.expected_sha256, current_sha256=before_sha256)

        lines = before_text.splitlines(keepends=True)
        start_line = self._int_argument(request.start_line, minimum=1)
        end_line = self._int_argument(request.end_line, minimum=start_line)
        if end_line > len(lines):
            raise ValueError(f"Line range {start_line}-{end_line} exceeds file length {len(lines)}.")

        replacement = request.replacement
        replacement_lines = replacement.splitlines(keepends=True)
        after_lines = [*lines[: start_line - 1], *replacement_lines, *lines[end_line:]]
        after_text = "".join(after_lines)
        path.write_text(after_text, encoding="utf-8", newline="")
        result = self._change_result(path, before_text, after_text, "replace_lines")
        result.replaced_line_range = LineRange(start_line=start_line, end_line=end_line)
        self._record_change(path, "replace_lines")
        return result.to_mapping()

    def _insert_text(self, arguments: dict[str, object]) -> dict[str, object]:
        request = InsertTextRequest.from_mapping(arguments)
        self._assert_write_allowed("insert_text")
        path = self._resolve_path(request.path, allow_missing=False)
        self._assert_writable_path(path, allow_protected=request.allow_protected_path)
        before_text, before_sha256 = self._read_existing_text(path, require_exists=True)
        self._assert_expected_sha256(path, request.expected_sha256, current_sha256=before_sha256)

        anchor = request.anchor
        position = request.position.lower()
        if position not in {"before", "after"}:
            raise ValueError("position must be 'before' or 'after'.")

        occurrence = self._int_argument(request.occurrence, 1, minimum=1)
        matches = [match.start() for match in re.finditer(re.escape(anchor), before_text)]
        if not matches:
            raise ValueError(f"Anchor text not found in {self._relative_path(path)}.")
        if occurrence > len(matches):
            raise ValueError(f"Requested occurrence {occurrence} but found only {len(matches)} occurrence(s).")

        anchor_start = matches[occurrence - 1]
        anchor_end = anchor_start + len(anchor)
        insert_at = anchor_start if position == "before" else anchor_end
        after_text = before_text[:insert_at] + request.text + before_text[insert_at:]
        path.write_text(after_text, encoding="utf-8", newline="")
        result = self._change_result(path, before_text, after_text, "insert_text")
        result.anchor_occurrence = occurrence
        result.position = position
        self._record_change(path, "insert_text")
        return result.to_mapping()

    def _move_path(self, arguments: dict[str, object]) -> dict[str, object]:
        request = MovePathRequest.from_mapping(arguments)
        source_path = self._resolve_path(request.source_path, allow_missing=False)
        destination_path = self._resolve_path(request.destination_path, allow_missing=True)
        allow_protected = request.allow_protected_path
        self._assert_writable_path(source_path, allow_protected=allow_protected)
        self._assert_writable_path(destination_path, allow_protected=allow_protected)

        dry_run = request.dry_run
        confirm = request.confirm
        overwrite = request.overwrite
        source_count = self._path_entry_count(source_path)
        self._assert_move_allowed(dry_run=dry_run, entries_affected=source_count)
        result = MovePathResult(
            action="move_path",
            source_path=self._relative_path(source_path),
            destination_path=self._relative_path(destination_path),
            dry_run=dry_run,
            entries_affected=source_count,
        )
        if destination_path.exists() and not overwrite:
            raise FileExistsError(f"Destination already exists: {self._relative_path(destination_path)}")
        if dry_run:
            self._record_activity("move_path_dry_run", result.to_mapping(), status="ok", category="mutation")
            return result.to_mapping()
        if not confirm:
            raise ValueError("move_path requires confirm=true when dry_run=false.")

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        if destination_path.exists() and overwrite:
            if destination_path.is_dir():
                shutil.rmtree(destination_path)
            else:
                destination_path.unlink()
        shutil.move(str(source_path), str(destination_path))
        self._record_change(destination_path, "move_path")
        result.ok = True
        return result.to_mapping()

    def _delete_path(self, arguments: dict[str, object]) -> dict[str, object]:
        request = DeletePathRequest.from_mapping(arguments)
        path = self._resolve_path(request.path, allow_missing=False)
        allow_protected = request.allow_protected_path
        self._assert_writable_path(path, allow_protected=allow_protected)
        recursive = request.recursive
        dry_run = request.dry_run
        confirm = request.confirm

        entry_count = self._path_entry_count(path)
        self._assert_delete_allowed(dry_run=dry_run, entries_affected=entry_count)
        result = DeletePathResult(
            action="delete_path",
            path=self._relative_path(path),
            recursive=recursive,
            dry_run=dry_run,
            entries_affected=entry_count,
        )
        if path.is_dir() and any(path.iterdir()) and not recursive:
            raise ValueError("delete_path requires recursive=true for non-empty directories.")
        if path.is_file():
            _, current_sha256 = self._read_existing_text(path)
            self._assert_expected_sha256(path, request.expected_sha256, current_sha256=current_sha256)
        if dry_run:
            self._record_activity("delete_path_dry_run", result.to_mapping(), status="ok", category="mutation")
            return result.to_mapping()
        if not confirm:
            raise ValueError("delete_path requires confirm=true when dry_run=false.")

        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        self._record_change(path, "delete_path")
        result.ok = True
        return result.to_mapping()
