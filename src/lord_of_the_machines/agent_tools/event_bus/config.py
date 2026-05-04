from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_EVENTS_FILE_NAME = "events.jsonl"
DEFAULT_MAX_CONSUME_LIMIT = 100


@dataclass(slots=True)
class EventBusToolConfig:
    root_path: Path
    events_file_name: str = DEFAULT_EVENTS_FILE_NAME
    max_consume_limit: int = DEFAULT_MAX_CONSUME_LIMIT

    def __post_init__(self) -> None:
        self.root_path = Path(self.root_path).resolve()
        self.root_path.mkdir(parents=True, exist_ok=True)
        if not self.root_path.is_dir():
            raise NotADirectoryError(f"Event bus root must be a directory: {self.root_path}")
        if not self.events_file_name.endswith(".jsonl"):
            raise ValueError("events_file_name must end with .jsonl")
        if self.max_consume_limit < 1:
            raise ValueError("max_consume_limit must be >= 1.")

