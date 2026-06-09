from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from crafting_bot.domain.cycle_execution import ExecutionMode


@dataclass(frozen=True)
class RebuildLoopSettings:
    """Complete settings object for the unattended rebuild loop.

    GUI and CLI should both create this object and pass it to BotController.
    Keeping loop settings in one immutable value prevents interface drift where
    the GUI and CLI accidentally call the loop runner with different arguments.
    """

    mode: ExecutionMode = "dry_run"
    max_cycles: int = 3
    desired_level: int | None = None
    reincarnation_enabled: bool = False
    hire_enabled: bool = False
    hire_setup_level: int = 45
    hire_drag_duration_ms: int = 750
    stuck_seconds: float = 20.0
    scan_interval_seconds: float = 1.0
    max_runtime_seconds: float | None = None
    stop_at_level: int | None = None
    step_delay_seconds: float = 0.20
    wait_timeout_seconds: float = 8.0
    poll_interval_seconds: float = 0.25
    min_digit_score_for_click: float = 0.50
    allow_low_confidence_level: bool = False
    stop_on_scan_failure: bool = True
    stop_on_cycle_failure: bool = True
    max_iterations: int = 500
    assist_digit_training: bool = False
    auto_train_missing_digits: bool = False
    auto_train_ready_template_max_score: float = 0.16

    @property
    def click_mode_enabled(self) -> bool:
        return self.mode == "click"

    def to_runner_kwargs(self) -> dict[str, Any]:
        """Return keyword arguments accepted by RebuildLoopRunner.run.

        This intentionally excludes stop_event and callbacks. Those are runtime
        concerns controlled by BotController rather than user settings.
        """

        return {
            "mode": self.mode,
            "max_cycles": self.max_cycles,
            "desired_level": self.desired_level,
            "reincarnation_enabled": self.reincarnation_enabled,
            "hire_enabled": self.hire_enabled,
            "hire_setup_level": self.hire_setup_level,
            "hire_drag_duration_ms": self.hire_drag_duration_ms,
            "stuck_seconds": self.stuck_seconds,
            "scan_interval_seconds": self.scan_interval_seconds,
            "max_runtime_seconds": self.max_runtime_seconds,
            "stop_at_level": self.stop_at_level,
            "step_delay_seconds": self.step_delay_seconds,
            "wait_timeout_seconds": self.wait_timeout_seconds,
            "poll_interval_seconds": self.poll_interval_seconds,
            "min_digit_score_for_click": self.min_digit_score_for_click,
            "allow_low_confidence_level": self.allow_low_confidence_level,
            "stop_on_scan_failure": self.stop_on_scan_failure,
            "stop_on_cycle_failure": self.stop_on_cycle_failure,
            "max_iterations": self.max_iterations,
            "assist_digit_training": self.assist_digit_training,
            "auto_train_missing_digits": self.auto_train_missing_digits,
            "auto_train_ready_template_max_score": self.auto_train_ready_template_max_score,
        }
