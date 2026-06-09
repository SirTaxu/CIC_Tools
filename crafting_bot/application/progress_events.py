from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from crafting_bot.domain.loop_execution import LoopIterationResult

BotEventType = Literal["scan", "wait", "cycle", "hire", "reincarnate", "recovery", "stop", "failed", "error"]


@dataclass(frozen=True)
class BotProgressEvent:
    """UI/CLI-safe progress event emitted by application controllers.

    This decouples the presentation layer from internal loop result classes.
    The original iteration is retained for backwards-compatible detailed CLI
    printing while the GUI can use the normalized summary fields.
    """

    event_type: BotEventType
    screen: str
    level_text: str
    ready: str
    same_level_seconds: float
    trigger_reason: str
    message: str
    selected_cycle: str | None = None
    cycle_success: bool | None = None
    original_iteration: LoopIterationResult | None = None

    @classmethod
    def from_iteration(cls, iteration: LoopIterationResult) -> "BotProgressEvent":
        cycle = iteration.cycle_result
        selected_cycle = cycle.cycle.name if cycle is not None and cycle.cycle is not None else None
        cycle_success: bool | None = None
        if cycle is not None:
            cycle_success = (
                cycle.cycle is not None
                and cycle.eligible
                and bool(cycle.steps)
                and all(step.outcome in {"success", "planned"} for step in cycle.steps)
            )

        event_type: BotEventType
        if iteration.action in {"wait", "cycle", "hire", "reincarnate", "recovery", "stop", "failed"}:
            event_type = iteration.action
        else:
            event_type = "scan"

        return cls(
            event_type=event_type,
            screen=iteration.scan.screen,
            level_text=iteration.scan.level_text,
            ready=iteration.scan.ready,
            same_level_seconds=iteration.same_level_seconds,
            trigger_reason=iteration.trigger_reason,
            message=iteration.message,
            selected_cycle=selected_cycle,
            cycle_success=cycle_success,
            original_iteration=iteration,
        )
