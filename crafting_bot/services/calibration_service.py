from __future__ import annotations

import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from crafting_bot.domain.models import AreaTarget, PointTarget
from crafting_bot.infra.calibration_store import CalibrationStore
from crafting_bot.vision.image_tools import crop_area, save_preview


@dataclass(frozen=True)
class CalibrationCaptureResult:
    target_name: str
    target_kind: str
    saved_config_path: Path
    crop_path: Path | None
    preview_path: Path | None
    message: str


class CalibrationService:
    """Writes calibrated targets and area crops without owning UI or ADB details."""

    def __init__(
        self,
        store: CalibrationStore,
        crop_dir: Path,
        preview_dir: Path,
    ) -> None:
        self.store = store
        self.crop_dir = crop_dir
        self.preview_dir = preview_dir

    def save_point(self, target: PointTarget) -> CalibrationCaptureResult:
        self._backup_config_once()
        self.store.update_point(target)
        self.store.save()
        return CalibrationCaptureResult(
            target_name=target.name,
            target_kind="point",
            saved_config_path=self.store.config_path,
            crop_path=None,
            preview_path=None,
            message=f"Saved point {target.name}: x={target.x}, y={target.y}.",
        )

    def save_area(self, target: AreaTarget, screenshot: Image.Image) -> CalibrationCaptureResult:
        self._backup_config_once()
        self.store.update_area(target)
        self.store.save()

        crop = crop_area(screenshot, target)
        self.crop_dir.mkdir(parents=True, exist_ok=True)
        self.preview_dir.mkdir(parents=True, exist_ok=True)

        crop_path = self.crop_dir / f"{target.name}.png"
        preview_path = self.preview_dir / f"{target.name}_preview.png"
        crop.save(crop_path)
        save_preview(crop, preview_path)

        return CalibrationCaptureResult(
            target_name=target.name,
            target_kind="area",
            saved_config_path=self.store.config_path,
            crop_path=crop_path,
            preview_path=preview_path,
            message=(
                f"Saved area {target.name}: x={target.x}, y={target.y}, "
                f"width={target.width}, height={target.height}."
            ),
        )

    def refresh_area_crop(self, target_name: str, screenshot: Image.Image) -> CalibrationCaptureResult:
        target = self.store.get_area(target_name)
        crop = crop_area(screenshot, target)
        self.crop_dir.mkdir(parents=True, exist_ok=True)
        self.preview_dir.mkdir(parents=True, exist_ok=True)

        crop_path = self.crop_dir / f"{target.name}.png"
        preview_path = self.preview_dir / f"{target.name}_preview.png"
        crop.save(crop_path)
        save_preview(crop, preview_path)

        return CalibrationCaptureResult(
            target_name=target.name,
            target_kind="area",
            saved_config_path=self.store.config_path,
            crop_path=crop_path,
            preview_path=preview_path,
            message=f"Refreshed crop for {target.name}: {crop.width}x{crop.height}.",
        )

    def _backup_config_once(self) -> None:
        if not self.store.config_path.exists():
            return

        backup_dir = self.store.config_path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"{self.store.config_path.stem}_{stamp}.json"
        shutil.copy2(self.store.config_path, backup_path)
