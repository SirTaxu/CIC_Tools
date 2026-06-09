from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ReadyState = Literal["yes", "no", "unknown"]


@dataclass(frozen=True)
class PointTarget:
    name: str
    x: int
    y: int


@dataclass(frozen=True)
class AreaTarget:
    name: str
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class ReadyMatch:
    state: ReadyState
    score: float
    template_path: Path | None
    level_hint: int | None = None


@dataclass(frozen=True)
class DigitMatch:
    digit: str
    score: float
    x: int
    y: int
    template_path: Path
    second_digit: str | None = None
    second_score: float | None = None
    ambiguous: bool = False
    source: str = "component"


@dataclass(frozen=True)
class LevelScanResult:
    ok: bool
    screen: str
    level_text: str
    level: int | None
    ready: ReadyState
    ready_score: float | None
    ready_template: str | None
    digit_score: float | None
    level_crop_path: Path | None
    message: str
    digit_diagnostics: str | None = None
