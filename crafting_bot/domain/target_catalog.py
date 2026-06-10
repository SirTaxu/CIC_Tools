from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TargetKind = Literal["point", "area"]
SearchAxis = Literal["both", "vertical"]
TargetPhase = Literal[
    "core",
    "level1_cycle",
    "early_cycle",
    "dynamic_cycle",
    "classifier",
    "recovery",
    "reward",
    "reincarnation",
    "hire",
    "reward_future",
]

@dataclass(frozen=True)
class TargetDefinition:
    name: str
    kind: TargetKind
    phase: TargetPhase
    description: str

@dataclass(frozen=True)
class SearchTargetDefinition:
    """
    A visual target found by searching one saved template crop inside one larger
    calibrated search area. This is for dynamic-position buttons such as the
    level 6+ rebuild button.
    """

    name: str
    template_area_name: str
    search_area_name: str
    phase: TargetPhase
    description: str
    default_threshold: float = 0.16
    search_axis: SearchAxis = "both"
    x_tolerance: int = 8

TARGETS: tuple[TargetDefinition, ...] = (
    # Core scan targets.
    TargetDefinition("level_area", "area", "core", "Area containing the level number and ready star."),
    TargetDefinition("level_button", "point", "core", "Point to open the level/rebuild flow from the level screen."),
    TargetDefinition("game_area", "area", "core", "Full stable game viewport area."),

    # Screen-classifier-only markers. These are separate from action check areas.
    # They answer "what screen am I currently on?" rather than "did my last
    # click reach the next expected step?". Keep them broad/stable and avoid
    # variable numbers/rewards whenever possible.
    TargetDefinition("classifier_rebuild_workshop_marker", "area", "classifier", "Classifier-only marker for the level 6+ Rebuild Workshop screen; prefer the Possible Rewards header/instructions area."),
    TargetDefinition("classifier_take_reward_marker", "area", "classifier", "Classifier-only marker for the Take Reward screen; include stable panel/button identity, not changing reward values."),
    TargetDefinition("classifier_free_screen_marker", "area", "classifier", "Classifier-only marker for the Free screen; include stable Free-button/panel identity."),
    TargetDefinition("classifier_headquarters_marker", "area", "classifier", "Classifier-only marker for the Headquarters screen/tab."),
    TargetDefinition("classifier_dynasty_marker", "area", "classifier", "Classifier-only marker for the Dynasty/reincarnation screen."),
    TargetDefinition("classifier_reincarnation_confirm_marker", "area", "classifier", "Classifier-only marker for the final reincarnation confirmation/default screen."),
    TargetDefinition("classifier_map_marker", "area", "classifier", "Classifier-only marker for the map screen that can appear after a missed level/rebuild click. Use a stable map-only area, not the top tabs."),
    TargetDefinition("recovery_safe_tap", "point", "recovery", "Optional irrelevant/safe tap point used between repeated ESC/BACK recovery presses. If missing, the runner uses a top-left fallback tap."),

    # Reward preference targets. These are active only for the level 6+ Rebuild
    # Workshop reward selector. The first implementation only distinguishes:
    # gems present -> click gem icon every time; otherwise -> use one calibrated
    # default slider position and skip repeated default clicks while the layout
    # remains non-gem.
    TargetDefinition("reward_slider_default_point", "point", "reward", "Reference default reward slider click point used when gems are not present. It is adjusted vertically at runtime relative to rebuild_button_dynamic."),
    TargetDefinition("reward_gems_template", "area", "reward", "Tight template crop of the gems reward icon on the Rebuild Workshop reward row."),
    TargetDefinition("reward_gems_search_area", "area", "reward", "Search area covering the possible gems reward icon position on the Rebuild Workshop reward row."),

    # Fixed level 1 / levels 2-5 cycle targets. These names come from the old
    # calibration set. Rebuild and take-reward are shared across levels 1-5.
    # Only the Free button differs for level 1.
    TargetDefinition("early_rebuild_button", "point", "level1_cycle", "Shared fixed rebuild button click point for levels 1-5."),
    TargetDefinition("early_rebuild_button_check_area", "area", "level1_cycle", "Visual check area for the shared levels 1-5 rebuild screen/button."),
    TargetDefinition("early_reward_button", "point", "level1_cycle", "Shared fixed Take Reward button click point for levels 1-5."),
    TargetDefinition("early_reward_button_check_area", "area", "level1_cycle", "Visual check area for the shared levels 1-5 take-reward panel."),
    TargetDefinition("early_free_button", "point", "level1_cycle", "Level 1 only Free button click point; Y/layout differs from levels 2+."),
    TargetDefinition("early_free_button_check_area", "area", "level1_cycle", "Visual check area for the level 1 only Free screen."),

    # Levels 2+ / level 6+ shared post-rebuild targets.
    TargetDefinition("free_button", "point", "early_cycle", "Normal Free button click point used by levels 2+."),
    TargetDefinition("free_button_check_area", "area", "early_cycle", "Visual check area for the normal Free screen used by levels 2+."),
    TargetDefinition("free_button_alt", "point", "early_cycle", "Alternate normal Free button click point if a later screen variant needs it."),
    TargetDefinition("free_button_alt_check_area", "area", "early_cycle", "Visual check area for the alternate normal Free screen."),

    # Level 6+ dynamic rebuild handling and normal take-reward targets.
    TargetDefinition("rebuild_workshop_check_area", "area", "dynamic_cycle", "Stable marker proving the level 6+ Rebuild Workshop screen is open before searching/clicking Rebuild now."),
    TargetDefinition("rebuild_button_template", "area", "dynamic_cycle", "Tight crop of the stable visual part of the level 6+ rebuild button."),
    TargetDefinition("rebuild_button_search_area", "area", "dynamic_cycle", "Tall vertical search region where the level 6+ rebuild button can appear."),
    TargetDefinition("reward_button", "point", "dynamic_cycle", "Normal Take Reward button click point used by the level 6+ cycle."),
    TargetDefinition("reward_button_check_area", "area", "dynamic_cycle", "Visual check area for the normal Take Reward panel used by the level 6+ cycle."),

    # Reward selection targets kept available for the future full reward-choice system.
    TargetDefinition("reward_blueprint_option_check_area", "area", "reward_future", "Normal blueprint reward option check area."),
    TargetDefinition("reward_gems_option_check_area", "area", "reward_future", "Normal gems reward option check area."),
    TargetDefinition("alt_reward_blueprint_option_check_area", "area", "reward_future", "Alternate blueprint reward option check area."),
    TargetDefinition("alt_reward_gems_option_check_area", "area", "reward_future", "Alternate gems reward option check area."),
    TargetDefinition("pre_rebuild_reward_slot_left", "area", "reward_future", "Left reward slot before rebuild."),
    TargetDefinition("pre_rebuild_reward_slot_right", "area", "reward_future", "Right reward slot before rebuild."),

    # Reincarnation targets. These are active in the current loop when reincarnation is enabled.
    TargetDefinition("hq_button", "point", "reincarnation", "Headquarters navigation button."),
    TargetDefinition("dynasty_button_check_area", "area", "reincarnation", "Visual marker proving the Headquarters/Dynasty navigation screen is open and Dynasty can be clicked."),
    TargetDefinition("dynasty_button", "point", "reincarnation", "Dynasty navigation button."),
    TargetDefinition("reincarnate_button_check_area", "area", "reincarnation", "Visual marker proving the Dynasty/reincarnation screen is open and Reincarnate can be clicked."),
    TargetDefinition("reincarnate_button", "point", "reincarnation", "Reincarnate button click point."),
    TargetDefinition("default_button_check_area", "area", "reincarnation", "Visual marker proving the final reincarnation confirmation/default screen is open."),
    TargetDefinition("default_button", "point", "reincarnation", "Default button on the final reincarnation confirmation screen."),

    # Hire/setup targets. These are active in the current loop when hire/setup is enabled.
    # Drag actions are represented by start/end point pairs.
    TargetDefinition("bag_button", "point", "hire", "Bag navigation button used to open the hire/setup panel."),
    TargetDefinition("bag_screen_check_area", "area", "hire", "Visual marker proving the Bag/hire setup screen is open before dragging sliders."),
    TargetDefinition("research_drag_start", "point", "hire", "Start/handle point for the Research slider drag."),
    TargetDefinition("research_drag_end", "point", "hire", "Target release point for the Research slider drag."),
    TargetDefinition("autosale_drag_start", "point", "hire", "Start/handle point for the Auto-Sale slider drag."),
    TargetDefinition("autosale_drag_end", "point", "hire", "Target release point for the Auto-Sale slider drag."),
    TargetDefinition("anvil_button", "point", "hire", "Anvil button used to return from the Bag/hire setup panel."),
    TargetDefinition("anvil_screen_check_area", "area", "hire", "Visual marker proving the Anvil/workshop screen is visible after returning from the hire setup."),
)

