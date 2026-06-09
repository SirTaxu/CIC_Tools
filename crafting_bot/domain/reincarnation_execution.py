from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from crafting_bot.domain.cycle_execution import ExecutionMode, VerificationResult
from crafting_bot.domain.reincarnation_definitions import ReincarnationStepDefinition

ReincarnationStepOutcome = Literal["planned", "success", "failed"]


@dataclass(frozen=True)
class ReincarnationStepResult:
    definition: ReincarnationStepDefinition
    outcome: ReincarnationStepOutcome
    mode: ExecutionMode
    target_used: str | None
    click_x: int | None
    click_y: int | None
    verification: VerificationResult | None
    message: str
    preview_path: Path | None = None


@dataclass(frozen=True)
class ReincarnationExecutionResult:
    mode: ExecutionMode
    eligible: bool
    steps: tuple[ReincarnationStepResult, ...]
    message: str
