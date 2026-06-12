from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path

from crafting_bot import paths
from crafting_bot.domain.log_maintenance import LogFileRecord, LogInventoryReport


class LogInventoryService:
    """Scans the logs folder and summarizes file sizes.

    This service only reads filesystem metadata. It never deletes or moves files.
    """

    def __init__(self, log_dir: Path = paths.LOG_DIR) -> None:
        self.log_dir = log_dir

    def collect(self, *, include_archives: bool = False) -> LogInventoryReport:
        records: list[LogFileRecord] = []

        if not self.log_dir.exists():
            return LogInventoryReport(
                log_dir=self.log_dir,
                records=tuple(),
                total_size_bytes=0,
                total_files=0,
                size_by_category={},
                count_by_category={},
            )

        for path in sorted(self.log_dir.rglob("*")):
            if not path.is_file():
                continue

            relative = path.relative_to(self.log_dir)
            if not include_archives and relative.parts and relative.parts[0].lower() == "archive":
                continue

            try:
                stat = path.stat()
            except OSError:
                continue

            category = categorize_log_file(relative)
            records.append(
                LogFileRecord(
                    path=path,
                    relative_path=relative,
                    size_bytes=stat.st_size,
                    modified_timestamp=stat.st_mtime,
                    modified_iso=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                    category=category,
                    extension=path.suffix.lower() or "<none>",
                    is_active_file=is_active_log_file(relative),
                )
            )

        size_by_category: dict[str, int] = defaultdict(int)
        count_by_category: dict[str, int] = defaultdict(int)

        for record in records:
            size_by_category[record.category] += record.size_bytes
            count_by_category[record.category] += 1

        return LogInventoryReport(
            log_dir=self.log_dir,
            records=tuple(records),
            total_size_bytes=sum(record.size_bytes for record in records),
            total_files=len(records),
            size_by_category=dict(sorted(size_by_category.items())),
            count_by_category=dict(sorted(count_by_category.items())),
        )


def categorize_log_file(relative_path: Path) -> str:
    parts = relative_path.parts
    if not parts:
        return "root"

    first = parts[0].lower()
    name = relative_path.name.lower()

    if first == "debug_crops":
        return "debug_crops"
    if first == "recovery":
        return "recovery"
    if first == "template_health":
        return "template_health"
    if first == "error_reports":
        return "error_reports"
    if first == "archive":
        return "archive"
    if name == "log.txt":
        return "main_log"
    if name.startswith("latest_"):
        return "latest_snapshots"
    if name.endswith("_before.png") or name.endswith("_after.png"):
        return "cycle_reports"
    if name.endswith("_report.txt"):
        return "cycle_reports"

    return "other"


def is_active_log_file(relative_path: Path) -> bool:
    name = relative_path.name.lower()
    if name == "log.txt":
        return True
    if name.startswith("latest_"):
        return True
    return False


def format_bytes(size: int) -> str:
    value = float(size)
    for suffix in ("B", "KB", "MB", "GB"):
        if value < 1024.0:
            if suffix == "B":
                return f"{int(value)} {suffix}"
            return f"{value:.1f} {suffix}"
        value /= 1024.0
    return f"{value:.1f} TB"
