from __future__ import annotations

from pathlib import Path
from typing import Any

from crafting_bot.domain.cycle_execution import ExecutionMode
from crafting_bot.domain.reward_selection import RewardSelectionResult
from crafting_bot.domain.target_catalog import get_search_target_definition
from crafting_bot.infra.adb_client import AdbClient
from crafting_bot.infra.calibration_store import CalibrationStore
from crafting_bot.services.search_target_service import SearchTargetService


class RewardSelectionService:
    """Keeps the Rebuild Workshop reward slider in a safe/preferred state.

    Current policy:
    - if gems are detected, click the detected gem icon every time;
    - if gems are not detected, use one calibrated default slider point;
    - while the latest applied selection is already default and gems are absent,
      skip clicking to keep the cycle faster.

    reward_slider_default_point is a calibrated reference point. At runtime it
    is adjusted vertically using the live position of rebuild_button_dynamic,
    because the whole Rebuild Workshop panel can move.
    """

    DEFAULT_POINT = "reward_slider_default_point"
    GEMS_SEARCH = "reward_gems_dynamic"
    REBUILD_ANCHOR_SEARCH = "rebuild_button_dynamic"
    REBUILD_ANCHOR_TEMPLATE = "rebuild_button_template"

    def __init__(
        self,
        *,
        adb: AdbClient,
        calibration: CalibrationStore,
        search_targets: SearchTargetService,
        latest_screenshot_path: Path,
    ) -> None:
        self.adb = adb
        self.calibration = calibration
        self.search_targets = search_targets
        self.latest_screenshot_path = latest_screenshot_path
        self._last_selected_reward: str | None = None

    def reset_memory(self) -> None:
        self._last_selected_reward = None

    def prepare_reward_selection(
        self,
        *,
        mode: ExecutionMode = "dry_run",
        stop_event: Any | None = None,
    ) -> RewardSelectionResult:
        if not self.calibration.has_point(self.DEFAULT_POINT):
            return RewardSelectionResult(
                ok=True,
                action="disabled_missing_calibration",
                selected_reward="none",
                gems_present=False,
                message=(
                    "Reward selector disabled: reward_slider_default_point is not calibrated. "
                    "The rebuild cycle will keep the previous behavior."
                ),
            )

        if self._stop_requested(stop_event):
            return RewardSelectionResult(
                ok=False,
                action="failed",
                selected_reward="none",
                gems_present=False,
                message="Stop requested before reward selection.",
            )

        gems = self._find_gems()
        if gems["present"]:
            click_x = int(gems["x"])
            click_y = int(gems["y"])
            if mode == "dry_run":
                return RewardSelectionResult(
                    ok=True,
                    action="planned_gems",
                    selected_reward="gems",
                    gems_present=True,
                    click_x=click_x,
                    click_y=click_y,
                    gems_score=gems["score"],
                    gems_threshold=gems["threshold"],
                    preview_path=gems["preview_path"],
                    message=(
                        f"Gems detected with score={gems['score']:.4f}. "
                        f"Would click gem icon at ({click_x}, {click_y})."
                    ),
                )

            self.adb.tap(click_x, click_y)
            self._last_selected_reward = "gems"
            return RewardSelectionResult(
                ok=True,
                action="click_gems",
                selected_reward="gems",
                gems_present=True,
                click_x=click_x,
                click_y=click_y,
                gems_score=gems["score"],
                gems_threshold=gems["threshold"],
                preview_path=gems["preview_path"],
                message=(
                    f"Gems detected with score={gems['score']:.4f}. "
                    f"Clicked gem icon at ({click_x}, {click_y})."
                ),
            )

        default_point = self._relative_default_point()
        if default_point["ok"] is False:
            return RewardSelectionResult(
                ok=False,
                action="failed",
                selected_reward="default",
                gems_present=False,
                gems_score=gems["score"],
                gems_threshold=gems["threshold"],
                preview_path=gems["preview_path"],
                message=str(default_point["message"]),
            )

        click_x = int(default_point["x"])
        click_y = int(default_point["y"])

        if self._last_selected_reward == "default":
            return RewardSelectionResult(
                ok=True,
                action="skip_default_already_selected",
                selected_reward="default",
                gems_present=False,
                click_x=click_x,
                click_y=click_y,
                gems_score=gems["score"],
                gems_threshold=gems["threshold"],
                preview_path=gems["preview_path"],
                message=(
                    "Gems were not detected and default reward was already selected in this run; "
                    f"skipping slider click. Current adjusted default point would be ({click_x}, {click_y}). "
                    f"{default_point['message']}"
                ),
            )

        if mode == "dry_run":
            return RewardSelectionResult(
                ok=True,
                action="planned_default",
                selected_reward="default",
                gems_present=False,
                click_x=click_x,
                click_y=click_y,
                gems_score=gems["score"],
                gems_threshold=gems["threshold"],
                preview_path=gems["preview_path"],
                message=(
                    "Gems were not detected. Would click adjusted default slider point "
                    f"at ({click_x}, {click_y}). {default_point['message']}"
                ),
            )

        self.adb.tap(click_x, click_y)
        self._last_selected_reward = "default"
        return RewardSelectionResult(
            ok=True,
            action="click_default_slider",
            selected_reward="default",
            gems_present=False,
            click_x=click_x,
            click_y=click_y,
            gems_score=gems["score"],
            gems_threshold=gems["threshold"],
            preview_path=gems["preview_path"],
            message=(
                "Gems were not detected. Clicked adjusted default slider point "
                f"at ({click_x}, {click_y}). {default_point['message']}"
            ),
        )

    def _relative_default_point(self) -> dict[str, object]:
        reference_point = self.calibration.get_point(self.DEFAULT_POINT)

        anchor_definition = get_search_target_definition(self.REBUILD_ANCHOR_SEARCH)
        if anchor_definition is None:
            return {
                "ok": False,
                "x": reference_point.x,
                "y": reference_point.y,
                "message": "Missing rebuild_button_dynamic search target definition; cannot anchor default slider point.",
            }

        if not self.calibration.has_area(self.REBUILD_ANCHOR_TEMPLATE):
            return {
                "ok": False,
                "x": reference_point.x,
                "y": reference_point.y,
                "message": "Missing rebuild_button_template area; cannot anchor default slider point.",
            }

        if not self.calibration.has_area(anchor_definition.search_area_name):
            return {
                "ok": False,
                "x": reference_point.x,
                "y": reference_point.y,
                "message": "Missing rebuild_button_search_area; cannot anchor default slider point.",
            }

        try:
            screenshot = self.adb.capture()
            self.latest_screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            screenshot.save(self.latest_screenshot_path)

            anchor_result = self.search_targets.run(anchor_definition, screenshot, save_preview=True)
            score = anchor_result.result.score
            if not anchor_result.result.ok or score is None or score > anchor_definition.default_threshold:
                return {
                    "ok": False,
                    "x": reference_point.x,
                    "y": reference_point.y,
                    "message": (
                        "Could not confidently locate rebuild_button_dynamic for reward anchoring. "
                        f"score={score}, threshold={anchor_definition.default_threshold}."
                    ),
                }

            template_area = self.calibration.get_area(self.REBUILD_ANCHOR_TEMPLATE)
            reference_anchor_center_y = template_area.y + template_area.height // 2
            live_anchor_center_y = int(anchor_result.result.center_y)
            y_offset = live_anchor_center_y - reference_anchor_center_y

            return {
                "ok": True,
                "x": int(reference_point.x),
                "y": int(reference_point.y + y_offset),
                "message": (
                    f"Anchored default slider point with rebuild button y_offset={y_offset}: "
                    f"reference_anchor_y={reference_anchor_center_y}, live_anchor_y={live_anchor_center_y}, "
                    f"anchor_score={score:.4f}."
                ),
            }
        except Exception as exc:
            return {
                "ok": False,
                "x": reference_point.x,
                "y": reference_point.y,
                "message": f"Default slider anchoring failed: {exc}",
            }

    def _find_gems(self) -> dict[str, object]:
        definition = get_search_target_definition(self.GEMS_SEARCH)
        if definition is None:
            return {
                "present": False,
                "x": None,
                "y": None,
                "score": None,
                "threshold": None,
                "preview_path": None,
                "message": "Missing reward_gems_dynamic target definition.",
            }

        if not self.calibration.has_area(definition.search_area_name) or not self.calibration.has_area(definition.template_area_name):
            return {
                "present": False,
                "x": None,
                "y": None,
                "score": None,
                "threshold": definition.default_threshold,
                "preview_path": None,
                "message": "Gems search/template areas are not fully calibrated.",
            }

        try:
            screenshot = self.adb.capture()
            self.latest_screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            screenshot.save(self.latest_screenshot_path)

            result = self.search_targets.run(definition, screenshot, save_preview=True)
            score = result.result.score
            present = bool(result.result.ok and score is not None and score <= definition.default_threshold)
            return {
                "present": present,
                "x": result.result.center_x,
                "y": result.result.center_y,
                "score": score,
                "threshold": definition.default_threshold,
                "preview_path": result.preview_path,
                "message": result.result.message,
            }
        except Exception as exc:
            return {
                "present": False,
                "x": None,
                "y": None,
                "score": None,
                "threshold": definition.default_threshold,
                "preview_path": None,
                "message": f"Gems detection failed: {exc}",
            }

    @staticmethod
    def _stop_requested(stop_event: Any | None) -> bool:
        return bool(stop_event is not None and getattr(stop_event, "is_set", lambda: False)())
