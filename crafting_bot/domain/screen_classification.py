from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

KnownScreen = Literal[
    "LEVEL_SCREEN",
    "MAP_SCREEN",
    "REBUILD_WORKSHOP",
    "TAKE_REWARD_SCREEN",
    "FREE_SCREEN",
    "HEADQUARTERS_SCREEN",
    "DYNASTY_SCREEN",
    "REINCARNATION_CONFIRM_SCREEN",
    "UNKNOWN",
]

ScreenConfidence = Literal["high", "medium", "low", "unknown"]


@dataclass(frozen=True)
class ScreenCandidate:
    screen: KnownScreen
    target_name: str
    attempted: bool
    passed: bool
    score: float | None = None
    threshold: float | None = None
    message: str = ""


@dataclass(frozen=True)
class ScreenClassificationResult:
    ok: bool
    screen: KnownScreen
    confidence: ScreenConfidence
    matched_target: str | None = None
    score: float | None = None
    threshold: float | None = None
    level: int | None = None
    level_text: str = "unknown"
    ready: str = "unknown"
    ready_score: float | None = None
    digit_score: float | None = None
    screenshot_path: Path | None = None
    candidates: tuple[ScreenCandidate, ...] = field(default_factory=tuple)
    message: str = ""
