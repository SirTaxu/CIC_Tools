from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from crafting_bot.domain.screen_classification import KnownScreen

RecoveryContextName = Literal[
    "general",
    "rebuild",
    "hire",
    "reincarnation",
    "waiting_for_level",
    "unknown",
]

RecoveryAction = Literal[
    "none",
    "resume",
    "safe_return_to_level",
    "press_esc_once",
    "press_esc_twice_slowly",
    "click_take_reward",
    "click_free",
    "continue_rebuild",
    "continue_reincarnation",
    "stop",
]

RecoveryRisk = Literal["safe", "guarded", "dangerous", "stop"]


@dataclass(frozen=True)
class RecoveryRequest:
    screen: KnownScreen
    context: RecoveryContextName = "general"
    expected_screen: KnownScreen | None = None
    previous_screenshot_path: str | None = None
    current_screenshot_path: str | None = None


@dataclass(frozen=True)
class RecoveryDecision:
    action: RecoveryAction
    risk: RecoveryRisk
    reason: str
    expected_after_action: KnownScreen | None = None
    esc_presses: int = 0
    delay_between_esc_seconds: float = 1.0
    never_use_esc: bool = False
    dry_run_only: bool = True


@dataclass(frozen=True)
class RecoveryExecutionResult:
    ok: bool
    action_executed: str
    decision: RecoveryDecision
    before_screen: KnownScreen
    after_screen: KnownScreen | None = None
    message: str = ""
