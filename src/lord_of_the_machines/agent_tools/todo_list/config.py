from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_LIST_EXTENSION = ".todo.json"
DEFAULT_MAX_LISTS_PER_AGENT = 200
DEFAULT_MAX_ITEMS_PER_LIST = 1_000


@dataclass(slots=True)
class TodoListToolConfig:
    root_path: Path
    list_extension: str = DEFAULT_LIST_EXTENSION
    max_lists_per_agent: int | None = DEFAULT_MAX_LISTS_PER_AGENT
    max_items_per_list: int | None = DEFAULT_MAX_ITEMS_PER_LIST

    def __post_init__(self) -> None:
        self.root_path = Path(self.root_path).resolve()
        self.root_path.mkdir(parents=True, exist_ok=True)
        if not self.root_path.is_dir():
            raise NotADirectoryError(f"Todo list root must be a directory: {self.root_path}")
        if not self.list_extension.startswith("."):
            raise ValueError("list_extension must start with '.'")
        if self.max_lists_per_agent is not None and self.max_lists_per_agent < 1:
            raise ValueError("max_lists_per_agent must be >= 1 when set.")
        if self.max_items_per_list is not None and self.max_items_per_list < 1:
            raise ValueError("max_items_per_list must be >= 1 when set.")

