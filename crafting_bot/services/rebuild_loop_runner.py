from __future__ import annotations

import hashlib
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
from crafting_bot.services.cycle_outcome_confirmer import CycleOutcomeConfirmer
from crafting_bot.services.cycle_runner import CycleRunner
from crafting_bot.services.expected_level_scanner import ExpectedLevelScanner
from crafting_bot.services.hire_runner import HireRunner
from crafting_bot.services.level_continuity_guard import LevelContinuityGuard
from crafting_bot.services.level_scanner import LevelScanner
from crafting_bot.services.reincarnation_runner import ReincarnationRunner
from crafting_bot.services.recovery_runner import RecoveryRunner


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
        recovery_runner: RecoveryRunner | None = None,
        cycle_outcome_confirmer: CycleOutcomeConfirmer | None = None,
        level_continuity_guard: LevelContinuityGuard | None = None,
    ) -> None:
        self.scanner = scanner
        self.expected_scanner = expected_scanner
        self.cycle_runner = cycle_runner
        self.auto_digit_trainer = auto_digit_trainer
        self.reincarnation_runner = reincarnation_runner
        self.hire_runner = hire_runner
        self.recovery_runner = recovery_runner
        self.cycle_outcome_confirmer = cycle_outcome_confirmer or CycleOutcomeConfirmer(scanner)
        self.level_continuity_guard = level_continuity_guard or LevelContinuityGuard()

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
        trusted_level: int | None = None
        same_level_started = started
        stopped_reason = "max_cycles_reached"
        confirmed_levels: list[int] = []
        cycle_start_levels: list[int] = []
        hire_done_this_climb = False
        auto_digit_training_signatures: set[tuple[int, str, str]] = set()

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

            continuity_decision = self.level_continuity_guard.evaluate(
                scan,
                trusted_level=trusted_level,
                expected_level=expected_level,
            )
            continuity_note = ""
            raw_scan_level_for_trust = scan.level if scan.ok else None
            if continuity_decision.quarantined:
                scan = self.level_continuity_guard.apply_effective_scan(scan, continuity_decision)
                continuity_note = " " + continuity_decision.message

            if (
                scan.ok
                and scan.level is None
                and desired_level is not None
                and reincarnation_enabled
                and expected_level is not None
                and expected_level >= desired_level
            ):
                # At the reincarnation boundary, an unknown level must not trigger
                # digit auto-training for the old expected level. Example:
                # desired level 82 is complete once visible level is 83. If tracking
                # is still expecting 82 and the live screen is actually 83, training
                # "level 82" from that crop pollutes the templates and can repeat
                # indefinitely. First try one broad scan; if that cannot prove the
                # level, stop safely and ask for inspection instead of training.
                broad_boundary_scan = self.scanner.scan()
                if broad_boundary_scan.ok and broad_boundary_scan.level is not None:
                    scan = broad_boundary_scan
                else:
                    iteration = LoopIterationResult(
                        index=index,
                        action="failed",
                        scan=scan,
                        same_level_seconds=0.0,
                        trigger_reason="reincarnation_boundary_unknown_level",
                        cycle_result=None,
                        message=(
                            f"Stopped before digit auto-training at reincarnation boundary. "
                            f"desired_level={desired_level}, expected_level={expected_level}, "
                            f"reincarnation trigger level={desired_level + 1}. The tracked scan could not "
                            "read the level, and a broad scan also could not prove the current level. "
                            "This prevents training the previous level from a post-target crop."
                        ),
                    )
                    self._record_iteration(iterations, iteration, on_iteration)
                    stopped_reason = "reincarnation_boundary_unknown_level"
                    break

            if scan.ok and scan.level is None and (assist_digit_training or auto_train_missing_digits):
                candidate = self._build_auto_train_candidate(
                    scan,
                    cycle_start_levels=cycle_start_levels,
                    expected_level=expected_level,
                    max_ready_template_score=auto_train_ready_template_max_score,
                )
                if candidate is not None:
                    signature = self._auto_train_signature(candidate)
                    if signature in auto_digit_training_signatures:
                        iteration = LoopIterationResult(
                            index=index,
                            action="failed",
                            scan=scan,
                            same_level_seconds=0.0,
                            trigger_reason="repeated_auto_digit_training_candidate",
                            cycle_result=None,
                            message=(
                                "Stopped to prevent repeated digit auto-training from the same crop/signature. "
                                f"expected_level={candidate.expected_level}, state={candidate.state}, "
                                f"crop_hash={signature[2]}. This usually means training did not fix recognition "
                                "or tracking is expecting the wrong level."
                            ),
                        )
                        self._record_iteration(iterations, iteration, on_iteration)
                        stopped_reason = "repeated_auto_digit_training_candidate"
                        break

                    auto_digit_training_signatures.add(signature)
                    training_result = self._maybe_train_missing_digits(
                        candidate,
                        ask=assist_digit_training and not auto_train_missing_digits,
                    )
                    reload_message = ""
                    if training_result is not None and training_result.ok:
                        reload_message = self._reload_digit_templates_after_training()

                    iteration = LoopIterationResult(
                        index=index,
                        action="wait" if training_result and training_result.ok else "failed",
                        scan=scan,
                        same_level_seconds=0.0,
                        trigger_reason="auto_digit_training",
                        cycle_result=None,
                        message=(
                            self._format_auto_train_iteration_message(candidate, training_result)
                            + reload_message
                        ),
                    )
                    self._record_iteration(iterations, iteration, on_iteration)
                    if training_result is not None and training_result.ok:
                        # Use the saved failed crop for training, reload digit
                        # templates in the live scanners, then do a fresh scan on
                        # the next iteration. This avoids acting on a stale scan
                        # result and ensures the loop can immediately use the
                        # newly saved templates without requiring a GUI restart.
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

            if (
                scan.ok
                and raw_scan_level_for_trust is not None
                and continuity_decision.accepted
            ):
                trusted_level = int(raw_scan_level_for_trust)
                self._remember_confirmed_level(confirmed_levels, trusted_level)

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
                recovered = self._attempt_safe_recovery(
                    index=index,
                    mode=mode,
                    context="general",
                    scan=scan,
                    same_level_seconds=0.0,
                    trigger_reason="unknown_level",
                    iterations=iterations,
                    callback=on_iteration,
                    stop_event=stop_event,
                )
                if recovered:
                    self._reset_tracking_after_recovery(confirmed_levels, cycle_start_levels)
                    trusted_level = None
                    last_level = None
                    same_level_started = time.monotonic()
                    if self._sleep_interruptible(scan_interval_seconds, stop_event):
                        stopped_reason = "stop_requested"
                        break
                    continue
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
                recovered = self._attempt_safe_recovery(
                    index=index,
                    mode=mode,
                    context="general",
                    scan=scan,
                    same_level_seconds=0.0,
                    trigger_reason="scan_failed",
                    iterations=iterations,
                    callback=on_iteration,
                    stop_event=stop_event,
                )
                if recovered:
                    self._reset_tracking_after_recovery(confirmed_levels, cycle_start_levels)
                    trusted_level = None
                    last_level = None
                    same_level_started = time.monotonic()
                    if self._sleep_interruptible(scan_interval_seconds, stop_event):
                        stopped_reason = "stop_requested"
                        break
                    continue
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
                            recovered = self._attempt_safe_recovery(
                                index=index,
                                mode=mode,
                                context="reincarnation",
                                scan=scan,
                                same_level_seconds=same_level_seconds,
                                trigger_reason="reincarnation_failed",
                                iterations=iterations,
                                callback=on_iteration,
                                stop_event=stop_event,
                            )
                            if recovered:
                                last_level = None
                                same_level_started = time.monotonic()
                                if self._sleep_interruptible(scan_interval_seconds, stop_event):
                                    stopped_reason = "stop_requested"
                                    break
                                continue
                            stopped_reason = "reincarnation_failed"
                            break

                        confirmed_levels.clear()
                        cycle_start_levels.clear()
                        trusted_level = None
                        hire_done_this_climb = False
                        last_level = None
                        same_level_started = time.monotonic()
                        if self._sleep_interruptible(scan_interval_seconds, stop_event):
                            stopped_reason = "stop_requested"
                            break
                        continue
            if hire_enabled and not hire_done_this_climb and scan.level is not None and scan.level == hire_setup_level:
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
                    recovered = self._attempt_safe_recovery(
                        index=index,
                        mode=mode,
                        context="hire",
                        scan=scan,
                        same_level_seconds=same_level_seconds,
                        trigger_reason="hire_failed",
                        iterations=iterations,
                        callback=on_iteration,
                        stop_event=stop_event,
                    )
                    if recovered:
                        last_level = None
                        same_level_started = time.monotonic()
                        if self._sleep_interruptible(scan_interval_seconds, stop_event):
                            stopped_reason = "stop_requested"
                            break
                        continue
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
                        f"{continuity_note}"
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
                iteration = LoopIterationResult(
                    index=index,
                    action="stop_requested",
                    scan=scan,
                    same_level_seconds=same_level_seconds,
                    trigger_reason=trigger_reason,
                    cycle_result=cycle_result,
                    message=(
                        "Stop requested during or immediately after cycle execution. "
                        "Skipping post-cycle confirmation and failure handling."
                    ),
                )
                self._record_iteration(iterations, iteration, on_iteration)
                break

            raw_cycle_success = self._cycle_result_is_success(cycle_result)
            success = raw_cycle_success
            timeout_failure_confirmed_same_level = False
            ready_failure_confirmed_no_progress = False
            ready_failure_confirmed_advanced = False
            timeout_failure_message = ""
            ready_failure_message = ""
            tracking_advanced = False
            tracking_message = "expected-level tracking unchanged"

            post_cycle_confirmed_advanced = False
            post_cycle_confirmed_no_progress = False
            post_cycle_message = "expected-level tracking unchanged"

            if mode == "click":
                confirmation = self.cycle_outcome_confirmer.confirm(
                    cycle_start_level=cycle_start_level,
                    trigger_reason=trigger_reason,
                    min_digit_score=min_digit_score_for_click,
                    allow_low_confidence_level=allow_low_confidence_level,
                )
                post_cycle_message = confirmation.message

                if self._stop_requested(stop_event):
                    stopped_reason = "stop_requested"
                    iteration = LoopIterationResult(
                        index=index,
                        action="stop_requested",
                        scan=scan,
                        same_level_seconds=same_level_seconds,
                        trigger_reason=trigger_reason,
                        cycle_result=cycle_result,
                        message=(
                            "Stop requested during post-cycle confirmation. "
                            "Ignoring confirmation failure and stopping cleanly."
                        ),
                    )
                    self._record_iteration(iterations, iteration, on_iteration)
                    break

                if confirmation.advanced:
                    success = True
                    post_cycle_confirmed_advanced = True
                    cycles_completed += 1
                    if cycle_start_level is not None:
                        self._remember_confirmed_level(cycle_start_levels, cycle_start_level)
                    trusted_level = confirmation.expected_next_level
                    tracking_advanced = True
                    tracking_message = post_cycle_message
                    last_level = None
                    same_level_started = time.monotonic()

                elif confirmation.same_level:
                    # Safe no-progress outcome. This covers high-level timeout
                    # attempts that need several passes and false-ready clicks
                    # that returned to the same readable level. Do not count a
                    # rebuild and do not advance expected-level tracking.
                    success = False
                    post_cycle_confirmed_no_progress = True
                    tracking_message = post_cycle_message
                    trusted_level = confirmation.start_level
                    last_level = None
                    same_level_started = time.monotonic()

                else:
                    success = False
                    tracking_message = post_cycle_message

            else:
                # Dry-run cannot move the game, so keep the planned-cycle result
                # and do not perform post-cycle confirmation scans.
                if success:
                    cycles_completed += 1
                    if cycle_start_level is not None:
                        self._remember_confirmed_level(cycle_start_levels, cycle_start_level)
                        tracking_advanced = True
                        tracking_message = (
                            f"Dry-run planned cycle for level {cycle_start_level}; "
                            f"next expected level would be {cycle_start_level + 1}."
                        )
                last_level = None
                same_level_started = time.monotonic()

            nonfatal_no_progress = post_cycle_confirmed_no_progress
            iteration_action = "cycle" if success or nonfatal_no_progress else "failed"
            iteration_trigger = trigger_reason
            if post_cycle_confirmed_no_progress:
                iteration_trigger = f"{trigger_reason}_confirmed_no_progress"
            elif post_cycle_confirmed_advanced:
                iteration_trigger = f"{trigger_reason}_confirmed_advanced"

            cycle_state_text = (
                "completed"
                if success
                else "did not advance safely"
                if nonfatal_no_progress
                else "failed"
            )

            iteration = LoopIterationResult(
                index=index,
                action=iteration_action,
                scan=scan,
                same_level_seconds=same_level_seconds,
                trigger_reason=iteration_trigger,
                cycle_result=cycle_result,
                message=(
                    f"Cycle {cycle_state_text}: trigger={trigger_reason}, "
                    f"cycles_completed={cycles_completed}/{max_cycles}. "
                    f"expected_level_tracking_advanced={'yes' if tracking_advanced else 'no'}. "
                    f"{tracking_message}{continuity_note}"
                ),
            )
            self._record_iteration(iterations, iteration, on_iteration)

            if stopped_reason == "stop_requested":
                break

            if not success and post_cycle_confirmed_no_progress:
                if self._sleep_interruptible(scan_interval_seconds, stop_event):
                    stopped_reason = "stop_requested"
                    break
                continue

            if not raw_cycle_success and post_cycle_confirmed_advanced:
                if mode == "dry_run":
                    stopped_reason = "dry_run_planned_one_cycle"
                    break
                if self._sleep_interruptible(scan_interval_seconds, stop_event):
                    stopped_reason = "stop_requested"
                    break
                continue

            if not success and stop_on_cycle_failure:
                recovered = self._attempt_safe_recovery(
                    index=index,
                    mode=mode,
                    context="rebuild",
                    scan=scan,
                    same_level_seconds=same_level_seconds,
                    trigger_reason="cycle_failed",
                    iterations=iterations,
                    callback=on_iteration,
                    stop_event=stop_event,
                )
                if recovered:
                    self._reset_tracking_after_recovery(confirmed_levels, cycle_start_levels)
                    trusted_level = None
                    last_level = None
                    same_level_started = time.monotonic()
                    if self._sleep_interruptible(scan_interval_seconds, stop_event):
                        stopped_reason = "stop_requested"
                        break
                    continue
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
                + (f" desired_level={desired_level}." if desired_level is not None and reincarnation_enabled else "")
                + (" reincarnation_enabled=yes." if reincarnation_enabled else "")
                + (f" hire_enabled=yes, hire_setup_level={hire_setup_level}." if hire_enabled else "")
            ),
        )


    def _confirm_transition_after_ready_failure(
        self,
        *,
        cycle_start_level: int | None,
        min_digit_score: float,
        allow_low_confidence_level: bool,
    ) -> tuple[bool, bool, str]:
        """Confirm what happened after a failed ready-triggered cycle.

        At high levels, the cycle runner can mark a ready-triggered rebuild as
        failed even though the game already returned to LEVEL_SCREEN and the
        visible level advanced. This can happen when one verification step is
        too strict or the final screen settles after the runner gives up.

        Returns:
            (advanced, no_progress, message)
        """
        if cycle_start_level is None:
            return False, False, "Ready-triggered cycle failed and no start level was available to confirm."

        next_level = cycle_start_level + 1
        scans: list[LevelScanResult] = []
        for _ in range(2):
            scan = self.scanner.scan()
            scans.append(scan)

            if not scan.ok:
                return False, False, f"Ready-triggered cycle failed; confirmation scan failed: {scan.message}"

            if scan.screen != "LEVEL_SCREEN":
                return False, False, (
                    "Ready-triggered cycle failed; confirmation scan did not see LEVEL_SCREEN "
                    f"(screen={scan.screen})."
                )

            if not allow_low_confidence_level and not self._digit_confidence_is_safe(scan.digit_score, min_digit_score):
                return False, False, (
                    "Ready-triggered cycle failed; level was read but digit confidence was too low "
                    f"(read={scan.level_text}, score={scan.digit_score}, required>={min_digit_score:.3f})."
                )

            if scan.level not in {cycle_start_level, next_level}:
                return False, False, (
                    "Ready-triggered cycle failed; confirmation scan read an unexpected level "
                    f"(start={cycle_start_level}, expected_next={next_level}, read={scan.level_text})."
                )

            time.sleep(0.10)

        levels = [scan.level for scan in scans]
        scores = ", ".join(str(scan.digit_score) for scan in scans)

        if all(level == next_level for level in levels):
            return (
                True,
                False,
                (
                    f"Ready-triggered cycle was marked failed, but two fresh scans confirmed "
                    f"LEVEL_SCREEN at next level {next_level} with digit scores [{scores}]. "
                    "Treating the rebuild as completed and continuing."
                ),
            )

        if all(level == cycle_start_level for level in levels):
            return (
                False,
                True,
                (
                    f"Ready-triggered cycle was marked failed, but two fresh scans confirmed "
                    f"LEVEL_SCREEN still at level {cycle_start_level} with digit scores [{scores}]. "
                    "Treating this as a non-fatal false-ready/no-progress attempt and continuing."
                ),
            )

        return (
            False,
            False,
            (
                "Ready-triggered cycle failed; confirmation scans were not stable "
                f"(levels={levels}, start={cycle_start_level}, expected_next={next_level})."
            ),
        )


    def _confirm_same_level_after_timeout_failure(
        self,
        *,
        cycle_start_level: int | None,
        min_digit_score: float,
        allow_low_confidence_level: bool,
    ) -> tuple[bool, str]:
        """Decide whether a failed timeout-triggered cycle is safe to ignore.

        On high levels, the same level can need several timeout rebuild attempts
        before it actually advances. A failed timeout attempt is only non-fatal
        if fresh scans prove that the bot is still on LEVEL_SCREEN and the same
        level number is being read with acceptable digit confidence.

        This avoids a hard "two cycle" limit while still stopping/recovering if
        the bot is on an unexpected screen or the level read is not trustworthy.
        """
        if cycle_start_level is None:
            return False, "Timeout-triggered cycle failed and no start level was available to confirm."

        scans: list[LevelScanResult] = []
        for _ in range(2):
            scan = self.scanner.scan()
            scans.append(scan)
            if not scan.ok:
                return False, f"Timeout-triggered cycle failed; confirmation scan failed: {scan.message}"
            if scan.screen != "LEVEL_SCREEN":
                return False, (
                    "Timeout-triggered cycle failed; confirmation scan did not see LEVEL_SCREEN "
                    f"(screen={scan.screen})."
                )
            if scan.level != cycle_start_level:
                return False, (
                    "Timeout-triggered cycle failed; confirmation scan did not read the same level "
                    f"(expected={cycle_start_level}, read={scan.level_text})."
                )
            if not allow_low_confidence_level and not self._digit_confidence_is_safe(scan.digit_score, min_digit_score):
                return False, (
                    "Timeout-triggered cycle failed; same level was read but digit confidence was too low "
                    f"(score={scan.digit_score}, required>={min_digit_score:.3f})."
                )
            time.sleep(0.10)

        scores = ", ".join(str(scan.digit_score) for scan in scans)
        return (
            True,
            (
                f"Timeout-triggered cycle failed but two fresh scans confirmed LEVEL_SCREEN at level "
                f"{cycle_start_level} with digit scores [{scores}]. Treating this as a non-fatal "
                "no-progress timeout attempt and continuing."
            ),
        )

    @staticmethod
    def _digit_confidence_is_safe(score: float | None, minimum: float) -> bool:
        return score is not None and float(score) >= float(minimum)


    @staticmethod
    def _reset_tracking_after_recovery(
        confirmed_levels: list[int],
        cycle_start_levels: list[int],
    ) -> None:
        # Recovery may have used ESC/BACK or completed a partially finished
        # cycle. After returning to LEVEL_SCREEN, throw away expected-level
        # history and let the next scan behave like a fresh start.
        confirmed_levels.clear()
        cycle_start_levels.clear()


    def _attempt_safe_recovery(
        self,
        *,
        index: int,
        mode: ExecutionMode,
        context: str,
        scan: LevelScanResult,
        same_level_seconds: float,
        trigger_reason: str,
        iterations: list[LoopIterationResult],
        callback: Callable[[LoopIterationResult], None] | None,
        stop_event: Any | None,
    ) -> bool:
        """Try one bounded safe recovery action and report it as an iteration.

        This integration runs one bounded recovery action. Rebuild-context recovery
        can finish Take Reward / Free screens forward; other navigation recovery
        returns to LEVEL_SCREEN with slow BACK/ESC handling.
        """
        if mode != "click":
            return False
        if self.recovery_runner is None:
            return False
        if self._stop_requested(stop_event):
            return False

        try:
            result = self.recovery_runner.run(
                context=context,  # type: ignore[arg-type]
                execute=True,
                allow_forward_clicks=(context == "rebuild"),
                current_level=scan.level,
            )
        except Exception as exc:
            iteration = LoopIterationResult(
                index=index,
                action="recovery",
                scan=scan,
                same_level_seconds=same_level_seconds,
                trigger_reason=f"{trigger_reason}_recovery_error",
                cycle_result=None,
                message=f"Safe recovery failed before execution: {exc}",
            )
            self._record_iteration(iterations, iteration, callback)
            return False

        before_screen = result.before.screen
        after_screen = result.after.screen if result.after is not None else "UNKNOWN"
        executed = result.execution.action_executed if result.execution is not None else "dry_run"
        exec_message = result.execution.message if result.execution is not None else "No execution result."

        recovered_to_level = bool(
            result.ok
            and result.after is not None
            and result.after.screen == "LEVEL_SCREEN"
            and executed not in {"none", "resume", "blocked", "unsupported", "dry_run"}
        )

        iteration = LoopIterationResult(
            index=index,
            action="recovery",
            scan=scan,
            same_level_seconds=same_level_seconds,
            trigger_reason=f"{trigger_reason}_safe_recovery",
            cycle_result=None,
            message=(
                f"Recovery attempted after {trigger_reason}: "
                f"before={before_screen}, action={result.decision.action}, executed={executed}, "
                f"after={after_screen}, recovered_to_level={'yes' if recovered_to_level else 'no'}, "
                f"report={result.report_path}. {exec_message}"
            ),
        )
        self._record_iteration(iterations, iteration, callback)
        return recovered_to_level


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

    def _reload_digit_templates_after_training(self) -> str:
        """Reload digit readers after loop auto-training saves new templates.

        The scanners keep DigitReader instances in memory. Without reloading,
        the next scan can still use the old template list, see the same crop as
        unreadable, and trip the duplicate-training guard even though training
        successfully wrote good templates to disk.
        """
        reloaded: list[str] = []
        failed: list[str] = []

        scanner_pairs = [
            ("scanner", self.scanner),
            ("expected_scanner", self.expected_scanner),
        ]

        for name, scanner in scanner_pairs:
            if scanner is None:
                continue

            digit_reader = getattr(scanner, "digit_reader", None)
            load = getattr(digit_reader, "load", None)
            if not callable(load):
                continue

            try:
                load()
                reloaded.append(name)
            except Exception as exc:
                failed.append(f"{name}: {exc}")

        if failed:
            return " Digit template reload failed for " + "; ".join(failed) + "."

        if reloaded:
            return " Reloaded digit templates for " + ", ".join(reloaded) + "."

        return " No live digit readers were available to reload."


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
    def _auto_train_signature(candidate: _AutoTrainCandidate) -> tuple[int, str, str]:
        try:
            digest = hashlib.sha1(candidate.crop_path.read_bytes()).hexdigest()[:12]
        except Exception:
            digest = hashlib.sha1(str(candidate.crop_path).encode("utf-8")).hexdigest()[:12]
        return int(candidate.expected_level), candidate.state, digest

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
