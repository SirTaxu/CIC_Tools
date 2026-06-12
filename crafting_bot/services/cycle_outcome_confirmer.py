from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from crafting_bot.domain.cycle_confirmation import CycleOutcomeConfirmation
from crafting_bot.domain.models import LevelScanResult
from crafting_bot.services.level_scanner import LevelScanner

ScanEvidenceKind = Literal[
    "advanced",
    "same_level",
    "unknown_level",
    "wrong_screen",
    "scan_failed",
    "unexpected_level",
    "low_confidence",
]


@dataclass(frozen=True)
class ScanEvidence:
    """Classified evidence from one post-cycle scan."""

    kind: ScanEvidenceKind
    scan: LevelScanResult
    message: str


class CycleOutcomeConfirmer:
    """Confirms what happened after a rebuild cycle.

    This service has one responsibility: after a cycle runner finishes, capture
    fresh evidence and decide whether the visible level advanced, stayed on the
    same level, or is still uncertain.

    The confirmer is intentionally tolerant of transient unknown reads. A single
    unknown read immediately after a rebuild click is not enough to fail the
    loop. It keeps scanning up to max_scan_count and decides only from stable
    usable evidence.
    """

    def __init__(
        self,
        scanner: LevelScanner,
        *,
        scan_count: int = 2,
        max_scan_count: int = 5,
        delay_seconds: float = 0.15,
    ) -> None:
        self.scanner = scanner
        self.scan_count = max(1, int(scan_count))
        self.max_scan_count = max(self.scan_count, int(max_scan_count))
        self.delay_seconds = max(0.0, float(delay_seconds))

    def confirm(
        self,
        *,
        cycle_start_level: int | None,
        trigger_reason: str,
        min_digit_score: float,
        allow_low_confidence_level: bool,
    ) -> CycleOutcomeConfirmation:
        if cycle_start_level is None:
            return CycleOutcomeConfirmation(
                status="uncertain",
                start_level=None,
                expected_next_level=None,
                scans=(),
                message=f"Post-cycle confirmation unavailable for {trigger_reason}: no cycle start level was available.",
            )

        start_level = int(cycle_start_level)
        next_level = start_level + 1

        scans: list[LevelScanResult] = []
        evidence: list[ScanEvidence] = []

        for index in range(self.max_scan_count):
            scan = self.scanner.scan()
            scans.append(scan)
            evidence.append(
                self._classify_scan(
                    scan=scan,
                    start_level=start_level,
                    next_level=next_level,
                    min_digit_score=min_digit_score,
                    allow_low_confidence_level=allow_low_confidence_level,
                )
            )

            decision = self._stable_decision(
                trigger_reason=trigger_reason,
                start_level=start_level,
                next_level=next_level,
                scans=scans,
                evidence=evidence,
            )
            if decision is not None:
                return decision

            if index + 1 < self.max_scan_count and self.delay_seconds > 0:
                time.sleep(self.delay_seconds)

        return self._uncertain_result(
            trigger_reason=trigger_reason,
            start_level=start_level,
            next_level=next_level,
            scans=scans,
            evidence=evidence,
        )

    def _stable_decision(
        self,
        *,
        trigger_reason: str,
        start_level: int,
        next_level: int,
        scans: list[LevelScanResult],
        evidence: list[ScanEvidence],
    ) -> CycleOutcomeConfirmation | None:
        usable = [item for item in evidence if item.kind in {"advanced", "same_level"}]

        if len(usable) < self.scan_count:
            return None

        recent = usable[-self.scan_count:]

        if all(item.kind == "advanced" for item in recent):
            scores = ", ".join(str(item.scan.digit_score) for item in recent)
            return CycleOutcomeConfirmation(
                status="advanced",
                start_level=start_level,
                expected_next_level=next_level,
                scans=tuple(scans),
                message=(
                    f"Post-cycle confirmation after {trigger_reason}: "
                    f"{self.scan_count} usable scan(s) confirmed LEVEL_SCREEN at next level {next_level} "
                    f"with digit scores [{scores}]. Tracking now treats level {start_level} as completed."
                    + self._retry_suffix(scans, usable)
                ),
            )

        if all(item.kind == "same_level" for item in recent):
            scores = ", ".join(str(item.scan.digit_score) for item in recent)
            return CycleOutcomeConfirmation(
                status="same_level",
                start_level=start_level,
                expected_next_level=next_level,
                scans=tuple(scans),
                message=(
                    f"Post-cycle confirmation after {trigger_reason}: "
                    f"{self.scan_count} usable scan(s) confirmed LEVEL_SCREEN still at level {start_level} "
                    f"with digit scores [{scores}]. Treating this as a safe no-progress cycle."
                    + self._retry_suffix(scans, usable)
                ),
            )

        # Mixed same/advanced usable evidence is not stable. Continue scanning
        # while budget remains; if it never stabilizes, the final uncertain
        # result will explain the evidence list.
        return None

    def _classify_scan(
        self,
        *,
        scan: LevelScanResult,
        start_level: int,
        next_level: int,
        min_digit_score: float,
        allow_low_confidence_level: bool,
    ) -> ScanEvidence:
        if not scan.ok:
            return ScanEvidence("scan_failed", scan, f"scan failed: {scan.message}")

        if scan.screen != "LEVEL_SCREEN":
            return ScanEvidence("wrong_screen", scan, f"expected LEVEL_SCREEN but saw {scan.screen}")

        if scan.level is None:
            return ScanEvidence("unknown_level", scan, "LEVEL_SCREEN was visible, but level could not be read")

        if scan.level not in {start_level, next_level}:
            return ScanEvidence(
                "unexpected_level",
                scan,
                f"unexpected level read {scan.level_text}; expected {start_level} or {next_level}",
            )

        if not allow_low_confidence_level and not self._digit_confidence_is_safe(scan.digit_score, min_digit_score):
            return ScanEvidence(
                "low_confidence",
                scan,
                (
                    f"level {scan.level_text} was read, but digit confidence was too low "
                    f"(score={scan.digit_score}, required>={min_digit_score:.3f})"
                ),
            )

        if scan.level == next_level:
            return ScanEvidence("advanced", scan, f"confirmed next level {next_level}")

        return ScanEvidence("same_level", scan, f"confirmed same level {start_level}")

    def _uncertain_result(
        self,
        *,
        trigger_reason: str,
        start_level: int,
        next_level: int,
        scans: list[LevelScanResult],
        evidence: list[ScanEvidence],
    ) -> CycleOutcomeConfirmation:
        counts: dict[str, int] = {}
        for item in evidence:
            counts[item.kind] = counts.get(item.kind, 0) + 1

        details = "; ".join(
            f"{index + 1}:{item.kind}({item.scan.level_text}, score={item.scan.digit_score}, screen={item.scan.screen})"
            for index, item in enumerate(evidence)
        )

        return CycleOutcomeConfirmation(
            status="uncertain",
            start_level=start_level,
            expected_next_level=next_level,
            scans=tuple(scans),
            message=(
                f"Post-cycle confirmation failed after {trigger_reason}: no stable same/next-level result after "
                f"{len(scans)} scan(s). expected {start_level} or {next_level}. "
                f"evidence_counts={counts}. evidence=[{details}]"
            ),
        )

    @staticmethod
    def _retry_suffix(scans: list[LevelScanResult], usable: list[ScanEvidence]) -> str:
        if len(scans) <= len(usable):
            return ""
        return f" Ignored {len(scans) - len(usable)} transient non-usable scan(s) during confirmation retry."

    @staticmethod
    def _digit_confidence_is_safe(score: float | None, minimum: float) -> bool:
        return score is not None and float(score) >= float(minimum)
