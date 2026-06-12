from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from crafting_bot.domain.models import LevelScanResult

CycleConfirmationStatus = Literal["advanced", "same_level", "uncertain"]


@dataclass(frozen=True)
class CycleOutcomeConfirmation:
    """Stable post-cycle evidence used by the loop to update tracking.

    A rebuild click sequence is not enough to prove progress. The loop should
    advance expected-level tracking only after fresh scans prove that the visible
    level moved from the cycle start level to the next level.
    """

    status: CycleConfirmationStatus
    start_level: int | None
    expected_next_level: int | None
    scans: tuple[LevelScanResult, ...]
    message: str

    @property
    def advanced(self) -> bool:
        return self.status == "advanced"

    @property
    def same_level(self) -> bool:
        return self.status == "same_level"

    @property
    def uncertain(self) -> bool:
        return self.status == "uncertain"
