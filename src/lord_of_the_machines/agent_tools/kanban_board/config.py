from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_COLUMNS = (
    "01-product-direction",
    "02-product-requirements",
    "03-technical-design",
    "04-development-plan",
    "05-implementation",
    "90-done",
    "99-blocked",
)
DEFAULT_TASK_EXTENSION = ".md"
DEFAULT_MAX_TASKS_PER_COLUMN = 10_000


@dataclass(slots=True)
class KanbanBoardToolConfig:
    root_path: Path
    columns: tuple[str, ...] = DEFAULT_COLUMNS
    task_extension: str = DEFAULT_TASK_EXTENSION
    max_tasks_per_column: int | None = DEFAULT_MAX_TASKS_PER_COLUMN

    def __post_init__(self) -> None:
        self.root_path = Path(self.root_path).resolve()
        self.root_path.mkdir(parents=True, exist_ok=True)
        if not self.root_path.is_dir():
            raise NotADirectoryError(f"Kanban board root must be a directory: {self.root_path}")
        if not self.columns:
            raise ValueError("columns cannot be empty.")
        if not self.task_extension.startswith("."):
            raise ValueError("task_extension must start with '.'.")
        if self.max_tasks_per_column is not None and self.max_tasks_per_column < 1:
            raise ValueError("max_tasks_per_column must be >= 1 when set.")
        for column in self.columns:
            if not isinstance(column, str) or not column.strip():
                raise ValueError("each column name must be a non-empty string.")
            (self.root_path / column).mkdir(parents=True, exist_ok=True)
