from __future__ import annotations

from dataclasses import dataclass

from crafting_bot.domain.reincarnation_definitions import REINCARNATION_STEPS, ReincarnationStepDefinition
from crafting_bot.infra.calibration_store import CalibrationStore
from crafting_bot.services.target_status_service import TargetStatusService


@dataclass(frozen=True)
class ReincarnationDryRunStep:
    definition: ReincarnationStepDefinition
    target_used: str | None
    target_status: str
    verification_status: str | None
    click_x: int | None
    click_y: int | None
    ready: bool
    message: str


@dataclass(frozen=True)
class ReincarnationDryRunResult:
    ready: bool
    steps: tuple[ReincarnationDryRunStep, ...]
    message: str


class ReincarnationDryRunService:
    """Plans the reincarnation flow without sending clicks.

    This service only checks whether the needed click points and verification
    crops are calibrated. It intentionally does not own ADB input or loop logic.
    """

    def __init__(self, calibration: CalibrationStore, target_status: TargetStatusService) -> None:
        self.calibration = calibration
        self.target_status = target_status

    def plan(self) -> ReincarnationDryRunResult:
        steps: list[ReincarnationDryRunStep] = []
        all_ready = True

        for definition in REINCARNATION_STEPS:
            target_used, target_status, click_x, click_y, target_ready = self._resolve_point(definition)
            verification_status = None
            verification_ready = True
            if definition.verification_target:
                verification_status = self.target_status.describe(definition.verification_target)
                verification_ready = self._status_is_ready(verification_status)

            ready = target_ready and verification_ready
            all_ready = all_ready and ready
            if ready:
                message = "ready"
            elif not target_ready:
                message = "missing click point"
            else:
                message = "missing or invalid verification target"

            steps.append(
                ReincarnationDryRunStep(
                    definition=definition,
                    target_used=target_used,
                    target_status=target_status,
                    verification_status=verification_status,
                    click_x=click_x,
                    click_y=click_y,
                    ready=ready,
                    message=message,
                )
            )

        if all_ready:
            message = "Reincarnation dry-run is ready. No clicks were sent."
        else:
            message = "Reincarnation dry-run found missing calibration. Calibrate missing targets before click-mode is added."

        return ReincarnationDryRunResult(ready=all_ready, steps=tuple(steps), message=message)

    def _resolve_point(
        self,
        definition: ReincarnationStepDefinition,
    ) -> tuple[str | None, str, int | None, int | None, bool]:
        candidates = (definition.target_name, *definition.fallback_point_names)
        primary_status = self.target_status.describe(definition.target_name)

        for index, name in enumerate(candidates):
            if self.calibration.has_point(name):
                point = self.calibration.get_point(name)
                if index == 0:
                    return name, primary_status, point.x, point.y, True
                return (
                    name,
                    f"primary {definition.target_name}: {primary_status}; using fallback {name}: point ok x={point.x}, y={point.y}",
                    point.x,
                    point.y,
                    True,
                )

        return None, primary_status, None, None, False

    @staticmethod
    def _status_is_ready(status: str) -> bool:
        return " ok " in f" {status} " or status.startswith("area ok") or status.startswith("point ok")
