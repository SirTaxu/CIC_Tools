from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from crafting_bot.domain.cycle_definitions import CycleDefinition, CycleStepDefinition
from crafting_bot.domain.models import LevelScanResult

ExecutionMode = Literal["dry_run", "click"]
StepOutcome = Literal["planned", "skipped", "success", "failed"]
VerificationStatus = Literal["not_attempted", "passed", "failed"]


@dataclass(frozen=True)
class VerificationResult:
    target_name: str | None
    attempted: bool
    passed: bool | None
    score: float | None
    threshold: float | None
    message: str
    preview_path: Path | None = None


@dataclass(frozen=True)
class StepExecutionResult:
    definition: CycleStepDefinition
    outcome: StepOutcome
    mode: ExecutionMode
    click_x: int | None
    click_y: int | None
    search_score: float | None
    search_accepted: bool | None
    verification: VerificationResult | None
    preview_path: Path | None
    message: str


@dataclass(frozen=True)
class CycleExecutionResult:
    mode: ExecutionMode
    scan: LevelScanResult
    cycle: CycleDefinition | None
    eligible: bool
    trigger_reason: str
    steps: tuple[StepExecutionResult, ...]
    message: str
