from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReincarnationStepDefinition:
    order: int
    action: str
    target_name: str
    verification_target: str | None
    fallback_point_names: tuple[str, ...] = ()
    notes: str = ""


REINCARNATION_STEPS: tuple[ReincarnationStepDefinition, ...] = (
    ReincarnationStepDefinition(
        order=1,
        action="open headquarters",
        target_name="hq_button",
        verification_target="dynasty_button_check_area",
        notes="Click the Headquarters button, then verify the Dynasty option is visible.",
    ),
    ReincarnationStepDefinition(
        order=2,
        action="open dynasty",
        target_name="dynasty_button",
        verification_target="reincarnate_button_check_area",
        notes="Click the Dynasty button, then verify the reincarnation screen/button is visible.",
    ),
    ReincarnationStepDefinition(
        order=3,
        action="open reincarnation confirmation",
        target_name="reincarnate_button",
        verification_target="default_button_check_area",
        notes="Click Reincarnate, then verify the final confirmation/default screen is visible.",
    ),
    ReincarnationStepDefinition(
        order=4,
        action="click default reincarnation",
        target_name="default_button",
        verification_target="level_area",
        notes=(
            "Click Default, then verify that the level screen returns after reincarnation."
        ),
    ),
)