SEARCH_TARGETS: tuple[SearchTargetDefinition, ...] = (
    SearchTargetDefinition(
        name="rebuild_button_dynamic",
        template_area_name="rebuild_button_template",
        search_area_name="rebuild_button_search_area",
        phase="dynamic_cycle",
        description="Find the level 6+ rebuild button by matching its template inside the vertical search area after the Rebuild Workshop screen has been verified.",
        default_threshold=0.08,
        search_axis="vertical",
        x_tolerance=8,
    ),
    SearchTargetDefinition(
        name="reward_gems_dynamic",
        template_area_name="reward_gems_template",
        search_area_name="reward_gems_search_area",
        phase="reward",
        description="Find whether the gems reward icon is currently present in the Rebuild Workshop reward row.",
        default_threshold=0.12,
        search_axis="both",
        x_tolerance=8,
    ),
)

TARGET_BY_NAME: dict[str, TargetDefinition] = {target.name: target for target in TARGETS}
SEARCH_TARGET_BY_NAME: dict[str, SearchTargetDefinition] = {target.name: target for target in SEARCH_TARGETS}

PHASE_ORDER: tuple[TargetPhase, ...] = (
    "core",
    "level1_cycle",
    "early_cycle",
    "dynamic_cycle",
    "classifier",
    "recovery",
    "reward",
    "reincarnation",
    "hire",
    "reward_future",
)

def get_target_definition(name: str) -> TargetDefinition | None:
    return TARGET_BY_NAME.get(name)

def get_search_target_definition(name: str) -> SearchTargetDefinition | None:
    return SEARCH_TARGET_BY_NAME.get(name)

def infer_target_kind(name: str) -> TargetKind | None:
    definition = get_target_definition(name)
    if definition:
        return definition.kind
    if name.endswith("_area") or name.endswith("_check_area") or name.endswith("_template") or "slot" in name:
        return "area"
    if name.endswith("_button") or name.endswith("_confirm"):
        return "point"
    return None
