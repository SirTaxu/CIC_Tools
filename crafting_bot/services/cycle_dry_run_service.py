from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from crafting_bot.domain.cycle_definitions import CycleDefinition, CycleStepDefinition
from crafting_bot.domain.cycle_selector import select_cycle_for_level
from crafting_bot.domain.models import LevelScanResult
from crafting_bot.domain.target_catalog import get_search_target_definition, get_target_definition
from crafting_bot.infra.calibration_store import CalibrationStore
from crafting_bot.services.level_scanner import LevelScanner
from crafting_bot.services.search_target_service import SearchTargetService
from crafting_bot.services.target_status_service import TargetStatusService


@dataclass(frozen=True)
class DryRunStep:
    definition: CycleStepDefinition
    target_status: str
    verification_status: str | None
    click_x: int | None
    click_y: int | None
    search_score: float | None
    search_accepted: bool | None
    preview_path: Path | None
    message: str


@dataclass(frozen=True)
class CycleDryRunResult:
    scan: LevelScanResult
    cycle: CycleDefinition | None
    trigger_reason: str
    steps: tuple[DryRunStep, ...]
    message: str


class CycleDryRunService:
    """Builds a no-click rebuild-cycle plan from the current scan result."""

    def __init__(
        self,
        scanner: LevelScanner,
        calibration: CalibrationStore,
        target_status: TargetStatusService,
        search_targets: SearchTargetService,
        latest_screenshot_path: Path,
    ) -> None:
        self.scanner = scanner
        self.calibration = calibration
        self.target_status = target_status
        self.search_targets = search_targets
        self.latest_screenshot_path = latest_screenshot_path

    def run(self, *, level_override: int | None = None, try_search_targets: bool = False) -> CycleDryRunResult:
        scan = self.scanner.scan()
        effective_level = level_override if level_override is not None else scan.level

        if effective_level is None:
            return CycleDryRunResult(
                scan=scan,
                cycle=None,
                trigger_reason="unknown_level",
                steps=(),
                message="Cannot choose a cycle because the level was not read.",
            )

        cycle = select_cycle_for_level(effective_level)
        screenshot = self._load_latest_screenshot()
        steps = tuple(
            self._describe_step(step, screenshot=screenshot, try_search_targets=try_search_targets)
            for step in cycle.steps
        )

        trigger_reason = self._trigger_reason(scan)
        return CycleDryRunResult(
            scan=scan,
            cycle=cycle,
            trigger_reason=trigger_reason,
            steps=steps,
            message=f"Dry run selected cycle {cycle.name} for level {effective_level}. No clicks were sent.",
        )

    def _describe_step(self, step: CycleStepDefinition, *, screenshot: Image.Image, try_search_targets: bool) -> DryRunStep:
        target_status = self.target_status.describe(step.target_name)
        verification_status = self.target_status.describe(step.verification_target) if step.verification_target else None
        click_x: int | None = None
        click_y: int | None = None
        search_score: float | None = None
        search_accepted: bool | None = None
        preview_path: Path | None = None
        message = "not executable in dry-run"

        if step.mode == "fixed_point":
            point = self._safe_point(step.target_name)
            if point is not None:
                click_x, click_y = point
                message = f"would click fixed point ({click_x}, {click_y})"
            else:
                message = "cannot click: missing point target"

        elif step.mode == "search_target":
            definition = get_search_target_definition(step.target_name)
            if definition is None:
                message = "cannot search: unknown search target"
            elif not try_search_targets:
                message = "search not attempted; use --try-search-targets when the relevant screen is visible"
            else:
                try:
                    run_result = self.search_targets.run(definition, screenshot=screenshot, save_preview=True)
                    found = run_result.result
                    search_score = found.score
                    preview_path = run_result.preview_path
                    search_accepted = bool(found.ok and found.score is not None and found.score <= definition.default_threshold)
                    if found.center_x is not None and found.center_y is not None:
                        click_x, click_y = found.center_x, found.center_y
                    message = (
                        f"search attempted; accepted={search_accepted}; "
                        f"score={search_score}; would click=({click_x}, {click_y})"
                    )
                except Exception as exc:
                    message = f"search failed: {exc}"

        elif step.mode == "screen_check":
            message = "would verify screen/check area"

        return DryRunStep(
            definition=step,
            target_status=target_status,
            verification_status=verification_status,
            click_x=click_x,
            click_y=click_y,
            search_score=search_score,
            search_accepted=search_accepted,
            preview_path=preview_path,
            message=message,
        )

    def _safe_point(self, target_name: str) -> tuple[int, int] | None:
        target = get_target_definition(target_name)
        if target is None or target.kind != "point" or not self.calibration.has_point(target_name):
            return None
        point = self.calibration.get_point(target_name)
        return point.x, point.y

    def _load_latest_screenshot(self) -> Image.Image:
        return Image.open(self.latest_screenshot_path).convert("RGB")

    @staticmethod
    def _trigger_reason(scan: LevelScanResult) -> str:
        if scan.ready == "yes":
            return "ready_star_detected"
        if scan.ready == "no":
            return "not_ready; no dry-run timer trigger available"
        return "ready_state_unknown"
