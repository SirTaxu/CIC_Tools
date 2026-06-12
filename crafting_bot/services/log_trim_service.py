from __future__ import annotations

from datetime import datetime
from pathlib import Path

from crafting_bot import paths
from crafting_bot.domain.log_maintenance import MainLogTrimPlan
from crafting_bot.services.log_error_finder_service import split_log_line


class MainLogTrimService:
    """Archives old log.txt lines and rewrites log.txt with only relevant recent lines.

    This service never discards old log lines silently. In apply mode, the
    archived portion is written to logs/archive/*.txt before log.txt is rewritten.
    """

    def __init__(
        self,
        *,
        log_path: Path = paths.LOG_DIR / "log.txt",
        archive_dir: Path = paths.LOG_DIR / "archive",
    ) -> None:
        self.log_path = log_path
        self.archive_dir = archive_dir

    def build_plan(
        self,
        *,
        before_timestamp: str | None = None,
        keep_last_lines: int | None = None,
        apply: bool = False,
    ) -> MainLogTrimPlan:
        if before_timestamp is None and keep_last_lines is None:
            raise ValueError("Provide --before or --keep-last-lines.")

        if keep_last_lines is not None and keep_last_lines < 1:
            raise ValueError("--keep-last-lines must be >= 1.")

        if not self.log_path.exists():
            return MainLogTrimPlan(
                apply=apply,
                source_path=self.log_path,
                archive_path=self._archive_path("missing"),
                original_line_count=0,
                archived_line_count=0,
                kept_line_count=0,
                mode="missing_log_file",
                cutoff_timestamp=before_timestamp,
                keep_last_lines=keep_last_lines,
            )

        lines = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        archived, kept, mode = self._split_lines(
            lines,
            before_timestamp=before_timestamp,
            keep_last_lines=keep_last_lines,
        )

        archive_path = self._archive_path(mode)

        plan = MainLogTrimPlan(
            apply=False,
            source_path=self.log_path,
            archive_path=archive_path,
            original_line_count=len(lines),
            archived_line_count=len(archived),
            kept_line_count=len(kept),
            mode=mode,
            cutoff_timestamp=before_timestamp,
            keep_last_lines=keep_last_lines,
        )

        if apply and archived:
            self._apply(archived=archived, kept=kept, archive_path=archive_path)
            return MainLogTrimPlan(
                apply=True,
                source_path=self.log_path,
                archive_path=archive_path,
                original_line_count=len(lines),
                archived_line_count=len(archived),
                kept_line_count=len(kept),
                mode=mode,
                cutoff_timestamp=before_timestamp,
                keep_last_lines=keep_last_lines,
            )

        return plan

    def _split_lines(
        self,
        lines: list[str],
        *,
        before_timestamp: str | None,
        keep_last_lines: int | None,
    ) -> tuple[list[str], list[str], str]:
        if keep_last_lines is not None:
            if len(lines) <= keep_last_lines:
                return [], lines, f"keep_last_{keep_last_lines}_lines"
            return lines[:-keep_last_lines], lines[-keep_last_lines:], f"keep_last_{keep_last_lines}_lines"

        assert before_timestamp is not None
        cutoff = parse_user_timestamp(before_timestamp)

        archived: list[str] = []
        kept: list[str] = []

        current_line_timestamp: datetime | None = None
        for line in lines:
            timestamp_text, _message = split_log_line(line)
            if timestamp_text:
                parsed = parse_log_timestamp(timestamp_text)
                if parsed is not None:
                    current_line_timestamp = parsed

            if current_line_timestamp is not None and current_line_timestamp < cutoff:
                archived.append(line)
            else:
                kept.append(line)

        return archived, kept, f"before_{cutoff.strftime('%Y%m%d_%H%M%S')}"

    def _apply(self, *, archived: list[str], kept: list[str], archive_path: Path) -> None:
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path.write_text("".join(archived), encoding="utf-8")

        header = (
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
            f"Archived {len(archived)} older log line(s) to {archive_path}.\n"
        )
        self.log_path.write_text(header + "".join(kept), encoding="utf-8")

    def _archive_path(self, mode: str) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.archive_dir / f"{stamp}_log_txt_trim_{safe_mode(mode)}.txt"


def parse_user_timestamp(value: str) -> datetime:
    text = value.strip()
    accepted_formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
    )

    for fmt in accepted_formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass

    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            "Unsupported timestamp format. Use something like '2026-06-10 12:00:00'."
        ) from exc


def parse_log_timestamp(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def safe_mode(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value)
    return cleaned[:80] or "trim"
