from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

RewardSelectionAction = Literal[
    "disabled_missing_calibration",
    "click_gems",
    "click_default_slider",
    "skip_default_already_selected",
    "planned_gems",
    "planned_default",
    "failed",
]

RewardChoice = Literal["gems", "default", "none"]


@dataclass(frozen=True)
class RewardSelectionResult:
    ok: bool
    action: RewardSelectionAction
    selected_reward: RewardChoice
    gems_present: bool
    click_x: int | None = None
    click_y: int | None = None
    gems_score: float | None = None
    gems_threshold: float | None = None
    preview_path: Path | None = None
    message: str = ""
