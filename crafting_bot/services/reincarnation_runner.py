from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from crafting_bot.domain.cycle_execution import ExecutionMode, VerificationResult
from crafting_bot.domain.reincarnation_definitions import REINCARNATION_STEPS, ReincarnationStepDefinition
from crafting_bot.domain.reincarnation_execution import ReincarnationExecutionResult, ReincarnationStepResult
from crafting_bot.infra.adb_client import AdbClient
from crafting_bot.infra.calibration_store import CalibrationStore
from crafting_bot.services.level_scanner import LevelScanner
from crafting_bot.services.screen_waiter import ScreenWaiter


class ReincarnationRunner:
    """Runs one guarded reincarnation sequence.

    The rebuild loop decides *when* reincarnation is allowed. This runner only
    knows how to execute the calibrated navigation sequence and verify each
    transition before continuing.
    """

    def __init__(
        self,
        *,
        adb: AdbClient,
        calibration: CalibrationStore,
        waiter: ScreenWaiter,
        scanner: LevelScanner,
    ) -> None:
        self.adb = adb
        self.calibration = calibration
        self.waiter = waiter
        self.scanner = scanner

    def run_once(
        self,
        *,
        mode: ExecutionMode = "dry_run",
        step_delay_seconds: float = 0.20,
        wait_timeout_seconds: float = 8.0,
        poll_interval_seconds: float = 0.25,
        stop_event: Any | None = None,
    ) -> ReincarnationExecutionResult:
        if self._stop_requested(stop_event):
            return ReincarnationExecutionResult(
                mode=mode,
                eligible=False,
                steps=(),
                message="Stop requested before reincarnation started.",
            )

        planned = [self._plan_step(step, mode=mode) for step in REINCARNATION_STEPS]
        missing = [step for step in planned if step.outcome == "failed"]
        if missing:
            return ReincarnationExecutionResult(
                mode=mode,
                eligible=False,
                steps=tuple(planned),
                message="Reincarnation cannot run because one or more targets are missing.",
            )

        if mode == "dry_run":
            return ReincarnationExecutionResult(
                mode=mode,
                eligible=True,
                steps=tuple(planned),
                message="Reincarnation planned once. No clicks were sent.",
            )

        results: list[ReincarnationStepResult] = []
        for definition in REINCARNATION_STEPS:
            if self._stop_requested(stop_event):
                results.append(self._stop_step(definition, mode, "Stop requested before this reincarnation step."))
                break

            result = self._run_step(
                definition,
                mode=mode,
                step_delay_seconds=step_delay_seconds,
                wait_timeout_seconds=wait_timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                stop_event=stop_event,
            )
            results.append(result)
            if result.outcome == "failed":
                break

        success = bool(results) and all(step.outcome == "success" for step in results)
        return ReincarnationExecutionResult(
            mode=mode,
            eligible=True,
            steps=tuple(results),
            message="Reincarnation completed." if success else "Reincarnation stopped before completion.",
        )

    def _plan_step(self, definition: ReincarnationStepDefinition, *, mode: ExecutionMode) -> ReincarnationStepResult:
        target_name, point = self._resolve_point(definition)
        if target_name is None or point is None:
            return ReincarnationStepResult(
                definition=definition,
                outcome="failed",
                mode=mode,
                target_used=None,
                click_x=None,
                click_y=None,
                verification=None,
                message=f"Missing click point: {definition.target_name}.",
            )
        verification = None
        if definition.verification_target:
            verification = VerificationResult(
                target_name=definition.verification_target,
                attempted=False,
                passed=None,
                score=None,
                threshold=None,
                message="Dry-run: verification not attempted.",
            )
        return ReincarnationStepResult(
            definition=definition,
            outcome="planned",
            mode=mode,
            target_used=target_name,
            click_x=point[0],
            click_y=point[1],
            verification=verification,
            message=f"Dry-run: would click {target_name} at ({point[0]}, {point[1]}).",
        )

    def _run_step(
        self,
        definition: ReincarnationStepDefinition,
        *,
        mode: ExecutionMode,
        step_delay_seconds: float,
        wait_timeout_seconds: float,
        poll_interval_seconds: float,
        stop_event: Any | None,
    ) -> ReincarnationStepResult:
        target_name, point = self._resolve_point(definition)
        if target_name is None or point is None:
            return ReincarnationStepResult(
                definition=definition,
                outcome="failed",
                mode=mode,
                target_used=None,
                click_x=None,
                click_y=None,
                verification=None,
                message=f"Missing click point: {definition.target_name}.",
            )

        if self._stop_requested(stop_event):
            return self._stop_step(definition, mode, "Stop requested before reincarnation tap.")

        x, y = point
        self.adb.tap(x, y)

        verification = self._wait_after_step(
            definition,
            step_delay_seconds=step_delay_seconds,
            wait_timeout_seconds=wait_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            stop_event=stop_event,
        )
        if verification is not None and verification.passed is False:
            return ReincarnationStepResult(
                definition=definition,
                outcome="failed",
                mode=mode,
                target_used=target_name,
                click_x=x,
                click_y=y,
                verification=verification,
                message=f"Clicked {target_name} at ({x}, {y}) but verification failed.",
            )
        return ReincarnationStepResult(
            definition=definition,
            outcome="success",
            mode=mode,
            target_used=target_name,
            click_x=x,
            click_y=y,
            verification=verification,
            message=f"Clicked {target_name} at ({x}, {y}).",
        )

    def _wait_after_step(
        self,
        definition: ReincarnationStepDefinition,
        *,
        step_delay_seconds: float,
        wait_timeout_seconds: float,
        poll_interval_seconds: float,
        stop_event: Any | None,
    ) -> VerificationResult | None:
        target_name = definition.verification_target
        if not target_name:
            return None
        if self._sleep_interruptible(step_delay_seconds, stop_event):
            return self._stop_verification(target_name, "Stop requested during post-click delay.")
        if target_name == "level_area":
            return self._wait_for_level_one(
                timeout_seconds=wait_timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                stop_event=stop_event,
            )
        return self.waiter.wait_for_verification(
            target_name,
            timeout_seconds=wait_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            stop_event=stop_event,
        )

    def _wait_for_level_one(
        self,
        *,
        timeout_seconds: float,
        poll_interval_seconds: float,
        stop_event: Any | None,
    ) -> VerificationResult:
        started = time.monotonic()
        attempts = 0
        last_message = "no scan attempted"
        while True:
            if self._stop_requested(stop_event):
                return self._stop_verification("level_area", "Stop requested while waiting for level 1 after reincarnation.")
            attempts += 1
            scan = self.scanner.scan()
            elapsed = time.monotonic() - started
            last_message = scan.message
            if scan.ok and scan.level == 1:
                return VerificationResult(
                    target_name="level_area",
                    attempted=True,
                    passed=True,
                    score=scan.ready_score,
                    threshold=None,
                    preview_path=scan.level_crop_path,
                    message=(
                        f"Reincarnation returned to level 1: {scan.message} "
                        f"attempts={attempts}, elapsed={elapsed:.2f}s."
                    ),
                )
            if elapsed >= timeout_seconds:
                return VerificationResult(
                    target_name="level_area",
                    attempted=True,
                    passed=False,
                    score=scan.ready_score if scan.ok else None,
                    threshold=None,
                    preview_path=scan.level_crop_path if scan.ok else None,
                    message=(
                        f"Timed out after {timeout_seconds:.2f}s waiting for level 1 after reincarnation. "
                        f"Last scan: {last_message}. attempts={attempts}, elapsed={elapsed:.2f}s."
                    ),
                )
            if self._sleep_interruptible(min(poll_interval_seconds, max(0.0, timeout_seconds - elapsed)), stop_event):
                return self._stop_verification("level_area", "Stop requested during level-1 wait after reincarnation.")

    def _resolve_point(self, definition: ReincarnationStepDefinition) -> tuple[str | None, tuple[int, int] | None]:
        for name in (definition.target_name, *definition.fallback_point_names):
            if self.calibration.has_point(name):
                point = self.calibration.get_point(name)
                return name, (point.x, point.y)
        return None, None

    @staticmethod
    def _stop_requested(stop_event: Any | None) -> bool:
        if stop_event is None:
            return False
        is_set = getattr(stop_event, "is_set", None)
        return bool(is_set()) if callable(is_set) else False

    @classmethod
    def _sleep_interruptible(cls, seconds: float, stop_event: Any | None) -> bool:
        deadline = time.monotonic() + max(0.0, float(seconds))
        while time.monotonic() < deadline:
            if cls._stop_requested(stop_event):
                return True
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        return cls._stop_requested(stop_event)

    @staticmethod
    def _stop_verification(target_name: str | None, message: str) -> VerificationResult:
        return VerificationResult(
            target_name=target_name,
            attempted=False,
            passed=False,
            score=None,
            threshold=None,
            message=message,
            preview_path=None,
        )

    @classmethod
    def _stop_step(cls, definition: ReincarnationStepDefinition, mode: ExecutionMode, message: str) -> ReincarnationStepResult:
        verification = None
        if definition.verification_target:
            verification = cls._stop_verification(definition.verification_target, message)
        return ReincarnationStepResult(
            definition=definition,
            outcome="failed",
            mode=mode,
            target_used=None,
            click_x=None,
            click_y=None,
            verification=verification,
            message=message,
        )
