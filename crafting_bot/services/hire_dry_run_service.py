from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from crafting_bot import paths
from crafting_bot.domain.hire_definitions import HIRE_STEPS, HireStepDefinition
from crafting_bot.infra.calibration_store import CalibrationStore


@dataclass(frozen=True)
class HireDryRunStepResult:
    order: int
    action: str
    mode: str
    target_name: str
    target_configured: bool
    target_status: str
    verification_target: str | None
    verification_configured: bool | None
    verification_status: str | None
    drag_end_target_name: str | None
    drag_end_configured: bool | None
    drag_end_status: str | None
    ready: bool
    notes: str


@dataclass(frozen=True)
class HireDryRunResult:
    ok: bool
    ready: bool
    setup_level: int
    steps: tuple[HireDryRunStepResult, ...]
    message: str


class HireDryRunService:
    """Reports whether the hire/setup flow has all required calibrated targets.

    This service is intentionally read-only. It never captures screenshots,
    clicks, drags, or writes calibration data.
    """

    def __init__(self, store: CalibrationStore) -> None:
        self.store = store

    def inspect(self, setup_level: int = 45) -> HireDryRunResult:
        step_results = tuple(self._inspect_step(step) for step in HIRE_STEPS)
        ready = all(step.ready for step in step_results)
        return HireDryRunResult(
            ok=True,
            ready=ready,
            setup_level=setup_level,
            steps=step_results,
            message=(
                "Hire calibration is complete enough for click-mode testing."
                if ready
                else "Hire calibration is incomplete. Calibrate the missing targets before click-mode is added."
            ),
        )

    def _inspect_step(self, step: HireStepDefinition) -> HireDryRunStepResult:
        target_configured, target_status = self._point_status(step.target_name)

        verification_configured: bool | None = None
        verification_status: str | None = None
        if step.verification_target:
            verification_configured, verification_status = self._area_status(step.verification_target)

        drag_end_configured: bool | None = None
        drag_end_status: str | None = None
        if step.drag_end_target_name:
            drag_end_configured, drag_end_status = self._point_status(step.drag_end_target_name)

        ready = target_configured
        if verification_configured is not None:
            ready = ready and verification_configured
        if drag_end_configured is not None:
            ready = ready and drag_end_configured

        return HireDryRunStepResult(
            order=step.order,
            action=step.action,
            mode=step.mode,
            target_name=step.target_name,
            target_configured=target_configured,
            target_status=target_status,
            verification_target=step.verification_target,
            verification_configured=verification_configured,
            verification_status=verification_status,
            drag_end_target_name=step.drag_end_target_name,
            drag_end_configured=drag_end_configured,
            drag_end_status=drag_end_status,
            ready=ready,
            notes=step.notes,
        )

    def _point_status(self, name: str) -> tuple[bool, str]:
        if not self.store.has_point(name):
            return False, "missing point"
        point = self.store.get_point(name)
        return True, f"configured x={point.x}, y={point.y}"

    def _area_status(self, name: str) -> tuple[bool, str]:
        if not self.store.has_area(name):
            return False, "missing area"

        area = self.store.get_area(name)
        crop_path = paths.CALIBRATION_CROP_DIR / f"{name}.png"
        if not crop_path.exists():
            return False, f"configured x={area.x}, y={area.y}, width={area.width}, height={area.height}; missing crop"

        try:
            with Image.open(crop_path) as image:
                actual_size = image.size
        except Exception as exc:
            return False, f"configured x={area.x}, y={area.y}, width={area.width}, height={area.height}; bad crop: {exc}"

        if actual_size != (area.width, area.height):
            return False, (
                f"configured x={area.x}, y={area.y}, width={area.width}, height={area.height}; "
                f"crop size mismatch: actual={actual_size[0]}x{actual_size[1]}"
            )

        return True, f"configured x={area.x}, y={area.y}, width={area.width}, height={area.height}; crop ok: {actual_size[0]}x{actual_size[1]}"
