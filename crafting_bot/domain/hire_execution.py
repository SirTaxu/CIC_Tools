from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from crafting_bot.domain.cycle_execution import ExecutionMode, VerificationResult
from crafting_bot.domain.hire_definitions import HireStepDefinition

HireStepOutcome = Literal["planned", "success", "failed"]


@dataclass(frozen=True)
class HireStepResult:
    definition: HireStepDefinition
    outcome: HireStepOutcome
    mode: ExecutionMode
    target_used: str | None
    click_x: int | None
    click_y: int | None
    drag_end_used: str | None
    drag_end_x: int | None
    drag_end_y: int | None
    drag_duration_ms: int | None
    verification: VerificationResult | None
    message: str
    preview_path: Path | None = None


@dataclass(frozen=True)
class HireExecutionResult:
    mode: ExecutionMode
    eligible: bool
    setup_level: int
    steps: tuple[HireStepResult, ...]
    message: str
