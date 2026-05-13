from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lord_of_the_machines.agent_tools.kanban_board.config import KanbanBoardToolConfig
from lord_of_the_machines.agent_tools.kanban_board.contracts import (
    AppendTaskNoteRequest,
    ClaimNextTaskRequest,
    CreateTaskRequest,
    GetTaskRequest,
    KanbanTaskMeta,
    ListColumnsRequest,
    ListTasksRequest,
    MoveTaskRequest,
    TaskHistoryEntry,
)
from lord_of_the_machines.agent_tools.kanban_board.definition import build_definition
from lord_of_the_machines.llm.base_agent import BaseAgent
from lord_of_the_machines.llm.tool_definitions import ToolDefinition
from lord_of_the_machines.llm.tools import ToolHandler


SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}$")
TASK_ID_RE = re.compile(r"^K-(\d{6,})$")
FRONTMATTER_DELIMITER = "---"


class KanbanBoardTool:
    TOOL_NAME = "kanban_board"

    def __init__(self, root_path: str | Path, *, config: KanbanBoardToolConfig | None = None) -> None:
        self.config = config or KanbanBoardToolConfig(root_path=Path(root_path))

    def install(self, agent: BaseAgent) -> None:
        agent.add_tool(self.definition(), handlers=self.handlers())

    def definition(self) -> ToolDefinition:
        return build_definition(self.TOOL_NAME)

    def handlers(self) -> dict[str, ToolHandler]:
        return {
            "list_columns": self._list_columns,
            "list_tasks": self._list_tasks,
            "create_task": self._create_task,
            "get_task": self._get_task,
            "claim_next_task": self._claim_next_task,
            "move_task": self._move_task,
            "append_task_note": self._append_task_note,
        }

    def _list_columns(self, arguments: dict[str, Any]) -> dict[str, Any]:
        ListColumnsRequest.from_mapping(arguments)
        columns = []
        for column in self.config.columns:
            column_path = self._column_path(column)
            task_paths = self._task_paths_in_column(column)
            columns.append(
                {
                    "column": column,
                    "path": self._relative_to_root(column_path),
                    "task_count": len(task_paths),
                }
            )
        return {"root_path": str(self.config.root_path), "columns": columns}

    def _list_tasks(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = ListTasksRequest.from_mapping(arguments)
        if request.column:
            column = self._safe_column_name(request.column)
            task_paths = self._task_paths_in_column(column)
            tasks = [self._load_task_payload(path, include_body=request.include_body) for path in task_paths]
            return {"columns": [{"column": column, "tasks": tasks}]}

        columns_payload = []
        for column in self.config.columns:
            task_paths = self._task_paths_in_column(column)
            tasks = [self._load_task_payload(path, include_body=request.include_body) for path in task_paths]
            columns_payload.append({"column": column, "tasks": tasks})
        return {"columns": columns_payload}

    def _create_task(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = CreateTaskRequest.from_mapping(arguments)
        column = self._safe_column_name(request.column)
        column_path = self._column_path(column)

        task_id = self._safe_task_id(request.task_id or self._generate_task_id())
        file_name = self._task_file_name(task_id, request.title)
        task_path = column_path / file_name
        if task_path.exists() and not request.overwrite:
            raise FileExistsError(f"Task already exists: {self._relative_to_root(task_path)}")
        if not task_path.exists():
            self._assert_column_capacity(column)

        now = self._utc_now()
        meta = KanbanTaskMeta(
            task_id=task_id,
            title=request.title,
            status=request.status.strip().lower(),
            owner=request.owner,
            created_at=now,
            updated_at=now,
            metadata=dict(request.metadata),
            history=[
                TaskHistoryEntry(
                    at=now,
                    action="created",
                    by=request.owner,
                    details={"column": column},
                )
            ],
        )
        body = request.description.strip()
        if not body:
            body = f"# {request.title}\n\nTask created in `{column}`."

        self._save_task_file(task_path, meta, body)
        return {
            "created": True,
            "task": self._task_payload(meta, task_path, body=body, include_body=True),
        }

    def _get_task(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = GetTaskRequest.from_mapping(arguments)
        task_path = self._find_task_path(task_id=request.task_id, column=request.column)
        if task_path is None:
            raise FileNotFoundError(f"Task not found: {request.task_id}")
        return {"task": self._load_task_payload(task_path, include_body=request.include_body)}

    def _claim_next_task(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = ClaimNextTaskRequest.from_mapping(arguments)
        column = self._safe_column_name(request.column)
        allowed_statuses = {status.strip().lower() for status in request.statuses}
        claimed_status = request.claimed_status.strip().lower()
        for task_path in self._task_paths_in_column(column):
            meta, body = self._load_task_file(task_path)
            if meta.status not in allowed_statuses:
                continue
            if meta.owner:
                continue
            now = self._utc_now()
            previous_status = meta.status
            meta.owner = request.agent_id
            meta.status = claimed_status
            meta.updated_at = now
            meta.history.append(
                TaskHistoryEntry(
                    at=now,
                    action="claimed",
                    by=request.agent_id,
                    details={
                        "column": column,
                        "previous_status": previous_status,
                        "status": claimed_status,
                    },
                )
            )
            self._save_task_file(task_path, meta, body)
            return {
                "claimed": True,
                "task": self._task_payload(meta, task_path, body=body, include_body=True),
            }
        return {"claimed": False, "task": None}

    def _move_task(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = MoveTaskRequest.from_mapping(arguments)
        to_column = self._safe_column_name(request.to_column)
        from_column = request.from_column.strip() if isinstance(request.from_column, str) else None
        task_path = self._find_task_path(task_id=request.task_id, column=from_column)
        if task_path is None:
            raise FileNotFoundError(f"Task not found: {request.task_id}")

        meta, body = self._load_task_file(task_path)
        source_column = task_path.parent.name
        destination_path = self._column_path(to_column) / task_path.name
        if destination_path.exists() and destination_path != task_path:
            raise FileExistsError(f"Destination already has a task file: {self._relative_to_root(destination_path)}")

        now = self._utc_now()
        if request.status:
            meta.status = request.status.strip().lower()
        meta.updated_at = now
        meta.history.append(
            TaskHistoryEntry(
                at=now,
                action="moved",
                by=request.actor,
                details={
                    "from_column": source_column,
                    "to_column": to_column,
                    "status": meta.status,
                },
            )
        )
        if request.note:
            body = self._append_activity_markdown(body, at=now, actor=request.actor, note=request.note)

        if destination_path == task_path:
            self._save_task_file(task_path, meta, body)
            final_path = task_path
        else:
            self._save_task_file(destination_path, meta, body)
            task_path.unlink()
            final_path = destination_path
        return {"moved": True, "task": self._task_payload(meta, final_path, body=body, include_body=True)}

    def _append_task_note(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = AppendTaskNoteRequest.from_mapping(arguments)
        task_path = self._find_task_path(task_id=request.task_id, column=request.column)
        if task_path is None:
            raise FileNotFoundError(f"Task not found: {request.task_id}")

        meta, body = self._load_task_file(task_path)
        now = self._utc_now()
        body = self._append_activity_markdown(body, at=now, actor=request.actor, note=request.note)
        meta.updated_at = now
        meta.history.append(
            TaskHistoryEntry(
                at=now,
                action="note",
                by=request.actor,
                details={"column": task_path.parent.name},
            )
        )
        self._save_task_file(task_path, meta, body)
        return {"updated": True, "task": self._task_payload(meta, task_path, body=body, include_body=True)}

    def _find_task_path(self, *, task_id: str, column: str | None = None) -> Path | None:
        safe_task_id = self._safe_task_id(task_id)
        if column:
            safe_column = self._safe_column_name(column)
            for path in self._task_paths_in_column(safe_column):
                if path.name.startswith(f"{safe_task_id}__"):
                    return path
            return None

        matches = []
        for candidate_column in self.config.columns:
            for path in self._task_paths_in_column(candidate_column):
                if path.name.startswith(f"{safe_task_id}__"):
                    matches.append(path)
        if not matches:
            return None
        if len(matches) > 1:
            raise ValueError(f"Ambiguous task id '{safe_task_id}': found in multiple columns.")
        return matches[0]

    def _load_task_payload(self, path: Path, *, include_body: bool) -> dict[str, Any]:
        meta, body = self._load_task_file(path)
        return self._task_payload(meta, path, body=body, include_body=include_body)

    def _task_payload(
        self,
        meta: KanbanTaskMeta,
        path: Path,
        *,
        body: str,
        include_body: bool,
    ) -> dict[str, Any]:
        payload = {
            "task_id": meta.task_id,
            "title": meta.title,
            "status": meta.status,
            "owner": meta.owner,
            "column": path.parent.name,
            "path": self._relative_to_root(path),
            "file_name": path.name,
            "created_at": meta.created_at,
            "updated_at": meta.updated_at,
            "metadata": dict(meta.metadata),
            "history": [entry.to_mapping() for entry in meta.history],
        }
        if include_body:
            payload["body"] = body
        return payload

    def _load_task_file(self, path: Path) -> tuple[KanbanTaskMeta, str]:
        raw = path.read_text(encoding="utf-8")
        lines = raw.splitlines()
        if len(lines) < 3 or lines[0].strip() != FRONTMATTER_DELIMITER:
            raise ValueError(f"Invalid task markdown frontmatter in {self._relative_to_root(path)}")
        delimiter_index = -1
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == FRONTMATTER_DELIMITER:
                delimiter_index = index
                break
        if delimiter_index < 0:
            raise ValueError(f"Missing closing frontmatter delimiter in {self._relative_to_root(path)}")
        metadata_text = "\n".join(lines[1:delimiter_index]).strip()
        if not metadata_text:
            raise ValueError(f"Task metadata is empty in {self._relative_to_root(path)}")
        metadata = KanbanTaskMeta.from_mapping(json.loads(metadata_text))
        body = "\n".join(lines[delimiter_index + 1 :])
        return metadata, body

    def _save_task_file(self, path: Path, meta: KanbanTaskMeta, body: str) -> None:
        frontmatter = json.dumps(meta.to_mapping(), ensure_ascii=False, indent=2)
        normalized_body = body.rstrip()
        content = f"{FRONTMATTER_DELIMITER}\n{frontmatter}\n{FRONTMATTER_DELIMITER}\n{normalized_body}\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _task_paths_in_column(self, column: str) -> list[Path]:
        column_path = self._column_path(column)
        return sorted(
            [
                path
                for path in column_path.iterdir()
                if path.is_file() and path.name.endswith(self.config.task_extension)
            ],
            key=lambda path: path.name.lower(),
        )

    def _column_path(self, column: str) -> Path:
        safe_column = self._safe_column_name(column)
        path = (self.config.root_path / safe_column).resolve()
        if not self._is_within_root(path):
            raise ValueError("Resolved column path is outside configured root.")
        return path

    def _safe_column_name(self, value: str) -> str:
        name = value.strip()
        if name not in self.config.columns:
            raise ValueError(f"Unknown column '{value}'. Allowed columns: {', '.join(self.config.columns)}.")
        if not SAFE_NAME_RE.fullmatch(name):
            raise ValueError("column name contains unsupported characters.")
        return name

    def _safe_task_id(self, value: str) -> str:
        task_id = value.strip().upper()
        if not TASK_ID_RE.fullmatch(task_id):
            raise ValueError("task_id must match K-<number>, for example K-000001.")
        return task_id

    def _task_file_name(self, task_id: str, title: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.strip().lower()).strip("-")
        slug = slug[:80] or "task"
        return f"{task_id}__{slug}{self.config.task_extension}"

    def _generate_task_id(self) -> str:
        max_seen = 0
        for column in self.config.columns:
            for path in self._task_paths_in_column(column):
                if "__" not in path.name:
                    continue
                candidate_id = path.name.split("__", 1)[0].upper()
                match = TASK_ID_RE.fullmatch(candidate_id)
                if match:
                    max_seen = max(max_seen, int(match.group(1)))
        return f"K-{max_seen + 1:06d}"

    def _assert_column_capacity(self, column: str) -> None:
        if self.config.max_tasks_per_column is None:
            return
        if len(self._task_paths_in_column(column)) >= self.config.max_tasks_per_column:
            raise ValueError(
                f"Column '{column}' reached max_tasks_per_column={self.config.max_tasks_per_column}."
            )

    def _append_activity_markdown(self, body: str, *, at: str, actor: str | None, note: str) -> str:
        actor_text = actor or "unknown"
        line = f"- [{at}] ({actor_text}) {note}"
        heading = "## Activity Log"
        content = body.rstrip()
        if not content:
            return f"{heading}\n{line}\n"
        if heading in content:
            return f"{content}\n{line}\n"
        return f"{content}\n\n{heading}\n{line}\n"

    def _is_within_root(self, path: Path) -> bool:
        try:
            path.relative_to(self.config.root_path)
            return True
        except ValueError:
            return False

    def _relative_to_root(self, path: Path) -> str:
        return path.relative_to(self.config.root_path).as_posix()

    def _utc_now(self) -> str:
        return datetime.now(tz=timezone.utc).isoformat()
