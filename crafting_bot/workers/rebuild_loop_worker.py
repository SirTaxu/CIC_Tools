from __future__ import annotations

import queue
import threading
from dataclasses import dataclass

from crafting_bot.application.progress_events import BotProgressEvent
from crafting_bot.application.settings import RebuildLoopSettings
from crafting_bot.domain.loop_execution import LoopIterationResult, LoopRunResult
from crafting_bot.factory import build_bot_controller


@dataclass(frozen=True)
class LoopGuiStatus:
    running: bool
    screen: str = "UNKNOWN"
    level: str = "-"
    ready: str = "unknown"
    cycles: str = "0"
    same_level_seconds: float = 0.0
    last_action: str = "-"
    message: str = ""


class RebuildLoopWorker:
    """Background worker for the minimal bot GUI.

    The GUI is intentionally a thin adapter. The actual loop logic remains in
    RebuildLoopRunner, and this worker only translates loop progress into GUI
    status messages.
    """

    # Safety cap for GUI rebuild-cycle counting. The visible stop condition should
    # normally be desired_level, reincarnation mode, or manual Stop.
    _GUI_MAX_REBUILD_CYCLES = 10000

    # Used when the optional GUI iteration safety is disabled. This is kept as a
    # finite value because the lower-level runner currently expects an integer.
    # At one scan per second it is effectively unlimited for normal runs.
    _GUI_UNLIMITED_MAX_ITERATIONS = 10_000_000

    def __init__(
        self,
        event_queue: queue.Queue[LoopGuiStatus],
        *,
        desired_level: int,
        reincarnation_enabled: bool,
        stuck_seconds: float,
        scan_interval_seconds: float,
        auto_train_missing_digits: bool,
        hire_enabled: bool = False,
        hire_setup_level: int = 45,
        hire_drag_duration_ms: int = 750,
        max_iterations_enabled: bool = False,
        max_iterations: int = 500,
    ) -> None:
        self.event_queue = event_queue
        self.desired_level = max(1, int(desired_level))
        self.reincarnation_enabled = bool(reincarnation_enabled)
        self.stuck_seconds = max(1.0, float(stuck_seconds))
        self.scan_interval_seconds = max(0.10, float(scan_interval_seconds))
        self.auto_train_missing_digits = auto_train_missing_digits
        self.hire_enabled = bool(hire_enabled)
        self.hire_setup_level = max(1, int(hire_setup_level))
        self.hire_drag_duration_ms = max(100, int(hire_drag_duration_ms))
        self.max_iterations_enabled = bool(max_iterations_enabled)
        self.max_iterations = max(1, int(max_iterations))

        self.stop_requested = threading.Event()
        self.thread: threading.Thread | None = None
        self.running = False
        self._cycles_completed = 0
        self._reincarnations_completed = 0
        self._hire_setups_completed = 0

    def start(self) -> None:
        if self.running:
            return
        self.stop_requested.clear()
        self.running = True
        self._cycles_completed = 0
        self._reincarnations_completed = 0
        self._hire_setups_completed = 0
        self._emit(
            LoopGuiStatus(
                running=True,
                screen="STARTING",
                cycles="0",
                last_action="start",
                message=(
                    f"Starting rebuild loop toward level {self.desired_level}. "
                    f"Reincarnation={'on' if self.reincarnation_enabled else 'off'}, "
                    f"hire setup={'on' if self.hire_enabled else 'off'} at level {self.hire_setup_level}, "
                    f"iteration safety={'on' if self.max_iterations_enabled else 'off'}"
                    f"{f' ({self.max_iterations})' if self.max_iterations_enabled else ''}."
                ),
            )
        )
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if not self.running:
            return
        self.stop_requested.set()
        self._emit(
            LoopGuiStatus(
                running=True,
                screen="STOPPING",
                cycles=str(self._cycles_completed),
                last_action="stop requested",
                message="Stop requested. The bot will stop before the next tap/poll as soon as the signal is observed.",
            )
        )

    def _run(self) -> None:
        try:
            controller = build_bot_controller()
            effective_max_iterations = (
                self.max_iterations
                if self.max_iterations_enabled
                else self._GUI_UNLIMITED_MAX_ITERATIONS
            )

            settings = RebuildLoopSettings(
                mode="click",
                max_cycles=self._GUI_MAX_REBUILD_CYCLES,
                desired_level=self.desired_level,
                reincarnation_enabled=self.reincarnation_enabled,
                stuck_seconds=self.stuck_seconds,
                scan_interval_seconds=self.scan_interval_seconds,
                assist_digit_training=False,
                auto_train_missing_digits=self.auto_train_missing_digits,
                hire_enabled=self.hire_enabled,
                hire_setup_level=self.hire_setup_level,
                hire_drag_duration_ms=self.hire_drag_duration_ms,
                max_iterations=effective_max_iterations,
            )
            result = controller.run_rebuild_loop(
                settings,
                stop_event=self.stop_requested,
                on_event=self._on_event,
            )
            self._emit_final(result)
        except Exception as exc:
            self._emit(
                LoopGuiStatus(
                    running=False,
                    screen="ERROR",
                    cycles=str(self._cycles_completed),
                    last_action="error",
                    message=f"Loop failed: {exc}",
                )
            )
        finally:
            self.running = False

    def _on_event(self, event: BotProgressEvent) -> None:
        iteration = event.original_iteration
        if iteration is None:
            self._emit(
                LoopGuiStatus(
                    running=True,
                    screen=event.screen,
                    level=event.level_text,
                    ready=event.ready,
                    cycles=f"{self._cycles_completed} rebuilds, {self._hire_setups_completed} hire setups, {self._reincarnations_completed} reincarnations",
                    same_level_seconds=event.same_level_seconds,
                    last_action=f"{event.event_type}: {event.trigger_reason}",
                    message=event.message,
                )
            )
            return

        if iteration.action == "cycle" and self._cycle_success(iteration):
            self._cycles_completed += 1
        elif iteration.action == "hire":
            if "completed" in iteration.message.lower() and "failed" not in iteration.message.lower():
                self._hire_setups_completed += 1
        elif iteration.action == "reincarnate":
            if "completed" in iteration.message.lower() and "failed" not in iteration.message.lower():
                self._reincarnations_completed += 1

        scan = iteration.scan
        message = iteration.message
        if iteration.cycle_result is not None:
            cycle = iteration.cycle_result
            cycle_name = cycle.cycle.name if cycle.cycle is not None else "none"
            message = f"{message} Selected cycle: {cycle_name}."

        self._emit(
            LoopGuiStatus(
                running=True,
                screen=scan.screen,
                level=scan.level_text,
                ready=scan.ready,
                cycles=f"{self._cycles_completed} rebuilds, {self._hire_setups_completed} hire setups, {self._reincarnations_completed} reincarnations",
                same_level_seconds=iteration.same_level_seconds,
                last_action=f"{iteration.action}: {iteration.trigger_reason}",
                message=message,
            )
        )

    def _emit_final(self, result: LoopRunResult) -> None:
        self._cycles_completed = result.cycles_completed
        self._emit(
            LoopGuiStatus(
                running=False,
                screen="STOPPED",
                cycles=f"{result.cycles_completed} rebuilds, {self._hire_setups_completed} hire setups, {self._reincarnations_completed} reincarnations",
                last_action=result.stopped_reason,
                message=result.message,
            )
        )

    @staticmethod
    def _cycle_success(iteration: LoopIterationResult) -> bool:
        result = iteration.cycle_result
        if result is None or result.cycle is None or not result.eligible:
            return False
        if not result.steps:
            return False
        return all(step.outcome in {"success", "planned"} for step in result.steps)

    def _emit(self, status: LoopGuiStatus) -> None:
        self.event_queue.put(status)
