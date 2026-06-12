from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from crafting_bot import paths
from crafting_bot.domain.log_maintenance import LogErrorEvent, LogErrorReport

_TIMESTAMP_PATTERN = re.compile(r"^\[(?P<timestamp>[^\]]+)\]\s*(?P<message>.*)$")
_WAITING_LEVEL_PATTERN = re.compile(r"Waiting:\s+level=(?P<level>\d+|unknown)", re.IGNORECASE)

# A large drop after these messages is expected and should not be treated as a
# suspicious bad digit read.
_RESET_CONTEXT_PATTERN = re.compile(
    r"reincarnation|Starting GUI loop session|Starting rebuild loop|level\s*1|target level|Loop stopped:\s*stop_requested",
    re.IGNORECASE,
)

_MANUAL_STOP_CONTEXT_PATTERN = re.compile(
    r"Stop requested|Loop stopped:\s*stop_requested",
    re.IGNORECASE,
)


class LogErrorFinderService:
    """Extracts important events from log.txt.

    This is a diagnostic tool, not a runtime component. It intentionally keeps
    noisy normal events, such as safe no-progress timeout cycles, out of the
    default output. Cycle failures caused by a manual stop request are also
    hidden by default because they are shutdown artifacts, not reliability
    failures.
    """

    ERROR_PATTERNS = (
        ("cycle_failed", re.compile(r"\bCycle failed\b", re.IGNORECASE)),
        ("loop_stopped_failure", re.compile(r"\bLoop stopped:\s*(?!stop_requested)\w+", re.IGNORECASE)),
        ("unexpected_level_read", re.compile(r"unexpected level read", re.IGNORECASE)),
        ("unknown_level", re.compile(r"\bunknown_level\b|level=unknown", re.IGNORECASE)),
        ("traceback", re.compile(r"Traceback|Exception|Error:", re.IGNORECASE)),
    )

    WARNING_PATTERNS = (
        ("recovery_attempted", re.compile(r"Recovery attempted", re.IGNORECASE)),
        ("implausible_level_guard", re.compile(r"continuity guard|implausible", re.IGNORECASE)),
    )

    INFO_PATTERNS = (
        ("safe_no_progress", re.compile(r"safe no-progress cycle", re.IGNORECASE)),
        ("cycle_completed", re.compile(r"\bCycle completed\b", re.IGNORECASE)),
        ("stop_requested", re.compile(r"\bStop requested\b|\bLoop stopped:\s*stop_requested", re.IGNORECASE)),
    )

    def __init__(self, log_path: Path = paths.LOG_DIR / "log.txt") -> None:
        self.log_path = log_path

    def find(
        self,
        *,
        tail_lines: int | None = 5000,
        include_info: bool = False,
        errors_only: bool = False,
        code_filter: set[str] | None = None,
        context_lines: int = 0,
        suppress_expected_resets: bool = True,
    ) -> LogErrorReport:
        lines = self._read_lines(tail_lines=tail_lines)
        base_line_number = max(1, self._total_line_count() - len(lines) + 1)

        events: list[LogErrorEvent] = []
        last_waiting_level: int | None = None

        for offset, raw_line in enumerate(lines):
            line_number = base_line_number + offset
            timestamp, message = split_log_line(raw_line)

            suspicious_drop = self._detect_suspicious_level_drop(message, last_waiting_level)
            waiting_level = parse_waiting_level(message)

            if suspicious_drop and not (
                suppress_expected_resets and self._has_reset_context(lines, offset, context_window=12)
            ):
                previous, current = suspicious_drop
                event = LogErrorEvent(
                    line_number=line_number,
                    timestamp=timestamp,
                    severity="error",
                    code="suspicious_level_drop",
                    message=(
                        f"Waiting level dropped from {previous} to {current}; "
                        "this is usually a bad digit read unless reincarnation just happened."
                    ),
                    raw_line=raw_line.rstrip("\n"),
                    context_before=self._context_before(lines, offset, context_lines),
                    context_after=self._context_after(lines, offset, context_lines),
                )
                if self._include_event(event, include_info, errors_only, code_filter):
                    events.append(event)

            if waiting_level is not None:
                last_waiting_level = waiting_level

            event = self._classify_line(
                raw_line=raw_line,
                line_number=line_number,
                timestamp=timestamp,
                message=message,
                lines=lines,
                offset=offset,
                context_lines=context_lines,
                include_info=include_info,
            )

            if event and self._include_event(event, include_info, errors_only, code_filter):
                events.append(event)

        return LogErrorReport(
            source_path=self.log_path,
            events=tuple(events),
            scanned_lines=len(lines),
        )

    def write_report(self, report: LogErrorReport, output_dir: Path = paths.LOG_DIR / "error_reports") -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"{stamp}_error_summary.txt"

        lines: list[str] = []
        lines.append("Log Error Summary")
        lines.append("=" * 80)
        lines.append(f"source: {report.source_path}")
        lines.append(f"scanned_lines: {report.scanned_lines}")
        lines.append(f"errors: {report.error_count}")
        lines.append(f"warnings: {report.warning_count}")
        lines.append(f"info: {report.info_count}")
        lines.append("")

        for event in report.events:
            timestamp = event.timestamp or "-"
            lines.append(f"[{event.severity.upper()}] line={event.line_number} time={timestamp} code={event.code}")
            for context_line in event.context_before:
                lines.append(f"  before: {context_line.rstrip()}")
            lines.append(event.message)
            lines.append(event.raw_line)
            for context_line in event.context_after:
                lines.append(f"  after: {context_line.rstrip()}")
            lines.append("")

        output_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        return output_path

    def _classify_line(
        self,
        *,
        raw_line: str,
        line_number: int,
        timestamp: str | None,
        message: str,
        lines: list[str],
        offset: int,
        context_lines: int,
        include_info: bool,
    ) -> LogErrorEvent | None:
        if re.search(r"\bCycle failed\b", message, re.IGNORECASE) and self._has_manual_stop_context(
            lines,
            offset,
            context_window=10,
        ):
            if not include_info:
                return None

            return LogErrorEvent(
                line_number=line_number,
                timestamp=timestamp,
                severity="info",
                code="cycle_failed_during_manual_stop",
                message=(
                    "Cycle failure was suppressed as a manual-stop shutdown artifact: "
                    f"{message}"
                ),
                raw_line=raw_line.rstrip("\n"),
                context_before=self._context_before(lines, offset, context_lines),
                context_after=self._context_after(lines, offset, context_lines),
            )

        for code, pattern in self.ERROR_PATTERNS:
            if pattern.search(message):
                return LogErrorEvent(
                    line_number=line_number,
                    timestamp=timestamp,
                    severity="error",
                    code=code,
                    message=message,
                    raw_line=raw_line.rstrip("\n"),
                    context_before=self._context_before(lines, offset, context_lines),
                    context_after=self._context_after(lines, offset, context_lines),
                )

        for code, pattern in self.WARNING_PATTERNS:
            if pattern.search(message):
                return LogErrorEvent(
                    line_number=line_number,
                    timestamp=timestamp,
                    severity="warning",
                    code=code,
                    message=message,
                    raw_line=raw_line.rstrip("\n"),
                    context_before=self._context_before(lines, offset, context_lines),
                    context_after=self._context_after(lines, offset, context_lines),
                )

        if include_info:
            for code, pattern in self.INFO_PATTERNS:
                if pattern.search(message):
                    return LogErrorEvent(
                        line_number=line_number,
                        timestamp=timestamp,
                        severity="info",
                        code=code,
                        message=message,
                        raw_line=raw_line.rstrip("\n"),
                        context_before=self._context_before(lines, offset, context_lines),
                        context_after=self._context_after(lines, offset, context_lines),
                    )

        return None

    @staticmethod
    def _include_event(
        event: LogErrorEvent,
        include_info: bool,
        errors_only: bool,
        code_filter: set[str] | None,
    ) -> bool:
        if errors_only and event.severity != "error":
            return False
        if event.severity == "info" and not include_info:
            return False
        if code_filter and event.code not in code_filter:
            return False
        return True

    def _read_lines(self, *, tail_lines: int | None) -> list[str]:
        if not self.log_path.exists():
            return []

        with self.log_path.open("r", encoding="utf-8", errors="replace") as handle:
            if tail_lines is None or tail_lines <= 0:
                return handle.readlines()

            lines = handle.readlines()
            return lines[-tail_lines:]

    def _total_line_count(self) -> int:
        if not self.log_path.exists():
            return 0
        with self.log_path.open("r", encoding="utf-8", errors="replace") as handle:
            return sum(1 for _ in handle)

    @staticmethod
    def _detect_suspicious_level_drop(message: str, previous_level: int | None) -> tuple[int, int] | None:
        current = parse_waiting_level(message)
        if current is None or previous_level is None:
            return None

        if previous_level >= 20 and current < previous_level - 5:
            return previous_level, current

        return None

    @staticmethod
    def _has_reset_context(lines: list[str], offset: int, *, context_window: int) -> bool:
        start = max(0, offset - context_window)
        end = min(len(lines), offset + context_window + 1)
        combined = "\n".join(lines[start:end])
        return bool(_RESET_CONTEXT_PATTERN.search(combined))

    @staticmethod
    def _has_manual_stop_context(lines: list[str], offset: int, *, context_window: int) -> bool:
        start = max(0, offset - context_window)
        end = min(len(lines), offset + context_window + 1)
        combined = "\n".join(lines[start:end])
        return bool(_MANUAL_STOP_CONTEXT_PATTERN.search(combined))

    @staticmethod
    def _context_before(lines: list[str], offset: int, context_lines: int) -> tuple[str, ...]:
        if context_lines <= 0:
            return ()
        start = max(0, offset - context_lines)
        return tuple(line.rstrip("\n") for line in lines[start:offset])

    @staticmethod
    def _context_after(lines: list[str], offset: int, context_lines: int) -> tuple[str, ...]:
        if context_lines <= 0:
            return ()
        end = min(len(lines), offset + context_lines + 1)
        return tuple(line.rstrip("\n") for line in lines[offset + 1:end])


def split_log_line(raw_line: str) -> tuple[str | None, str]:
    match = _TIMESTAMP_PATTERN.match(raw_line.rstrip("\n"))
    if not match:
        return None, raw_line.rstrip("\n")
    return match.group("timestamp"), match.group("message")


def parse_waiting_level(message: str) -> int | None:
    match = _WAITING_LEVEL_PATTERN.search(message)
    if not match:
        return None

    text = match.group("level")
    if not text.isdigit():
        return None

    return int(text)
