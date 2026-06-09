from __future__ import annotations

import time
from typing import Any

from crafting_bot.domain.cycle_execution import ExecutionMode, VerificationResult
from crafting_bot.domain.hire_definitions import HIRE_STEPS, HireStepDefinition
from crafting_bot.domain.hire_execution import HireExecutionResult, HireStepResult
from crafting_bot.infra.adb_client import AdbClient
from crafting_bot.infra.calibration_store import CalibrationStore
from crafting_bot.services.screen_waiter import ScreenWaiter


class HireRunner:
    """Runs one guarded hire/setup sequence.

    The rebuild loop should decide *when* this is allowed. This runner only
    executes the calibrated Bag -> Research drag -> Auto-Sale drag -> Anvil
    sequence once, with verification around the screen transitions.
    """

    def __init__(
        self,
        *,
        adb: AdbClient,
        calibration: CalibrationStore,
        waiter: ScreenWaiter,
    ) -> None:
        self.adb = adb
        self.calibration = calibration
        self.waiter = waiter

    def run_once(
        self,
        *,
        mode: ExecutionMode = "dry_run",
        setup_level: int = 45,
        drag_duration_ms: int = 750,
        step_delay_seconds: float = 0.20,
        wait_timeout_seconds: float = 8.0,
        poll_interval_seconds: float = 0.25,
        stop_event: Any | None = None,
    ) -> HireExecutionResult:
        if self._stop_requested(stop_event):
            return HireExecutionResult(
                mode=mode,
                eligible=False,
                setup_level=setup_level,
                steps=(),
                message="Stop requested before hire/setup started.",
            )

        planned = [self._plan_step(step, mode=mode, drag_duration_ms=drag_duration_ms) for step in HIRE_STEPS]
        missing = [step for step in planned if step.outcome == "failed"]
        if missing:
            return HireExecutionResult(
                mode=mode,
                eligible=False,
                setup_level=setup_level,
                steps=tuple(planned),
                message="Hire/setup cannot run because one or more calibrated targets are missing.",
            )

        if mode == "dry_run":
            return HireExecutionResult(
                mode=mode,
                eligible=True,
                setup_level=setup_level,
                steps=tuple(planned),
                message="Hire/setup planned once. No clicks or drags were sent.",
            )

        results: list[HireStepResult] = []
        for definition in HIRE_STEPS:
            if self._stop_requested(stop_event):
                results.append(self._stop_step(definition, mode, "Stop requested before this hire/setup step."))
                break

            result = self._run_step(
                definition,
                mode=mode,
                drag_duration_ms=drag_duration_ms,
                step_delay_seconds=step_delay_seconds,
                wait_timeout_seconds=wait_timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                stop_event=stop_event,
            )
            results.append(result)
            if result.outcome == "failed":
                break

        success = bool(results) and all(step.outcome == "success" for step in results)
        return HireExecutionResult(
            mode=mode,
            eligible=True,
            setup_level=setup_level,
            steps=tuple(results),
            message="Hire/setup completed." if success else "Hire/setup stopped before completion.",
        )

    def _plan_step(self, definition: HireStepDefinition, *, mode: ExecutionMode, drag_duration_ms: int) -> HireStepResult:
        start = self._point(definition.target_name)
        if start is None:
            return HireStepResult(
                definition=definition,
                outcome="failed",
                mode=mode,
                target_used=None,
                click_x=None,
                click_y=None,
                drag_end_used=None,
                drag_end_x=None,
                drag_end_y=None,
                drag_duration_ms=None,
                verification=None,
                message=f"Missing point target: {definition.target_name}.",
            )

        end = None
        if definition.mode == "drag":
            if not definition.drag_end_target_name:
                return HireStepResult(
                    definition=definition,
                    outcome="failed",
                    mode=mode,
                    target_used=definition.target_name,
                    click_x=start[0],
                    click_y=start[1],
                    drag_end_used=None,
                    drag_end_x=None,
                    drag_end_y=None,
                    drag_duration_ms=None,
                    verification=None,
                    message=f"Missing drag end target name for {definition.action}.",
                )
            end = self._point(definition.drag_end_target_name)
            if end is None:
                return HireStepResult(
                    definition=definition,
                    outcome="failed",
                    mode=mode,
                    target_used=definition.target_name,
                    click_x=start[0],
                    click_y=start[1],
                    drag_end_used=definition.drag_end_target_name,
                    drag_end_x=None,
                    drag_end_y=None,
                    drag_duration_ms=drag_duration_ms,
                    verification=None,
                    message=f"Missing point target: {definition.drag_end_target_name}.",
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

        return HireStepResult(
            definition=definition,
            outcome="planned",
            mode=mode,
            target_used=definition.target_name,
            click_x=start[0],
            click_y=start[1],
            drag_end_used=definition.drag_end_target_name,
            drag_end_x=end[0] if end else None,
            drag_end_y=end[1] if end else None,
            drag_duration_ms=drag_duration_ms if definition.mode == "drag" else None,
            verification=verification,
            message=self._planned_message(definition, start, end, drag_duration_ms),
        )

    def _run_step(
        self,
        definition: HireStepDefinition,
        *,
        mode: ExecutionMode,
        drag_duration_ms: int,
        step_delay_seconds: float,
        wait_timeout_seconds: float,
        poll_interval_seconds: float,
        stop_event: Any | None,
    ) -> HireStepResult:
        start = self._point(definition.target_name)
        if start is None:
            return self._failed_missing(definition, mode, f"Missing point target: {definition.target_name}.")

        end = None
        if definition.mode == "drag":
            if not definition.drag_end_target_name:
                return self._failed_missing(definition, mode, f"Missing drag end target name for {definition.action}.")
            end = self._point(definition.drag_end_target_name)
            if end is None:
                return self._failed_missing(definition, mode, f"Missing point target: {definition.drag_end_target_name}.")

        if self._stop_requested(stop_event):
            return self._stop_step(definition, mode, "Stop requested before hire/setup input.")

        if definition.mode == "click":
            self.adb.tap(start[0], start[1])
            message = f"Clicked {definition.target_name} at ({start[0]}, {start[1]})."
        else:
            assert end is not None
            self.adb.swipe(start[0], start[1], end[0], end[1], duration_ms=drag_duration_ms)
            message = (
                f"Dragged {definition.target_name} ({start[0]}, {start[1]}) -> "
                f"{definition.drag_end_target_name} ({end[0]}, {end[1]}) over {drag_duration_ms}ms."
            )

        verification = self._wait_after_step(
            definition,
            step_delay_seconds=step_delay_seconds,
            wait_timeout_seconds=wait_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            stop_event=stop_event,
        )
        if verification is not None and verification.passed is False:
            return HireStepResult(
                definition=definition,
                outcome="failed",
                mode=mode,
                target_used=definition.target_name,
                click_x=start[0],
                click_y=start[1],
                drag_end_used=definition.drag_end_target_name,
                drag_end_x=end[0] if end else None,
                drag_end_y=end[1] if end else None,
                drag_duration_ms=drag_duration_ms if definition.mode == "drag" else None,
                verification=verification,
                message=f"{message} Verification failed.",
            )

        return HireStepResult(
            definition=definition,
            outcome="success",
            mode=mode,
            target_used=definition.target_name,
            click_x=start[0],
            click_y=start[1],
            drag_end_used=definition.drag_end_target_name,
            drag_end_x=end[0] if end else None,
            drag_end_y=end[1] if end else None,
            drag_duration_ms=drag_duration_ms if definition.mode == "drag" else None,
            verification=verification,
            message=message,
        )

    def _wait_after_step(
        self,
        definition: HireStepDefinition,
        *,
        step_delay_seconds: float,
        wait_timeout_seconds: float,
        poll_interval_seconds: float,
        stop_event: Any | None,
    ) -> VerificationResult | None:
        if not definition.verification_target:
            if self._sleep_interruptible(step_delay_seconds, stop_event):
                return self._stop_verification(None, "Stop requested during post-action delay.")
            return None

        if self._sleep_interruptible(step_delay_seconds, stop_event):
            return self._stop_verification(definition.verification_target, "Stop requested during post-action delay.")
        return self.waiter.wait_for_verification(
            definition.verification_target,
            timeout_seconds=wait_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            stop_event=stop_event,
        )

    def _point(self, name: str) -> tuple[int, int] | None:
        if not self.calibration.has_point(name):
            return None
        point = self.calibration.get_point(name)
        return point.x, point.y

    @staticmethod
    def _planned_message(definition: HireStepDefinition, start: tuple[int, int], end: tuple[int, int] | None, drag_duration_ms: int) -> str:
        if definition.mode == "drag":
            return (
                f"Dry-run: would drag {definition.target_name} ({start[0]}, {start[1]}) -> "
                f"{definition.drag_end_target_name} ({end[0]}, {end[1]}) over {drag_duration_ms}ms."
            )
        return f"Dry-run: would click {definition.target_name} at ({start[0]}, {start[1]})."

    def _failed_missing(self, definition: HireStepDefinition, mode: ExecutionMode, message: str) -> HireStepResult:
        return HireStepResult(
            definition=definition,
            outcome="failed",
            mode=mode,
            target_used=definition.target_name,
            click_x=None,
            click_y=None,
            drag_end_used=definition.drag_end_target_name,
            drag_end_x=None,
            drag_end_y=None,
            drag_duration_ms=None,
            verification=None,
            message=message,
        )

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
    def _stop_step(cls, definition: HireStepDefinition, mode: ExecutionMode, message: str) -> HireStepResult:
        verification = None
        if definition.verification_target:
            verification = cls._stop_verification(definition.verification_target, message)
        return HireStepResult(
            definition=definition,
            outcome="failed",
            mode=mode,
            target_used=definition.target_name,
            click_x=None,
            click_y=None,
            drag_end_used=definition.drag_end_target_name,
            drag_end_x=None,
            drag_end_y=None,
            drag_duration_ms=None,
            verification=verification,
            message=message,
        )
