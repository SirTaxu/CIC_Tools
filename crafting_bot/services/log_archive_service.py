from __future__ import annotations

import json
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from crafting_bot import paths
from crafting_bot.domain.log_maintenance import LogArchiveAction, LogArchivePlan
from crafting_bot.services.log_inventory_service import LogInventoryService


class LogArchiveService:
    """Builds and applies safe log archive plans.

    Dry-run is the default at the CLI level. When apply=True, selected files are
    written to a zip archive and removed from logs only after the zip entry is
    successfully written.
    """

    def __init__(
        self,
        *,
        log_dir: Path = paths.LOG_DIR,
        archive_dir: Path = paths.LOG_DIR / "archive",
        inventory_service: LogInventoryService | None = None,
    ) -> None:
        self.log_dir = log_dir
        self.archive_dir = archive_dir
        self.inventory_service = inventory_service or LogInventoryService(log_dir)

    def build_plan(
        self,
        *,
        older_than_days: int,
        include_active_files: bool = False,
        categories: set[str] | None = None,
        apply: bool = False,
    ) -> LogArchivePlan:
        if older_than_days < 0:
            raise ValueError("older_than_days must be >= 0")

        report = self.inventory_service.collect(include_archives=False)
        cutoff = datetime.now() - timedelta(days=older_than_days)
        cutoff_timestamp = cutoff.timestamp()

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_path = self.archive_dir / f"{stamp}_logs_older_than_{older_than_days}_days.zip"

        actions: list[LogArchiveAction] = []

        for record in report.records:
            if categories and record.category not in categories:
                continue

            if record.modified_timestamp > cutoff_timestamp:
                actions.append(
                    LogArchiveAction(
                        source_path=record.path,
                        relative_path=record.relative_path,
                        size_bytes=record.size_bytes,
                        category=record.category,
                        status="skipped",
                        reason="File is newer than the cutoff.",
                    )
                )
                continue

            if record.is_active_file and not include_active_files:
                actions.append(
                    LogArchiveAction(
                        source_path=record.path,
                        relative_path=record.relative_path,
                        size_bytes=record.size_bytes,
                        category=record.category,
                        status="skipped",
                        reason="Active/latest files are kept unless --include-active-files is used.",
                    )
                )
                continue

            actions.append(
                LogArchiveAction(
                    source_path=record.path,
                    relative_path=record.relative_path,
                    size_bytes=record.size_bytes,
                    category=record.category,
                    status="planned",
                    reason="Selected for archive.",
                )
            )

        plan = LogArchivePlan(
            apply=False,
            older_than_days=older_than_days,
            archive_path=archive_path,
            actions=tuple(actions),
        )

        if apply:
            return self.apply_plan(plan)

        return plan

    def apply_plan(self, plan: LogArchivePlan) -> LogArchivePlan:
        selected = [action for action in plan.actions if action.status == "planned"]
        if not selected:
            return LogArchivePlan(
                apply=True,
                older_than_days=plan.older_than_days,
                archive_path=plan.archive_path,
                actions=tuple(
                    LogArchiveAction(
                        source_path=action.source_path,
                        relative_path=action.relative_path,
                        size_bytes=action.size_bytes,
                        category=action.category,
                        status=action.status,
                        reason=action.reason,
                    )
                    for action in plan.actions
                ),
            )

        self.archive_dir.mkdir(parents=True, exist_ok=True)
        applied_actions: list[LogArchiveAction] = []

        manifest = []
        with zipfile.ZipFile(plan.archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for action in plan.actions:
                if action.status != "planned":
                    applied_actions.append(action)
                    continue

                if not action.source_path.exists():
                    applied_actions.append(
                        LogArchiveAction(
                            source_path=action.source_path,
                            relative_path=action.relative_path,
                            size_bytes=action.size_bytes,
                            category=action.category,
                            status="skipped",
                            reason="File disappeared before archive apply.",
                        )
                    )
                    continue

                archive_name = str(action.relative_path).replace("\\", "/")
                archive.write(action.source_path, archive_name)
                manifest.append(
                    {
                        "source_path": str(action.source_path),
                        "archive_name": archive_name,
                        "size_bytes": action.size_bytes,
                        "category": action.category,
                    }
                )

                action.source_path.unlink()

                applied_actions.append(
                    LogArchiveAction(
                        source_path=action.source_path,
                        relative_path=action.relative_path,
                        size_bytes=action.size_bytes,
                        category=action.category,
                        status="archived",
                        reason="Archived and removed from logs folder.",
                    )
                )

            archive.writestr(
                "manifest.json",
                json.dumps(
                    {
                        "created_at": datetime.now().isoformat(timespec="seconds"),
                        "older_than_days": plan.older_than_days,
                        "files": manifest,
                    },
                    indent=2,
                ),
            )

        self._remove_empty_dirs(self.log_dir)

        return LogArchivePlan(
            apply=True,
            older_than_days=plan.older_than_days,
            archive_path=plan.archive_path,
            actions=tuple(applied_actions),
        )

    def _remove_empty_dirs(self, root: Path) -> None:
        if not root.exists():
            return

        for directory in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
            try:
                if directory == self.archive_dir or self.archive_dir in directory.parents:
                    continue
                directory.rmdir()
            except OSError:
                pass
