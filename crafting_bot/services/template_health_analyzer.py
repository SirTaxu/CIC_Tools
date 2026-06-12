from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from crafting_bot.domain.template_health import TemplateHealthFinding, TemplateHealthReport, TemplateRecord


class TemplateHealthAnalyzer:
    """Turns template inventory records into actionable health findings."""

    def __init__(
        self,
        *,
        high_auto_count_warning_threshold: int = 15,
        high_total_count_warning_threshold: int = 30,
    ) -> None:
        self.high_auto_count_warning_threshold = high_auto_count_warning_threshold
        self.high_total_count_warning_threshold = high_total_count_warning_threshold

    def analyze(self, records: list[TemplateRecord]) -> TemplateHealthReport:
        findings: list[TemplateHealthFinding] = []

        for record in records:
            findings.extend(self._analyze_record(record))

        findings.extend(self._analyze_ready_pairs(records))
        findings.extend(self._analyze_template_counts(records))

        summary = self._summary(records, findings)
        findings = sorted(
            findings,
            key=lambda item: (
                {"error": 0, "warning": 1, "info": 2}[item.severity],
                item.kind or "",
                item.level if item.level is not None else 10_000,
                item.code,
                str(item.relative_path or item.path or ""),
            ),
        )

        return TemplateHealthReport(
            records=tuple(records),
            findings=tuple(findings),
            summary=summary,
        )

    def _analyze_record(self, record: TemplateRecord) -> list[TemplateHealthFinding]:
        findings: list[TemplateHealthFinding] = []

        if record.source == "missing_directory":
            return [
                self._finding(
                    "error",
                    "missing_template_directory",
                    record,
                    record.parse_message or "Template directory is missing.",
                    "Create the directory or restore the data folder before running the bot.",
                )
            ]

        if record.level is not None and record.level < 1:
            findings.append(
                self._finding(
                    "error",
                    "invalid_template_level_zero",
                    record,
                    "Template is assigned to level 0, but level 0 does not exist.",
                    "Quarantine this template or repair the index entry. Do not use level 0 templates.",
                )
            )

        if record.indexed and not record.exists:
            findings.append(
                self._finding(
                    "error",
                    "index_missing_file",
                    record,
                    "index.json references a template file that does not exist.",
                    "Remove the stale index entry or restore the missing template file.",
                )
            )
            return findings

        if record.exists and not record.loadable:
            findings.append(
                self._finding(
                    "error",
                    "unreadable_image",
                    record,
                    record.parse_message or "Template file exists but cannot be loaded as an image.",
                    "Quarantine this file and retrain the affected template if needed.",
                )
            )

        if record.exists and record.parse_message and "filename" in record.parse_message.lower():
            findings.append(
                self._finding(
                    "warning",
                    "unparsed_filename",
                    record,
                    record.parse_message,
                    "Rename the file to the expected naming format or add a valid index entry.",
                )
            )

        if record.exists and not record.indexed:
            findings.append(
                self._finding(
                    "info",
                    "unindexed_file",
                    record,
                    "Template file is present but not listed in index.json.",
                    "This is acceptable if filename parsing works, but adding it to index.json makes the data easier to audit.",
                )
            )

        findings.extend(self._metadata_mismatches(record))

        if record.kind == "digit" and record.exists and record.loadable:
            if record.digit is None:
                findings.append(
                    self._finding(
                        "warning",
                        "digit_missing_label",
                        record,
                        "Digit template has no parseable digit label.",
                        "Rename the file or retrain the digit so the label is explicit.",
                    )
                )

        if record.kind == "ready" and record.exists and record.loadable:
            if record.level is None or record.state is None:
                findings.append(
                    self._finding(
                        "warning",
                        "ready_missing_level_or_state",
                        record,
                        "Ready template has no parseable level or ready/not-ready state.",
                        "Rename the file or add a valid index entry with level and state.",
                    )
                )

        return findings

    def _metadata_mismatches(self, record: TemplateRecord) -> list[TemplateHealthFinding]:
        findings: list[TemplateHealthFinding] = []
        if not record.indexed:
            return findings

        if (
            record.filename_level is not None
            and record.index_level is not None
            and record.filename_level != record.index_level
        ):
            findings.append(
                self._finding(
                    "warning",
                    "metadata_level_mismatch",
                    record,
                    f"Filename level {record.filename_level} differs from index level {record.index_level}.",
                    "Fix the filename or index entry so both point to the same level.",
                )
            )

        if (
            record.filename_state is not None
            and record.index_state is not None
            and record.filename_state != record.index_state
        ):
            findings.append(
                self._finding(
                    "warning",
                    "metadata_state_mismatch",
                    record,
                    f"Filename state {record.filename_state} differs from index state {record.index_state}.",
                    "Fix the filename or index entry so both use the same state.",
                )
            )

        if (
            record.filename_digit is not None
            and record.index_digit is not None
            and record.filename_digit != record.index_digit
        ):
            findings.append(
                self._finding(
                    "warning",
                    "metadata_digit_mismatch",
                    record,
                    f"Filename digit {record.filename_digit} differs from index digit {record.index_digit}.",
                    "Fix the filename or index entry so both use the same digit.",
                )
            )

        return findings

    def _analyze_ready_pairs(self, records: list[TemplateRecord]) -> list[TemplateHealthFinding]:
        by_level: dict[int, set[str]] = defaultdict(set)

        for record in records:
            if record.kind != "ready" or not record.exists or not record.loadable:
                continue
            if record.level is None or record.level < 1 or record.state is None:
                continue
            by_level[record.level].add(record.state)

        findings: list[TemplateHealthFinding] = []
        for level, states in sorted(by_level.items()):
            if states == {"yes"} or states == {"no"}:
                missing = "no" if states == {"yes"} else "yes"
                findings.append(
                    TemplateHealthFinding(
                        severity="warning",
                        code="ready_level_missing_pair_state",
                        message=f"Level {level} has ready templates for {sorted(states)} but no {missing} template.",
                        recommendation="Train or restore the missing pair state so yes-vs-no confirmation can work reliably.",
                        path=None,
                        relative_path=None,
                        kind="ready",
                        level=level,
                        state=missing,
                        digit=None,
                    )
                )

        return findings

    def _analyze_template_counts(self, records: list[TemplateRecord]) -> list[TemplateHealthFinding]:
        grouped: dict[tuple[str, int | None, str | None, str | None], list[TemplateRecord]] = defaultdict(list)

        for record in records:
            if not record.exists or not record.loadable:
                continue
            if record.level is not None and record.level < 1:
                continue
            key = (record.kind, record.level, record.state, record.digit)
            grouped[key].append(record)

        findings: list[TemplateHealthFinding] = []
        for (kind, level, state, digit), items in sorted(grouped.items(), key=lambda kv: str(kv[0])):
            auto_items = [item for item in items if item.source in {"auto", "loop_auto"}]

            if len(auto_items) > self.high_auto_count_warning_threshold:
                findings.append(
                    TemplateHealthFinding(
                        severity="warning",
                        code="many_auto_templates_for_bucket",
                        message=(
                            f"{len(auto_items)} auto/loop_auto templates found for "
                            f"kind={kind}, level={level}, state={state}, digit={digit}."
                        ),
                        recommendation="Review this bucket and quarantine weak or accidental auto-trained templates.",
                        path=None,
                        relative_path=None,
                        kind=kind,  # type: ignore[arg-type]
                        level=level,
                        state=state,
                        digit=digit,
                    )
                )

            if len(items) > self.high_total_count_warning_threshold:
                findings.append(
                    TemplateHealthFinding(
                        severity="info",
                        code="many_templates_for_bucket",
                        message=(
                            f"{len(items)} total templates found for "
                            f"kind={kind}, level={level}, state={state}, digit={digit}."
                        ),
                        recommendation="This may be fine, but large buckets can make bad templates harder to spot.",
                        path=None,
                        relative_path=None,
                        kind=kind,  # type: ignore[arg-type]
                        level=level,
                        state=state,
                        digit=digit,
                    )
                )

        return findings

    @staticmethod
    def _summary(records: list[TemplateRecord], findings: list[TemplateHealthFinding]) -> dict[str, int]:
        finding_counts = Counter(finding.severity for finding in findings)

        return {
            "records_total": len(records),
            "ready_records": sum(1 for record in records if record.kind == "ready"),
            "digit_records": sum(1 for record in records if record.kind == "digit"),
            "files_existing": sum(1 for record in records if record.exists),
            "files_loadable": sum(1 for record in records if record.loadable),
            "indexed_records": sum(1 for record in records if record.indexed),
            "errors": finding_counts["error"],
            "warnings": finding_counts["warning"],
            "info": finding_counts["info"],
        }

    @staticmethod
    def _finding(
        severity: str,
        code: str,
        record: TemplateRecord,
        message: str,
        recommendation: str,
    ) -> TemplateHealthFinding:
        return TemplateHealthFinding(
            severity=severity,  # type: ignore[arg-type]
            code=code,
            message=message,
            recommendation=recommendation,
            path=record.path,
            relative_path=record.relative_path,
            kind=record.kind,
            level=record.level,
            state=record.state,
            digit=record.digit,
        )
