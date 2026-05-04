from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lord_of_the_machines.agent_tools.software_development_environment.contracts import (
    ActivityEntry,
    JournalSummary,
)
from lord_of_the_machines.runtime.logging import to_loggable
from lord_of_the_machines.runtime.paths import LOG_DIR


@dataclass(slots=True)
class ToolActivityJournalConfig:
    enabled: bool = True
    log_dir: Path | None = None
    file_prefix: str = "tool-activity"
    max_entries: int = 500
    text_preview_chars: int = 240


class ToolActivityJournal:
    def __init__(
        self,
        *,
        tool_name: str,
        workspace_root: Path,
        config: ToolActivityJournalConfig | None = None,
    ) -> None:
        self._tool_name = tool_name
        self._workspace_root = workspace_root
        self._config = config or ToolActivityJournalConfig()
        self._entries: list[ActivityEntry] = []
        self._sequence = 0
        self._persist_error: str | None = None
        self._session_id = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        self._journal_path: Path | None = None

        if self._config.enabled:
            log_dir = self._config.log_dir or LOG_DIR
            log_dir.mkdir(parents=True, exist_ok=True)
            self._journal_path = log_dir / f"{self._config.file_prefix}-{self._session_id}.jsonl"

    @property
    def journal_path(self) -> Path | None:
        return self._journal_path

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def persist_error(self) -> str | None:
        return self._persist_error

    def record(
        self,
        *,
        action: str,
        details: dict[str, Any] | None = None,
        status: str = "info",
        category: str = "activity",
    ) -> ActivityEntry:
        self._sequence += 1
        entry = ActivityEntry(
            event_id=f"{self._session_id}-{self._sequence:05d}",
            timestamp=datetime.now(tz=timezone.utc).isoformat(),
            session_id=self._session_id,
            tool=self._tool_name,
            workspace_root=str(self._workspace_root),
            category=category,
            action=action,
            status=status,
            details=self._summarize(to_loggable(details or {})),
        )
        self._entries.append(entry)
        if len(self._entries) > self._config.max_entries:
            overflow = len(self._entries) - self._config.max_entries
            del self._entries[:overflow]
        self._persist_entry(entry)
        return entry

    def recent(self, limit: int) -> list[ActivityEntry]:
        if limit <= 0:
            return []
        return self._entries[-limit:]

    def total_entries(self) -> int:
        return len(self._entries)

    def summary(self) -> JournalSummary:
        return JournalSummary(
            session_id=self._session_id,
            journal_path=str(self._journal_path) if self._journal_path is not None else None,
            entries_in_memory=len(self._entries),
            persist_error=self._persist_error,
        )

    def _persist_entry(self, entry: ActivityEntry) -> None:
        if self._journal_path is None:
            return
        try:
            with self._journal_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(entry.to_mapping(), ensure_ascii=False))
                handle.write("\n")
        except OSError as exc:
            self._persist_error = str(exc)

    def _summarize(self, value: Any) -> Any:
        if isinstance(value, str):
            return self._truncate(value)
        if isinstance(value, dict):
            return {str(key): self._summarize(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._summarize(item) for item in value]
        return value

    def _truncate(self, value: str) -> str:
        if len(value) <= self._config.text_preview_chars:
            return value
        limit = max(0, self._config.text_preview_chars - 3)
        return value[:limit].rstrip() + "..."
