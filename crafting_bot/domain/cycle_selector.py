from __future__ import annotations

from crafting_bot.domain.cycle_definitions import CYCLE_DEFINITIONS, CycleDefinition, CycleName


def select_cycle_name_for_level(level: int) -> CycleName:
    if level <= 1:
        return "level1"
    if 2 <= level <= 5:
        return "early_2_5"
    return "dynamic_6_plus"


def select_cycle_for_level(level: int) -> CycleDefinition:
    name = select_cycle_name_for_level(level)
    for cycle in CYCLE_DEFINITIONS:
        if cycle.name == name:
            return cycle
    raise LookupError(f"Cycle definition {name!r} is missing.")
