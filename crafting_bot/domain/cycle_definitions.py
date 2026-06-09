from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CycleName = Literal["level1", "early_2_5", "dynamic_6_plus"]
StepMode = Literal["fixed_point", "search_target", "screen_check"]


@dataclass(frozen=True)
class CycleStepDefinition:
    order: int
    action: str
    target_name: str
    mode: StepMode
    verification_target: str | None
    notes: str = ""


@dataclass(frozen=True)
class CycleDefinition:
    name: CycleName
    level_range: str
    status: str
    notes: str
    steps: tuple[CycleStepDefinition, ...]


CYCLE_DEFINITIONS: tuple[CycleDefinition, ...] = (
    CycleDefinition(
        name="level1",
        level_range="1",
        status="fixed_level_1_cycle",
        notes=(
            "Level 1 uses the fixed early rebuild and fixed early take-reward buttons, "
            "but it has its own Free-screen layout/Y position. It must not use the "
            "normal free_button target."
        ),
        steps=(
            CycleStepDefinition(1, "open level 1 rebuild flow", "level_button", "fixed_point", "early_rebuild_button_check_area"),
            CycleStepDefinition(2, "click fixed rebuild", "early_rebuild_button", "fixed_point", "early_reward_button_check_area"),
            CycleStepDefinition(3, "take reward", "early_reward_button", "fixed_point", "early_free_button_check_area"),
            CycleStepDefinition(4, "click level 1 free", "early_free_button", "fixed_point", "level_area", "Level 1 Free has a different Y/layout than later levels."),
        ),
    ),
    CycleDefinition(
        name="early_2_5",
        level_range="2-5",
        status="fixed_levels_2_5_cycle",
        notes=(
            "Levels 2, 3, 4, and 5 share one fixed pattern. Rebuild and Take Reward "
            "use the same early_rebuild/early_reward targets as level 1. Free uses the "
            "normal free_button target, not early_free_button."
        ),
        steps=(
            CycleStepDefinition(1, "open levels 2-5 rebuild flow", "level_button", "fixed_point", "early_rebuild_button_check_area"),
            CycleStepDefinition(2, "click fixed rebuild", "early_rebuild_button", "fixed_point", "early_reward_button_check_area"),
            CycleStepDefinition(3, "take reward", "early_reward_button", "fixed_point", "free_button_check_area"),
            CycleStepDefinition(4, "click normal free", "free_button", "fixed_point", "level_area", "Levels 2-5 use the normal Free button position."),
        ),
    ),
    CycleDefinition(
        name="dynamic_6_plus",
        level_range="6+",
        status="guarded_dynamic_cycle",
        notes=(
            "Levels 6+ use the Rebuild Workshop screen. The Rebuild now button is found "
            "visually inside rebuild_button_search_area, but only after "
            "rebuild_workshop_check_area proves the correct panel is open."
        ),
        steps=(
            CycleStepDefinition(1, "open rebuild workshop", "level_button", "fixed_point", "rebuild_workshop_check_area", "Wait for the Rebuild Workshop screen marker before any dynamic search/click."),
            CycleStepDefinition(2, "find and click rebuild", "rebuild_button_dynamic", "search_target", "reward_button_check_area"),
            CycleStepDefinition(3, "take reward", "reward_button", "fixed_point", "free_button_check_area"),
            CycleStepDefinition(4, "click free", "free_button", "fixed_point", "level_area", "Verify by scanning the level screen again."),
        ),
    ),
)
