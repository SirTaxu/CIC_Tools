from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from crafting_bot.domain.cycle_execution import CycleExecutionResult, ExecutionMode
from crafting_bot.domain.models import LevelScanResult

LoopAction = Literal["wait", "cycle", "hire", "reincarnate", "stop", "failed"]


@dataclass(frozen=True)
class LoopIterationResult:
    """One observable decision made by the unattended loop.

    The loop owns repeated scanning, timers, and stop conditions. It does not own
    the details of a rebuild cycle; those remain inside CycleRunner.
    """

    index: int
    action: LoopAction
    scan: LevelScanResult
    same_level_seconds: float
    trigger_reason: str
    cycle_result: CycleExecutionResult | None
    message: str


@dataclass(frozen=True)
class LoopRunResult:
    mode: ExecutionMode
    max_cycles: int
    cycles_completed: int
    runtime_seconds: float
    stopped_reason: str
    iterations: tuple[LoopIterationResult, ...]
    message: str
