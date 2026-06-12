from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image

from crafting_bot.domain.cycle_definitions import CycleStepDefinition
from crafting_bot.domain.cycle_execution import CycleExecutionResult, ExecutionMode, StepExecutionResult, VerificationResult
from crafting_bot.domain.cycle_selector import select_cycle_for_level
from crafting_bot.domain.target_catalog import get_search_target_definition, get_target_definition
from crafting_bot.infra.adb_client import AdbClient
from crafting_bot.infra.calibration_store import CalibrationStore
from crafting_bot.services.level_scanner import LevelScanner
from crafting_bot.services.screen_verifier import ScreenVerifier
from crafting_bot.services.screen_waiter import ScreenWaiter
from crafting_bot.services.search_target_service import SearchTargetService
from crafting_bot.services.reward_selection_service import RewardSelectionService
from crafting_bot.services.target_status_service import TargetStatusService


class CycleRunner:
    """Runs exactly one selected rebuild cycle, with optional click mode.

    This is not the unattended loop. It is a guarded single-cycle executor used
    to prove each level phase before the main bot starts automating repeatedly.
    Between clicks it waits for the expected next screen/target instead of using
    one fixed sleep.
    """

    def __init__(
        self,
        scanner: LevelScanner,
        adb: AdbClient,
        calibration: CalibrationStore,
        search_targets: SearchTargetService,
        verifier: ScreenVerifier,
        waiter: ScreenWaiter,
        target_status: TargetStatusService,
        latest_screenshot_path: Path,
        reward_selector: RewardSelectionService | None = None,
    ) -> None:
        self.scanner = scanner
        self.adb = adb
        self.calibration = calibration
        self.search_targets = search_targets
        self.verifier = verifier
        self.waiter = waiter
        self.target_status = target_status
        self.latest_screenshot_path = latest_screenshot_path
        self.reward_selector = reward_selector
        self._last_free_button_target = "free_button"

    def run_once(
        self,
        *,
        mode: ExecutionMode = "dry_run",
        force: bool = False,
        level_override: int | None = None,
        step_delay_seconds: float = 0.20,
        wait_timeout_seconds: float = 8.0,
        poll_interval_seconds: float = 0.25,
        stop_on_failure: bool = True,
        min_digit_score_for_click: float = 0.50,
        allow_low_confidence_level: bool = False,
        stop_event: Any | None = None,
    ) -> CycleExecutionResult:
        self._last_free_button_target = "free_button"

        scan = self.scanner.scan()
        effective_level = level_override if level_override is not None else scan.level

        if self._stop_requested(stop_event):
            return CycleExecutionResult(
                mode=mode,
                scan=scan,
                cycle=None,
                eligible=False,
                trigger_reason="stop_requested",
                steps=(),
                message="Stop requested before cycle execution started.",
            )

        if effective_level is None:
            return CycleExecutionResult(
                mode=mode,
                scan=scan,
                cycle=None,
                eligible=False,
                trigger_reason="unknown_level",
                steps=(),
                message="Cannot choose a cycle because the level was not read.",
            )

        if (
            mode == "click"
            and level_override is None
            and not allow_low_confidence_level
            and not self._level_confidence_is_safe(scan.digit_score, min_digit_score_for_click)
        ):
            return CycleExecutionResult(
                mode=mode,
                scan=scan,
                cycle=None,
                eligible=False,
                trigger_reason="level_confidence_too_low",
                steps=(),
                message=(
                    "Click mode blocked because the level digit confidence is too low. "
                    f"score={scan.digit_score}, required>={min_digit_score_for_click:.3f}. "
                    "Inspect logs/debug_crops/latest_level_area.png, add/train a better digit template, "
                    "or use --level only for controlled manual phase testing."
                ),
            )

        cycle = select_cycle_for_level(effective_level)
        trigger_reason = self._trigger_reason(scan, force=force)
        eligible = force or scan.ready == "yes"

        planned_steps = tuple(self._plan_step(step, mode=mode) for step in cycle.steps)
        if not eligible:
            return CycleExecutionResult(
                mode=mode,
                scan=scan,
                cycle=cycle,
                eligible=False,
                trigger_reason=trigger_reason,
                steps=planned_steps,
                message="Cycle was not executed because the level is not ready. Use --force only for manual testing.",
            )

        if mode == "dry_run":
            return CycleExecutionResult(
                mode=mode,
                scan=scan,
                cycle=cycle,
                eligible=True,
                trigger_reason=trigger_reason,
                steps=planned_steps,
                message=f"Cycle {cycle.name} planned once. No clicks were sent.",
            )

        steps: list[StepExecutionResult] = []
        for step in cycle.steps:
            if self._stop_requested(stop_event):
                steps.append(self._stop_step_result(step, mode, "Stop requested before this cycle step started."))
                break
            result = self._run_step(
                step,
                mode=mode,
                step_delay_seconds=step_delay_seconds,
                wait_timeout_seconds=wait_timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                stop_event=stop_event,
            )
            steps.append(result)
            if stop_on_failure and result.outcome == "failed":
                break

        return CycleExecutionResult(
            mode=mode,
            scan=scan,
            cycle=cycle,
            eligible=True,
            trigger_reason=trigger_reason,
            steps=tuple(steps),
            message=f"Cycle {cycle.name} executed once. Click mode was enabled.",
        )

    def _plan_step(self, step: CycleStepDefinition, *, mode: ExecutionMode) -> StepExecutionResult:
        point = None
        search_score = None
        search_accepted = None
        preview_path = None
        message = "planned only"
        if step.mode == "fixed_point":
            point = self._safe_point(step.target_name)
            message = f"would click fixed point {point}" if point else "missing fixed point"
        elif step.mode == "search_target":
            message = "would wait for/search target on the live screen reached during execution"
        elif step.mode == "screen_check" and step.target_name == "reward_selection":
            if self.reward_selector is None:
                message = "reward selector service is not wired"
            else:
                message = (
                    "would select reward preference after Rebuild Workshop opens: "
                    "click gems if detected, otherwise use the calibrated default slider point"
                )
        verification = VerificationResult(step.verification_target, False, None, None, None, "Verification not attempted in planning.") if step.verification_target else None
        return StepExecutionResult(
            definition=step,
            outcome="planned",
            mode=mode,
            click_x=point[0] if point else None,
            click_y=point[1] if point else None,
            search_score=search_score,
            search_accepted=search_accepted,
            verification=verification,
            preview_path=preview_path,
            message=message,
        )

    def _run_reward_selection_step(
        self,
        step: CycleStepDefinition,
        *,
        mode: ExecutionMode,
        stop_event: Any | None = None,
    ) -> StepExecutionResult:
        if self.reward_selector is None:
            return StepExecutionResult(
                step,
                "skipped",
                mode,
                None,
                None,
                None,
                None,
                None,
                None,
                "Reward selector service is not wired; keeping previous cycle behavior.",
            )

        result = self.reward_selector.prepare_reward_selection(mode=mode, stop_event=stop_event)
        outcome = "success" if result.ok else "failed"
        if result.action in {"disabled_missing_calibration", "skip_default_already_selected"}:
            outcome = "skipped" if result.ok else "failed"

        return StepExecutionResult(
            step,
            outcome,
            mode,
            result.click_x,
            result.click_y,
            result.gems_score,
            result.gems_present,
            None,
            result.preview_path,
            (
                f"Reward selection: action={result.action}, selected={result.selected_reward}, "
                f"gems_present={'yes' if result.gems_present else 'no'}. {result.message}"
            ),
        )


    def _run_step(
        self,
        step: CycleStepDefinition,
        *,
        mode: ExecutionMode,
        step_delay_seconds: float,
        wait_timeout_seconds: float,
        poll_interval_seconds: float,
        stop_event: Any | None = None,
    ) -> StepExecutionResult:
        if step.mode == "fixed_point":
            return self._run_fixed_point_step(
                step,
                mode=mode,
                step_delay_seconds=step_delay_seconds,
                wait_timeout_seconds=wait_timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                stop_event=stop_event,
            )
        if step.mode == "search_target":
            return self._run_search_target_step(
                step,
                mode=mode,
                step_delay_seconds=step_delay_seconds,
                wait_timeout_seconds=wait_timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                stop_event=stop_event,
            )
        if step.mode == "screen_check" and step.target_name == "reward_selection":
            return self._run_reward_selection_step(
                step,
                mode=mode,
                stop_event=stop_event,
            )
        return StepExecutionResult(step, "skipped", mode, None, None, None, None, None, None, "Unsupported screen-check step in cycle runner.")

    def _run_fixed_point_step(
        self,
        step: CycleStepDefinition,
        *,
        mode: ExecutionMode,
        step_delay_seconds: float,
        wait_timeout_seconds: float,
        poll_interval_seconds: float,
        stop_event: Any | None = None,
    ) -> StepExecutionResult:
        if self._stop_requested(stop_event):
            return self._stop_step_result(step, mode, "Stop requested before fixed-point step.")

        actual_target_name = self._point_target_for_step(step.target_name)
        point = self._safe_point(actual_target_name)
        if point is None:
            return StepExecutionResult(step, "failed", mode, None, None, None, None, None, None, f"Missing point target: {actual_target_name}")

        x, y = point
        if mode == "click":
            if self._stop_requested(stop_event):
                return self._stop_step_result(step, mode, "Stop requested before fixed-point tap.")
            self.adb.tap(x, y)
            verification = self._wait_after_step(
                step,
                step_delay_seconds=step_delay_seconds,
                wait_timeout_seconds=wait_timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                stop_event=stop_event,
            )
            if verification and verification.passed is False:
                return StepExecutionResult(step, "failed", mode, x, y, None, None, verification, None, f"Clicked ({x}, {y}) but verification failed.")
            message = f"Clicked fixed point ({x}, {y})."
            if actual_target_name != step.target_name:
                message += f" Used {actual_target_name} for detected free-screen variant."
            if step.target_name == "free_button":
                self._last_free_button_target = "free_button"
            return StepExecutionResult(step, "success", mode, x, y, None, None, verification, None, message)

        verification = VerificationResult(step.verification_target, False, None, None, None, "Dry-run: verification not attempted.") if step.verification_target else None
        message = f"Dry-run: would click fixed point ({x}, {y})."
        if actual_target_name != step.target_name:
            message += f" Would use {actual_target_name} for detected free-screen variant."
        return StepExecutionResult(step, "planned", mode, x, y, None, None, verification, None, message)

    def _run_search_target_step(
        self,
        step: CycleStepDefinition,
        *,
        mode: ExecutionMode,
        step_delay_seconds: float,
        wait_timeout_seconds: float,
        poll_interval_seconds: float,
        stop_event: Any | None = None,
    ) -> StepExecutionResult:
        if self._stop_requested(stop_event):
            return self._stop_step_result(step, mode, "Stop requested before search-target step.")

        definition = get_search_target_definition(step.target_name)
        if definition is None:
            return StepExecutionResult(step, "failed", mode, None, None, None, None, None, None, f"Unknown search target: {step.target_name}")

        wait_result = self.waiter.wait_for_search_target(
            definition,
            timeout_seconds=wait_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            save_preview=True,
            stop_event=stop_event,
        )
        search = wait_result.search
        found = search.result if search else None
        accepted = wait_result.accepted
        x = found.center_x if found else None
        y = found.center_y if found else None
        score = found.score if found else None
        preview_path = search.preview_path if search else None

        if not accepted or x is None or y is None:
            return StepExecutionResult(
                step,
                "failed",
                mode,
                x,
                y,
                score,
                accepted,
                None,
                preview_path,
                wait_result.message,
            )

        if mode == "click":
            if self._stop_requested(stop_event):
                return self._stop_step_result(step, mode, "Stop requested before dynamic-target tap.")
            self.adb.tap(x, y)
            verification = self._wait_after_step(
                step,
                step_delay_seconds=step_delay_seconds,
                wait_timeout_seconds=wait_timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                stop_event=stop_event,
            )
            if verification and verification.passed is False:
                return StepExecutionResult(
                    step,
                    "failed",
                    mode,
                    x,
                    y,
                    score,
                    accepted,
                    verification,
                    preview_path,
                    f"Clicked dynamic target ({x}, {y}) but verification failed. {wait_result.message}",
                )
            return StepExecutionResult(
                step,
                "success",
                mode,
                x,
                y,
                score,
                accepted,
                verification,
                preview_path,
                f"Clicked dynamic target ({x}, {y}). {wait_result.message}",
            )

        verification = VerificationResult(step.verification_target, False, None, None, None, "Dry-run: verification not attempted.") if step.verification_target else None
        return StepExecutionResult(step, "planned", mode, x, y, score, accepted, verification, preview_path, f"Dry-run: would click dynamic target ({x}, {y}). {wait_result.message}")

    def _wait_after_step(
        self,
        step: CycleStepDefinition,
        *,
        step_delay_seconds: float,
        wait_timeout_seconds: float,
        poll_interval_seconds: float,
        stop_event: Any | None = None,
    ) -> VerificationResult | None:
        if not step.verification_target:
            return None
        if self._stop_requested(stop_event):
            return self._stop_verification(step.verification_target, "Stop requested before verification wait.")
        if step_delay_seconds > 0 and self._sleep_interruptible(step_delay_seconds, stop_event):
            return self._stop_verification(step.verification_target, "Stop requested during post-click delay.")
        if step.verification_target in {"free_button_check_area", "early_free_button_check_area"}:
            return self._wait_for_free_screen_variant(
                requested_target_name=step.verification_target,
                timeout_seconds=wait_timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                stop_event=stop_event,
            )

        return self.waiter.wait_for_verification(
            step.verification_target,
            timeout_seconds=wait_timeout_seconds,
            poll_interval_seconds=poll_interval_seconds,
            stop_event=stop_event,
        )

    def _wait_for_free_screen_variant(
        self,
        *,
        requested_target_name: str,
        timeout_seconds: float,
        poll_interval_seconds: float,
        stop_event: Any | None = None,
    ) -> VerificationResult:
        """Wait for either known Free-screen layout.

        Normal level 1:
            early_free_button_check_area -> early_free_button

        Alternate level 1:
            early_free_button_alt_check_area -> early_free_button_alt

        Normal level 2+:
            free_button_check_area -> free_button

        Alternate level 2+:
            free_button_alt_check_area -> free_button_alt

        Whichever check area passes determines which point the later
        "click free" step will tap.
        """
        import time

        variants = self._free_screen_variants_for_verification(requested_target_name)
        available = tuple(
            (check_name, point_name)
            for check_name, point_name in variants
            if self.calibration.has_area(check_name) and self.calibration.has_point(point_name)
        )
        if not available:
            return VerificationResult(
                target_name=requested_target_name,
                attempted=True,
                passed=False,
                score=None,
                threshold=None,
                message=(
                    "No usable Free-screen variants are calibrated for this cycle phase. Expected one of the configured normal/alternate Free-screen pairs."
                ),
                preview_path=None,
            )

        timeout_seconds = max(0.0, float(timeout_seconds))
        poll_interval_seconds = max(0.05, float(poll_interval_seconds))
        required_passes = 2
        minimum_wait_seconds = 0.90
        consecutive: dict[str, int] = {check_name: 0 for check_name, _ in available}
        last_result: VerificationResult | None = None
        started = time.monotonic()
        attempts = 0

        if minimum_wait_seconds > 0:
            if self._sleep_interruptible(min(minimum_wait_seconds, timeout_seconds), stop_event):
                return self._stop_verification(
                    requested_target_name,
                    "Stop requested during Free-screen variant minimum wait.",
                )

        while True:
            if self._stop_requested(stop_event):
                return self._stop_verification(
                    requested_target_name,
                    "Stop requested during Free-screen variant polling.",
                )

            attempts += 1
            screenshot = self.adb.capture()
            self._save_latest_screenshot(screenshot)
            elapsed = time.monotonic() - started

            for check_name, point_name in available:
                result = self.verifier.verify(check_name, screenshot=screenshot)
                last_result = result
                if result.passed is True:
                    consecutive[check_name] += 1
                else:
                    consecutive[check_name] = 0

                if result.passed is True and consecutive[check_name] >= required_passes:
                    selected_point = point_name
                    green_present, green_ratio = self._normal_free_check_has_green_headstart_ui(
                        screenshot,
                        check_name=check_name,
                        point_name=point_name,
                    )
                    alt_point = self._alt_free_point_for_normal_point(point_name)
                    used_green_guard = bool(green_present and alt_point and self.calibration.has_point(alt_point))
                    if used_green_guard:
                        selected_point = alt_point

                    self._last_free_button_target = selected_point
                    guard_message = ""
                    if green_present:
                        guard_message = (
                            f" Green head-start UI guard detected green_ratio={green_ratio:.4f}; "
                            f"using {selected_point}."
                        )
                    return VerificationResult(
                        target_name=check_name,
                        attempted=True,
                        passed=True,
                        score=result.score,
                        threshold=result.threshold,
                        message=(
                            f"Verification passed for Free-screen variant {check_name}; "
                            f"will click {selected_point}. attempts={attempts}, elapsed={elapsed:.2f}s, "
                            f"stable_passes={consecutive[check_name]}/{required_passes}. "
                            f"{result.message}{guard_message}"
                        ),
                        preview_path=result.preview_path,
                    )

            if elapsed >= timeout_seconds:
                last_message = last_result.message if last_result is not None else "No variant check was attempted."
                return VerificationResult(
                    target_name=requested_target_name,
                    attempted=True,
                    passed=False,
                    score=last_result.score if last_result is not None else None,
                    threshold=last_result.threshold if last_result is not None else None,
                    message=(
                        "Timed out waiting for either Free-screen variant "
                        f"({', '.join(name for name, _ in available)}). Last result: {last_message}"
                    ),
                    preview_path=last_result.preview_path if last_result is not None else None,
                )

            if self._sleep_interruptible(min(poll_interval_seconds, max(0.0, timeout_seconds - elapsed)), stop_event):
                return self._stop_verification(
                    requested_target_name,
                    "Stop requested during Free-screen variant poll wait.",
                )

    def _normal_free_check_has_green_headstart_ui(
        self,
        screenshot: Image.Image,
        *,
        check_name: str,
        point_name: str,
    ) -> tuple[bool, float]:
        """Detect the green head-start button inside a normal Free check area.

        The alternate Rebuild-with-head-start Free screen can partially match the
        normal Free check area because both layouts contain a blue Free button.
        The reliable difference is the green head-start button visible lower in
        the same normal check crop. If that green UI is present, use the alternate
        Free click point even if the normal Free check passed.
        """
        if point_name not in {"free_button", "early_free_button"}:
            return False, 0.0
        if not self.calibration.has_area(check_name):
            return False, 0.0

        try:
            area = self.calibration.get_area(check_name)
            crop = screenshot.crop((area.x, area.y, area.x + area.width, area.y + area.height)).convert("RGB")
            pixels = list(crop.getdata())
            if not pixels:
                return False, 0.0

            green_pixels = 0
            for red, green, blue in pixels:
                if (
                    green >= 120
                    and green - red >= 35
                    and green - blue >= 35
                    and green >= red * 1.20
                    and green >= blue * 1.10
                ):
                    green_pixels += 1

            ratio = green_pixels / len(pixels)
            return ratio >= 0.015 or green_pixels >= 100, ratio
        except Exception:
            return False, 0.0

    @staticmethod
    def _alt_free_point_for_normal_point(point_name: str) -> str | None:
        if point_name == "free_button":
            return "free_button_alt"
        if point_name == "early_free_button":
            return "early_free_button_alt"
        return None


    def _point_target_for_step(self, target_name: str) -> str:
        if target_name in {"free_button", "early_free_button"}:
            selected = self._last_free_button_target
            if selected in {"free_button_alt", "early_free_button_alt"} and self.calibration.has_point(selected):
                return selected
        return target_name

    @staticmethod
    def _free_screen_variants_for_verification(requested_target_name: str) -> tuple[tuple[str, str], ...]:
        # Prefer alternate checks first. The normal Free-screen check area can
        # partially match the alternate Rebuild-with-head-start screen because
        # both layouts contain a Free button. If the normal check is evaluated
        # first, the cycle may verify the alternate screen but still click the
        # normal free_button point. Checking the alternate marker first lets the
        # variant-specific point win when that layout is present.
        if requested_target_name == "early_free_button_check_area":
            return (
                ("early_free_button_alt_check_area", "early_free_button_alt"),
                ("early_free_button_check_area", "early_free_button"),
            )
        return (
            ("free_button_alt_check_area", "free_button_alt"),
            ("free_button_check_area", "free_button"),
        )


    @staticmethod
    def _stop_requested(stop_event: Any | None) -> bool:
        if stop_event is None:
            return False
        is_set = getattr(stop_event, "is_set", None)
        return bool(is_set()) if callable(is_set) else False

    @classmethod
    def _sleep_interruptible(cls, seconds: float, stop_event: Any | None) -> bool:
        import time

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
    def _stop_step_result(cls, step: CycleStepDefinition, mode: ExecutionMode, message: str) -> StepExecutionResult:
        verification = cls._stop_verification(step.verification_target, message) if step.verification_target else None
        return StepExecutionResult(
            definition=step,
            outcome="failed",
            mode=mode,
            click_x=None,
            click_y=None,
            search_score=None,
            search_accepted=None,
            verification=verification,
            preview_path=None,
            message=message,
        )

    def _safe_point(self, target_name: str) -> tuple[int, int] | None:
        target = get_target_definition(target_name)
        if target is None or target.kind != "point" or not self.calibration.has_point(target_name):
            return None
        point = self.calibration.get_point(target_name)
        return point.x, point.y

    def _save_latest_screenshot(self, screenshot: Image.Image) -> None:
        self.latest_screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot.save(self.latest_screenshot_path)

    @staticmethod
    def _level_confidence_is_safe(score: float | None, minimum: float) -> bool:
        return score is not None and score >= minimum

    @staticmethod
    def _trigger_reason(scan, *, force: bool) -> str:
        if force:
            return "manual_force"
        if scan.ready == "yes":
            return "ready_star_detected"
        if scan.ready == "no":
            return "not_ready"
        return "ready_state_unknown"
