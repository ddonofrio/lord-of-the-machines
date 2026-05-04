from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DEFAULT_ALLOWED_STATUSES = (
    "draft",
    "published",
    "approved",
    "superseded",
    "archived",
)


@dataclass(slots=True)
class ArtifactRegistryToolConfig:
    root_path: Path
    allowed_statuses: tuple[str, ...] = DEFAULT_ALLOWED_STATUSES

    def __post_init__(self) -> None:
        self.root_path = Path(self.root_path).resolve()
        self.root_path.mkdir(parents=True, exist_ok=True)
        if not self.root_path.is_dir():
            raise NotADirectoryError(f"Artifact registry root must be a directory: {self.root_path}")
        if not self.allowed_statuses:
            raise ValueError("allowed_statuses cannot be empty.")

