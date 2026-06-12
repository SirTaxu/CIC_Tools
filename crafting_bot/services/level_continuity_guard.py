from __future__ import annotations

from dataclasses import replace

from crafting_bot.domain.level_continuity import LevelContinuityDecision
from crafting_bot.domain.models import LevelScanResult


class LevelContinuityGuard:
    """Protects the loop from impossible single-scan level reads.

    In a normal climb, the visible level can stay the same or advance by one.
    A large drop, for example 106 -> 10, is not accepted unless the higher-level
    system explicitly resets tracking after a confirmed reincarnation/recovery.

    This guard has no IO and no scanner dependency. It only evaluates already
    captured scan results against trusted loop context.
    """

    def evaluate(
        self,
        scan: LevelScanResult,
        *,
        trusted_level: int | None,
        expected_level: int | None = None,
    ) -> LevelContinuityDecision:
        reference_level = self._reference_level(trusted_level, expected_level)
        raw_level = scan.level if scan.ok else None

        if not scan.ok:
            return self._accepted(raw_level, reference_level, expected_level, "scan_not_ok")

        if raw_level is None:
            return self._accepted(raw_level, reference_level, expected_level, "level_unknown")

        observed = int(raw_level)
        if reference_level is None:
            return self._accepted(observed, reference_level, expected_level, "no_reference_yet")

        reference = int(reference_level)
        if observed == reference:
            return self._accepted(observed, reference, expected_level, "same_level")

        if observed == reference + 1:
            return self._accepted(observed, reference, expected_level, "next_level")

        if observed < reference:
            return self._quarantined(
                raw_level=observed,
                effective_level=reference,
                reference_level=reference,
                expected_level=expected_level,
                reason="unexpected_drop",
                message=(
                    f"Level continuity guard ignored implausible drop {observed} after trusted level {reference}. "
                    f"Keeping trusted level {reference} for timing and cycle selection."
                ),
            )

        return self._quarantined(
            raw_level=observed,
            effective_level=reference,
            reference_level=reference,
            expected_level=expected_level,
            reason="unexpected_jump",
            message=(
                f"Level continuity guard ignored implausible jump {observed} after trusted level {reference}. "
                f"Keeping trusted level {reference} for timing and cycle selection."
            ),
        )

    def apply_effective_scan(
        self,
        scan: LevelScanResult,
        decision: LevelContinuityDecision,
    ) -> LevelScanResult:
        """Return a loop-safe scan.

        For quarantined scans, the raw crop and diagnostics remain available in
        the message, but the level/ready state used by the loop are made safe:
        - level is restored to the trusted effective level
        - ready is set to unknown so only timeout/probe logic can act on it
        """

        if not decision.quarantined:
            return scan

        effective_level = decision.effective_level
        level_text = str(effective_level) if effective_level is not None else "unknown"
        raw_level = scan.level_text

        return replace(
            scan,
            level_text=level_text,
            level=effective_level,
            ready="unknown",
            ready_score=None,
            ready_template=None,
            digit_score=None,
            message=(
                f"{scan.message} {decision.message} "
                f"Raw scan level={raw_level}, raw ready={scan.ready}, raw digit_score={scan.digit_score}."
            ),
        )

    @staticmethod
    def _reference_level(trusted_level: int | None, expected_level: int | None) -> int | None:
        if trusted_level is not None:
            return int(trusted_level)
        if expected_level is not None:
            return int(expected_level)
        return None

    @staticmethod
    def _accepted(
        raw_level: int | None,
        reference_level: int | None,
        expected_level: int | None,
        reason: str,
    ) -> LevelContinuityDecision:
        return LevelContinuityDecision(
            status="accepted",
            raw_level=raw_level,
            effective_level=raw_level,
            reference_level=reference_level,
            expected_level=expected_level,
            reason=reason,
            message=f"Level continuity accepted: reason={reason}.",
        )

    @staticmethod
    def _quarantined(
        *,
        raw_level: int,
        effective_level: int,
        reference_level: int,
        expected_level: int | None,
        reason: str,
        message: str,
    ) -> LevelContinuityDecision:
        return LevelContinuityDecision(
            status="quarantined",
            raw_level=raw_level,
            effective_level=effective_level,
            reference_level=reference_level,
            expected_level=expected_level,
            reason=reason,
            message=message,
        )
