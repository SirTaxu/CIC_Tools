from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

LogEventSeverity = Literal["info", "warning", "error"]
ArchiveActionStatus = Literal["planned", "archived", "skipped"]


@dataclass(frozen=True)
class LogFileRecord:
    """Metadata for one file inside the logs folder."""

    path: Path
    relative_path: Path
    size_bytes: int
    modified_timestamp: float
    modified_iso: str
    category: str
    extension: str
    is_active_file: bool


@dataclass(frozen=True)
class LogInventoryReport:
    """Summary of the logs folder."""

    log_dir: Path
    records: tuple[LogFileRecord, ...]
    total_size_bytes: int
    total_files: int
    size_by_category: dict[str, int]
    count_by_category: dict[str, int]


@dataclass(frozen=True)
class LogArchiveAction:
    """One file selected for archive or skipped by policy."""

    source_path: Path
    relative_path: Path
    size_bytes: int
    category: str
    status: ArchiveActionStatus
    reason: str


@dataclass(frozen=True)
class LogArchivePlan:
    """Archive plan or apply result."""

    apply: bool
    older_than_days: int
    archive_path: Path
    actions: tuple[LogArchiveAction, ...]

    @property
    def selected_actions(self) -> tuple[LogArchiveAction, ...]:
        return tuple(action for action in self.actions if action.status in {"planned", "archived"})

    @property
    def selected_count(self) -> int:
        return len(self.selected_actions)

    @property
    def selected_size_bytes(self) -> int:
        return sum(action.size_bytes for action in self.selected_actions)


@dataclass(frozen=True)
class LogErrorEvent:
    """One important log event extracted from log.txt."""

    line_number: int
    timestamp: str | None
    severity: LogEventSeverity
    code: str
    message: str
    raw_line: str
    context_before: tuple[str, ...] = ()
    context_after: tuple[str, ...] = ()


@dataclass(frozen=True)
class LogErrorReport:
    """Important events extracted from one log file."""

    source_path: Path
    events: tuple[LogErrorEvent, ...]
    scanned_lines: int

    @property
    def error_count(self) -> int:
        return sum(1 for event in self.events if event.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for event in self.events if event.severity == "warning")

    @property
    def info_count(self) -> int:
        return sum(1 for event in self.events if event.severity == "info")


@dataclass(frozen=True)
class MainLogTrimPlan:
    """Dry-run or applied trim plan for logs/log.txt."""

    apply: bool
    source_path: Path
    archive_path: Path
    original_line_count: int
    archived_line_count: int
    kept_line_count: int
    mode: str
    cutoff_timestamp: str | None = None
    keep_last_lines: int | None = None
