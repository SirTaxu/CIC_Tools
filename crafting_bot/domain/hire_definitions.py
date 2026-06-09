from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

HireStepMode = Literal["click", "drag"]


@dataclass(frozen=True)
class HireStepDefinition:
    order: int
    action: str
    mode: HireStepMode
    target_name: str
    verification_target: str | None = None
    drag_end_target_name: str | None = None
    notes: str = ""


HIRE_STEPS: tuple[HireStepDefinition, ...] = (
    HireStepDefinition(
        order=1,
        action="open bag",
        mode="click",
        target_name="bag_button",
        verification_target="bag_screen_check_area",
        notes="Click Bag, then verify the hire/setup panel is open before dragging anything.",
    ),
    HireStepDefinition(
        order=2,
        action="set research",
        mode="drag",
        target_name="research_drag_start",
        drag_end_target_name="research_drag_end",
        notes="Click-and-hold Research slider start, drag to the desired calibrated position, then release.",
    ),
    HireStepDefinition(
        order=3,
        action="set auto-sale",
        mode="drag",
        target_name="autosale_drag_start",
        drag_end_target_name="autosale_drag_end",
        notes="Click-and-hold Auto-Sale slider start, drag to the desired calibrated position, then release.",
    ),
    HireStepDefinition(
        order=4,
        action="return to anvil",
        mode="click",
        target_name="anvil_button",
        verification_target="anvil_screen_check_area",
        notes="Click Anvil, then verify the normal anvil/workshop screen is visible again.",
    ),
)
