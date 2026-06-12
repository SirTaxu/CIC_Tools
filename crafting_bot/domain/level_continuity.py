from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LevelContinuityStatus = Literal["accepted", "quarantined"]


@dataclass(frozen=True)
class LevelContinuityDecision:
    """Result of checking a raw level scan against trusted climb context.

    The scanner reports observations. This decision says whether that observation
    is plausible for the current climb. A quarantined observation is not thrown
    away; the loop keeps it in diagnostics while continuing to use the trusted
    level for timing and cycle selection.
    """

    status: LevelContinuityStatus
    raw_level: int | None
    effective_level: int | None
    reference_level: int | None
    expected_level: int | None
    reason: str
    message: str

    @property
    def accepted(self) -> bool:
        return self.status == "accepted"

    @property
    def quarantined(self) -> bool:
        return self.status == "quarantined"
