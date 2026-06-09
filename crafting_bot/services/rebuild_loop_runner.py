from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from crafting_bot.domain.cycle_execution import CycleExecutionResult, ExecutionMode
from crafting_bot.domain.loop_execution import LoopIterationResult, LoopRunResult
from crafting_bot.domain.models import LevelScanResult
from crafting_bot.services.auto_digit_training_service import (
    AutoDigitTrainingResult,
    AutoDigitTrainingService,
    build_default_auto_digit_training_service,
)
from crafting_bot.services.cycle_runner import CycleRunner
from crafting_bot.services.expected_level_scanner import ExpectedLevelScanner
from crafting_bot.services.hire_runner import HireRunner
from crafting_bot.services.level_scanner import LevelScanner
from crafting_bot.services.reincarnation_runner import ReincarnationRunner


@dataclass(frozen=True)
class _AutoTrainCandidate:
    expected_level: int
    state: str
    crop_path: Path
    template_name: str
    template_score: float
    previous_levels: tuple[int, int]


class RebuildLoopRunner:
    """Runs the small unattended rebuild loop.

    This service owns repeated scans, same-level timing, expected-level tracking,
    assisted digit training, and stop limits. It delegates one-cycle click
    behavior to CycleRunner so cycle details remain independent from the loop
    and the GUI.
    """

    def __init__(
        self,
        *,
        scanner: LevelScanner,
        cycle_runner: CycleRunner,
        expected_scanner: ExpectedLevelScanner | None = None,
        auto_digit_trainer: AutoDigitTrainingService | None = None,
        reincarnation_runner: ReincarnationRunner | None = None,
        hire_runner: HireRunner | None = None,
    ) -> None:
        self.scanner = scanner
        self.expected_scanner = expected_scanner
        self.cycle_runner = cycle_runner
        self.auto_digit_trainer = auto_digit_trainer
        self.reincarnation_runner = reincarnation_runner
        self.hire_runner = hire_runner

    def run(
        self,
        *,
        mode: ExecutionMode = "dry_run",
        max_cycles: int = 3,
        desired_level: int | None = None,
        reincarnation_enabled: bool = False,
        hire_enabled: bool = False,
        hire_setup_level: int = 45,
        hire_drag_duration_ms: int = 750,
        stuck_seconds: float = 20.0,
        scan_interval_seconds: float = 1.0,
        max_runtime_seconds: float | None = None,
        stop_at_level: int | None = None,
        step_delay_seconds: float = 0.20,
        wait_timeout_seconds: float = 8.0,
        poll_interval_seconds: float = 0.25,
        min_digit_score_for_click: float = 0.50,
        allow_low_confidence_level: bool = False,
        stop_on_scan_failure: bool = True,
        stop_on_cycle_failure: bool = True,
        max_iterations: int = 500,
        assist_digit_training: bool = False,
        auto_train_missing_digits: bool = False,
        auto_train_ready_template_max_score: float = 0.16,
        stop_event: Any | None = None,
        on_iteration: Callable[[LoopIterationResult], None] | None = None,
    ) -> LoopRunResult:
        max_cycles = max(1, int(max_cycles))
        stuck_seconds = max(1.0, float(stuck_seconds))
        scan_interval_seconds = max(0.10, float(scan_interval_seconds))
        max_iterations = max(1, int(max_iterations))
        auto_train_ready_template_max_score = max(0.0, float(auto_train_ready_template_max_score))
        if desired_level is not None:
            desired_level = max(1, int(desired_level))
        hire_setup_level = max(1, int(hire_setup_level))
        hire_drag_duration_ms = max(100, int(hire_drag_duration_ms))

        started = time.monotonic()
        iterations: list[LoopIterationResult] = []
        cycles_completed = 0
        last_level: int | None = None
        same_level_started = started
        stopped_reason = "max_cycles_reached"
        confirmed_levels: list[int] = []
        cycle_start_levels: list[int] = []
        hire_done_this_climb = False

        for index in range(1, max_iterations + 1):
            if self._stop_requested(stop_event):
                stopped_reason = "stop_requested"
                break

            now = time.monotonic()
            runtime = now - started

            if max_runtime_seconds is not None and runtime >= max_runtime_seconds:
                stopped_reason = "max_runtime_reached"
                break

            if cycles_completed >= max_cycles:
                stopped_reason = "max_cycles_reached"
                break

            expected_level = self._expected_current_level(cycle_start_levels)
            scan = self._scan_with_tracking(expected_level)
            now = time.monotonic()

            if scan.ok and scan.level is None and (assist_digit_training or auto_train_missing_digits):
                candidate = self._build_auto_train_candidate(
                    scan,
                    cycle_start_levels=cycle_start_levels,
                    expected_level=expected_level,
                    max_ready_template_score=auto_train_ready_template_max_score,
                )
                if candidate is not None:
                    training_result = self._maybe_train_missing_digits(
                        candidate,
                        ask=assist_digit_training and not auto_train_missing_digits,
                    )
                    iteration = LoopIterationResult(
                        index=index,
                        action="wait" if training_result and training_result.ok else "failed",
                        scan=scan,
                        same_level_seconds=0.0,
                        trigger_reason="auto_digit_training",
                        cycle_result=None,
                        message=self._format_auto_train_iteration_message(candidate, training_result),
                    )
                    self._record_iteration(iterations, iteration, on_iteration)
                    if training_result is not None and training_result.ok:
                        # Use the saved failed crop for training, then do a fresh
                        # scan on the next iteration. This avoids acting on a
                        # stale scan result and keeps the loop's decision path simple.
                        if self._sleep_interruptible(scan_interval_seconds, stop_event):
                            stopped_reason = "stop_requested"
                            break
                        continue
                    if stop_on_scan_failure:
                        stopped_reason = "auto_digit_training_failed"
                        break
                    if self._sleep_interruptible(scan_interval_seconds, stop_event):
                        stopped_reason = "stop_requested"
                        break
                    continue

            if scan.ok and scan.level is not None:
                self._remember_confirmed_level(confirmed_levels, scan.level)

            if scan.ok and scan.level is None:
                iteration = LoopIterationResult(
                    index=index,
                    action="failed",
                    scan=scan,
                    same_level_seconds=0.0,
                    trigger_reason="unknown_level",
                    cycle_result=None,
                    message=(
                        "Level could not be read. In tracked mode this usually means the expected "
                        "level marker was visible but the digits need training. Enable "
                        "--assist-digit-training or --auto-train-missing-digits to train from the saved crop."
                    ),
                )
                self._record_iteration(iterations, iteration, on_iteration)
                if stop_on_scan_failure:
                    stopped_reason = "unknown_level"
                    break
                if self._sleep_interruptible(scan_interval_seconds, stop_event):
                    stopped_reason = "stop_requested"
                    break
                continue

            if not scan.ok:
                iteration = LoopIterationResult(
                    index=index,
                    action="failed",
                    scan=scan,
                    same_level_seconds=0.0,
                    trigger_reason="scan_failed",
                    cycle_result=None,
                    message=scan.message,
                )
                self._record_iteration(iterations, iteration, on_iteration)
                if stop_on_scan_failure:
                    stopped_reason = "scan_failed"
                    break
                if self._sleep_interruptible(scan_interval_seconds, stop_event):
                    stopped_reason = "stop_requested"
                    break
                continue

            if scan.level != last_level:
                last_level = scan.level
                same_level_started = now
            same_level_seconds = now - same_level_started

            if desired_level is not None and scan.level is not None:
                if reincarnation_enabled:
                    reincarnation_trigger_level = desired_level + 1
                    if scan.level >= reincarnation_trigger_level:
                        if self.reincarnation_runner is None:
                            iteration = LoopIterationResult(
                                index=index,
                                action="failed",
                                scan=scan,
                                same_level_seconds=same_level_seconds,
                                trigger_reason="reincarnation_runner_missing",
                                cycle_result=None,
                                message="Reincarnation is enabled but no ReincarnationRunner is configured.",
                            )
                            self._record_iteration(iterations, iteration, on_iteration)
                            stopped_reason = "reincarnation_runner_missing"
                            break

                        reincarnation_result = self.reincarnation_runner.run_once(
                            mode=mode,
                            step_delay_seconds=step_delay_seconds,
                            wait_timeout_seconds=wait_timeout_seconds,
                            poll_interval_seconds=poll_interval_seconds,
                            stop_event=stop_event,
                        )
                        reincarnation_success = (
                            reincarnation_result.eligible
                            and bool(reincarnation_result.steps)
                            and all(step.outcome in {"success", "planned"} for step in reincarnation_result.steps)
                        )
                        details = "; ".join(
                            f"{step.definition.action}: {step.outcome}" for step in reincarnation_result.steps
                        )
                        iteration = LoopIterationResult(
                            index=index,
                            action="reincarnate",
                            scan=scan,
                            same_level_seconds=same_level_seconds,
                            trigger_reason="desired_level_completed",
                            cycle_result=None,
                            message=(
                                f"Desired level {desired_level} is complete because visible level is {scan.level}. "
                                f"Reincarnation {'completed' if reincarnation_success else 'failed'}: "
                                f"{reincarnation_result.message} {details}"
                            ),
                        )
                        self._record_iteration(iterations, iteration, on_iteration)
                        if self._stop_requested(stop_event):
                            stopped_reason = "stop_requested"
                            break
                        if not reincarnation_success:
                            stopped_reason = "reincarnation_failed"
                            break

                        confirmed_levels.clear()
                        cycle_start_levels.clear()
                        hire_done_this_climb = False
                        last_level = None
                        same_level_started = time.monotonic()
                        if self._sleep_interruptible(scan_interval_seconds, stop_event):
                            stopped_reason = "stop_requested"
                            break
                        continue
                elif scan.level >= desired_level:
                    iteration = LoopIterationResult(
                        index=index,
                        action="stop",
                        scan=scan,
                        same_level_seconds=same_level_seconds,
                        trigger_reason="desired_level_reached",
                        cycle_result=None,
                        message=f"Desired level reached: level={scan.level}, desired_level={desired_level}.",
                    )
                    self._record_iteration(iterations, iteration, on_iteration)
                    stopped_reason = "desired_level_reached"
                    break


            if hire_enabled and not hire_done_this_climb and scan.level is not None and scan.level >= hire_setup_level:
                if self.hire_runner is None:
                    iteration = LoopIterationResult(
                        index=index,
                        action="failed",
                        scan=scan,
                        same_level_seconds=same_level_seconds,
                        trigger_reason="hire_runner_missing",
                        cycle_result=None,
                        message="Hire/setup is enabled but no HireRunner is configured.",
                    )
                    self._record_iteration(iterations, iteration, on_iteration)
                    stopped_reason = "hire_runner_missing"
                    break

                hire_result = self.hire_runner.run_once(
                    mode=mode,
                    setup_level=hire_setup_level,
                    drag_duration_ms=hire_drag_duration_ms,
                    step_delay_seconds=step_delay_seconds,
                    wait_timeout_seconds=wait_timeout_seconds,
                    poll_interval_seconds=poll_interval_seconds,
                    stop_event=stop_event,
                )
                hire_success = (
                    hire_result.eligible
                    and bool(hire_result.steps)
                    and all(step.outcome in {"success", "planned"} for step in hire_result.steps)
                )
                details = "; ".join(
                    f"{step.definition.action}: {step.outcome}" for step in hire_result.steps
                )
                iteration = LoopIterationResult(
                    index=index,
                    action="hire",
                    scan=scan,
                    same_level_seconds=same_level_seconds,
                    trigger_reason="hire_setup_level_reached",
                    cycle_result=None,
                    message=(
                        f"Hire/setup {'completed' if hire_success else 'failed'} at level {scan.level} "
                        f"(threshold={hire_setup_level}): {hire_result.message} {details}"
                    ),
                )
                self._record_iteration(iterations, iteration, on_iteration)
                if self._stop_requested(stop_event):
                    stopped_reason = "stop_requested"
                    break
                if not hire_success:
                    stopped_reason = "hire_failed"
                    break

                hire_done_this_climb = True
                # Bag/anvil navigation can slightly change the visual state. Force
                # a fresh scan/timer baseline before deciding whether to rebuild.
                last_level = None
                same_level_started = time.monotonic()
                if mode == "dry_run":
                    stopped_reason = "dry_run_planned_one_cycle"
                    break
                if self._sleep_interruptible(scan_interval_seconds, stop_event):
                    stopped_reason = "stop_requested"
                    break
                continue

            if stop_at_level is not None and scan.level is not None and scan.level >= stop_at_level:
                iteration = LoopIterationResult(
                    index=index,
                    action="stop",
                    scan=scan,
                    same_level_seconds=same_level_seconds,
                    trigger_reason="stop_at_level_reached",
                    cycle_result=None,
                    message=f"Stop-at-level reached: level={scan.level}, stop_at_level={stop_at_level}.",
                )
                self._record_iteration(iterations, iteration, on_iteration)
                stopped_reason = "stop_at_level_reached"
                break

            trigger_reason: str | None = None
            force_cycle = False
            if scan.ready == "yes":
                trigger_reason = "ready_star_detected"
            elif scan.level is not None and same_level_seconds >= stuck_seconds:
                trigger_reason = "same_level_timeout"
                force_cycle = True

            if trigger_reason is None:
                iteration = LoopIterationResult(
                    index=index,
                    action="wait",
                    scan=scan,
                    same_level_seconds=same_level_seconds,
                    trigger_reason="not_ready_waiting",
                    cycle_result=None,
                    message=(
                        f"Waiting: level={scan.level_text}, ready={scan.ready}, "
                        f"same_level_seconds={same_level_seconds:.1f}/{stuck_seconds:.1f}."
                    ),
                )
                self._record_iteration(iterations, iteration, on_iteration)
                if self._sleep_interruptible(scan_interval_seconds, stop_event):
                    stopped_reason = "stop_requested"
                    break
                continue

            cycle_start_level = scan.level
            cycle_result = self.cycle_runner.run_once(
                mode=mode,
                force=force_cycle or trigger_reason == "ready_star_detected",
                level_override=cycle_start_level,
                step_delay_seconds=step_delay_seconds,
                wait_timeout_seconds=wait_timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
                stop_on_failure=True,
                min_digit_score_for_click=min_digit_score_for_click,
                allow_low_confidence_level=allow_low_confidence_level,
                stop_event=stop_event,
            )
            if self._stop_requested(stop_event):
                stopped_reason = "stop_requested"
            success = self._cycle_result_is_success(cycle_result)
            tracking_advanced = False
            tracking_message = "expected-level tracking unchanged"
            if success:
                cycles_completed += 1
                if cycle_start_level is not None:
                    if trigger_reason == "ready_star_detected":
                        self._remember_confirmed_level(cycle_start_levels, cycle_start_level)
                        tracking_advanced = True
                        tracking_message = (
                            f"Ready-triggered cycle: level {cycle_start_level} is treated as completed; "
                            f"next expected level is {cycle_start_level + 1}."
                        )
                    elif trigger_reason == "same_level_timeout":
                        transition = self._infer_timeout_cycle_transition(
                            cycle_start_level=cycle_start_level,
                            max_template_score=auto_train_ready_template_max_score,
                        )
                        tracking_message = transition
                        if transition.startswith("Timeout-triggered cycle advanced"):
                            self._remember_confirmed_level(cycle_start_levels, cycle_start_level)
                            tracking_advanced = True
                # Force a fresh same-level baseline after the cycle. The next scan
                # will either see the new level or start timing the current one.
                last_level = None
                same_level_started = time.monotonic()

            iteration = LoopIterationResult(
                index=index,
                action="cycle" if success else "failed",
                scan=scan,
                same_level_seconds=same_level_seconds,
                trigger_reason=trigger_reason,
                cycle_result=cycle_result,
                message=(
                    f"Cycle {'completed' if success else 'failed'}: trigger={trigger_reason}, "
                    f"cycles_completed={cycles_completed}/{max_cycles}. "
                    f"expected_level_tracking_advanced={'yes' if tracking_advanced else 'no'}. "
                    f"{tracking_message}"
                ),
            )
            self._record_iteration(iterations, iteration, on_iteration)

            if stopped_reason == "stop_requested":
                break

            if not success and stop_on_cycle_failure:
                stopped_reason = "cycle_failed"
                break

            if mode == "dry_run":
                # Dry-run cannot advance the game. Stop after the first planned
                # cycle so it does not print the same plan repeatedly.
                stopped_reason = "dry_run_planned_one_cycle"
                break

            if self._sleep_interruptible(scan_interval_seconds, stop_event):
                stopped_reason = "stop_requested"
                break

        else:
            stopped_reason = "max_iterations_reached"

        runtime = time.monotonic() - started
        return LoopRunResult(
            mode=mode,
            max_cycles=max_cycles,
            cycles_completed=cycles_completed,
            runtime_seconds=runtime,
            stopped_reason=stopped_reason,
            iterations=tuple(iterations),
            message=(
                f"Loop stopped: {stopped_reason}. "
                f"cycles_completed={cycles_completed}/{max_cycles}, runtime={runtime:.1f}s."
                + (f" desired_level={desired_level}." if desired_level is not None else "")
                + (" reincarnation_enabled=yes." if reincarnation_enabled else "")
                + (f" hire_enabled=yes, hire_setup_level={hire_setup_level}." if hire_enabled else "")
            ),
        )

    def _expected_current_level(self, cycle_start_levels: list[int]) -> int | None:
        previous_two = self._last_two_consecutive_levels(cycle_start_levels)
        if previous_two is None:
            return None
        return previous_two[-1] + 1

    def _infer_timeout_cycle_transition(
        self,
        *,
        cycle_start_level: int,
        max_template_score: float,
    ) -> str:
        """Conservatively infer whether a timeout rebuild advanced a level.

        Timeout-triggered rebuilds usually mean the level did not complete yet.
        A false positive advance breaks expected-level tracking, so the default
        is to stay on the same level unless the post-cycle screen strongly and
        repeatedly proves the next level.
        """
        same_level = int(cycle_start_level)
        next_level = same_level + 1

        # Prefer evidence that the level did *not* advance. Staying on the same
        # level one extra cycle is safe; jumping tracking forward incorrectly is not.
        same_scan = self._scan_expected_for_transition(same_level)
        if same_scan is not None and same_scan.ok and same_scan.level == same_level:
            return (
                f"Timeout-triggered cycle did not advance: expected scan read current level {same_level}. "
                f"Tracking remains on level {same_level}."
            )
        if self._scan_has_level_or_marker(
            same_scan,
            expected_level=same_level,
            max_template_score=max_template_score,
        ):
            return (
                f"Timeout-triggered cycle did not advance: current-level marker matched level {same_level}. "
                f"Tracking remains on level {same_level}."
            )

        broad_scan = self.scanner.scan()
        if broad_scan.ok and broad_scan.level == same_level:
            return (
                f"Timeout-triggered cycle did not advance: broad post-cycle scan read level {same_level}. "
                f"Tracking remains on level {same_level}."
            )

        # Advance only when independent evidence agrees on the next level and no
        # current-level marker was found. Do not advance from a marker-only match.
        next_scan_1 = self._scan_expected_for_transition(next_level)
        if not (next_scan_1 is not None and next_scan_1.ok and next_scan_1.level == next_level):
            broad_detail = broad_scan.level_text if broad_scan.ok else "scan failed"
            return (
                f"Timeout-triggered cycle advance unknown: next level {next_level} was not strongly confirmed "
                f"(broad={broad_detail}). Tracking remains on level {same_level}."
            )

        # Re-check current level once more before allowing the rare advancement.
        same_scan_2 = self._scan_expected_for_transition(same_level)
        if self._scan_has_level_or_marker(
            same_scan_2,
            expected_level=same_level,
            max_template_score=max_template_score,
        ):
            return (
                f"Timeout-triggered cycle did not advance: second current-level check still matched {same_level}. "
                f"Tracking remains on level {same_level}."
            )

        next_scan_2 = self._scan_expected_for_transition(next_level)
        if next_scan_2 is not None and next_scan_2.ok and next_scan_2.level == next_level:
            if broad_scan.ok and broad_scan.level not in {None, next_level}:
                return (
                    f"Timeout-triggered cycle advance unknown: expected scans read {next_level}, but broad scan read "
                    f"{broad_scan.level_text}. Tracking remains on level {same_level}."
                )
            return (
                f"Timeout-triggered cycle advanced: two expected scans read next level {next_level}. "
                f"Tracking now treats level {same_level} as completed."
            )

        return (
            f"Timeout-triggered cycle advance unknown: next level {next_level} was not stable across two scans. "
            f"Tracking remains on level {same_level}."
        )

    def _scan_expected_for_transition(self, expected_level: int) -> LevelScanResult | None:
        if self.expected_scanner is None:
            return None
        return self.expected_scanner.scan_expected(expected_level)

    @staticmethod
    def _scan_has_level_or_marker(
        scan: LevelScanResult | None,
        *,
        expected_level: int,
        max_template_score: float,
    ) -> bool:
        if scan is None or not scan.ok:
            return False
        if scan.level == expected_level:
            return True
        if scan.ready not in {"yes", "no"}:
            return False
        if scan.ready_score is None:
            return False
        return scan.ready_score <= max_template_score

    def _scan_with_tracking(self, expected_level: int | None) -> LevelScanResult:
        if expected_level is not None and self.expected_scanner is not None:
            return self.expected_scanner.scan_expected(expected_level)
        return self.scanner.scan()

    def _build_auto_train_candidate(
        self,
        scan: LevelScanResult,
        *,
        cycle_start_levels: list[int],
        expected_level: int | None,
        max_ready_template_score: float,
    ) -> _AutoTrainCandidate | None:
        """Build a safe assisted-training candidate for an unreadable level.

        Important: the ready-template filename is intentionally *not* used to
        infer the level number. Full-badge ready templates can match a nearby
        or visually similar level, e.g. a live level 25 may report a 023_*
        ready template.

        The expected level comes from the last two successful cycle start levels,
        not from the post-cycle level scan. Example: if the loop successfully
        cycled ready levels 30 and 31, then an unreadable next screen is expected
        to be level 32. This prevents the loop from counting the level reached
        after a cycle as if it had already been completed.

        The ready-template match is used only as a screen/state confidence signal.
        """
        if scan.level is not None or not scan.level_crop_path:
            return None
        if scan.ready_template is None or scan.ready_score is None:
            return None
        if scan.ready_score > max_ready_template_score:
            return None

        previous_two = self._last_two_consecutive_levels(cycle_start_levels)
        if previous_two is None:
            return None

        state = self._state_from_scan(scan)
        if state is None:
            return None

        expected_next = expected_level if expected_level is not None else previous_two[-1] + 1
        return _AutoTrainCandidate(
            expected_level=expected_next,
            state=state,
            crop_path=scan.level_crop_path,
            template_name=scan.ready_template or "expected-level-marker",
            template_score=scan.ready_score,
            previous_levels=previous_two,
        )

    def _maybe_train_missing_digits(
        self,
        candidate: _AutoTrainCandidate,
        *,
        ask: bool,
    ) -> AutoDigitTrainingResult | None:
        if ask:
            print("\nDigit training assist")
            print("-" * 80)
            print(f"Previous completed cycle start levels: {candidate.previous_levels[0]}, {candidate.previous_levels[1]}")
            print(f"Expected current level: {candidate.expected_level}")
            print(f"Ready template: {candidate.template_name}")
            print(f"Ready score: {candidate.template_score:.4f}")
            print(f"State to train: {candidate.state}")
            print(f"Saved failed crop: {candidate.crop_path}")
            answer = input("Train digit templates from this saved crop? [y/N] ").strip().lower()
            if answer not in {"y", "yes"}:
                return None

        trainer = self.auto_digit_trainer or build_default_auto_digit_training_service()
        return trainer.train_from_crop(
            crop_path=candidate.crop_path,
            expected_level=candidate.expected_level,
            state=candidate.state,
            source_label="loop_auto",
        )

    @staticmethod
    def _state_from_scan(scan: LevelScanResult) -> str | None:
        if scan.ready == "yes":
            return "ready"
        if scan.ready == "no":
            return "not_ready"
        return None

    @staticmethod
    def _record_iteration(
        iterations: list[LoopIterationResult],
        iteration: LoopIterationResult,
        callback: Callable[[LoopIterationResult], None] | None,
    ) -> None:
        iterations.append(iteration)
        if callback is None:
            return
        try:
            callback(iteration)
        except Exception:
            # Progress callbacks are observational only; never let a UI/logging
            # issue change the bot behavior.
            return

    @staticmethod
    def _stop_requested(stop_event: Any | None) -> bool:
        if stop_event is None:
            return False
        is_set = getattr(stop_event, "is_set", None)
        if callable(is_set):
            return bool(is_set())
        return False

    @classmethod
    def _sleep_interruptible(cls, seconds: float, stop_event: Any | None) -> bool:
        deadline = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < deadline:
            if cls._stop_requested(stop_event):
                return True
            time.sleep(min(0.10, max(0.0, deadline - time.monotonic())))
        return cls._stop_requested(stop_event)

    @staticmethod
    def _remember_confirmed_level(levels: list[int], level: int) -> None:
        if levels and levels[-1] == level:
            return
        levels.append(level)
        del levels[:-6]

    @staticmethod
    def _last_two_consecutive_levels(levels: list[int]) -> tuple[int, int] | None:
        if len(levels) < 2:
            return None
        previous, current = levels[-2], levels[-1]
        if current == previous + 1:
            return previous, current
        return None

    @staticmethod
    def _format_auto_train_iteration_message(
        candidate: _AutoTrainCandidate,
        result: AutoDigitTrainingResult | None,
    ) -> str:
        base = (
            f"Unknown level but previous completed cycle start levels {candidate.previous_levels[0]} "
            f"and {candidate.previous_levels[1]} imply current level {candidate.expected_level}. "
            f"Template {candidate.template_name} passed as a {candidate.state} screen marker "
            f"with score {candidate.template_score:.4f}; its filename level is not trusted. "
        )
        if result is None:
            return base + "Digit training was skipped by user."
        return base + result.message

    @staticmethod
    def _cycle_result_is_success(result: CycleExecutionResult) -> bool:
        if result.cycle is None or not result.eligible:
            return False
        if not result.steps:
            return False
        return all(step.outcome in {"success", "planned"} for step in result.steps)
