from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from crafting_bot import paths
from crafting_bot.domain.cycle_execution import VerificationResult
from crafting_bot.infra.calibration_store import CalibrationStore
from crafting_bot.services.level_scanner import LevelScanner
from crafting_bot.vision.image_tools import crop_area


class ScreenVerifier:
    """Verifies screen progress after a click.

    It is deliberately small and conservative. For normal check-area targets it
    compares the live crop to the saved calibration crop. For level_area it runs
    the level scanner again, because returning to the level screen is better
    confirmed by reading the level than by exact pixel matching.
    """

    def __init__(
        self,
        calibration: CalibrationStore,
        scanner: LevelScanner,
        preview_dir: Path,
        default_threshold: float = 0.18,
    ) -> None:
        self.calibration = calibration
        self.scanner = scanner
        self.preview_dir = preview_dir
        self.default_threshold = default_threshold

    def verify(self, target_name: str | None, screenshot: Image.Image | None = None) -> VerificationResult:
        if not target_name:
            return VerificationResult(None, False, None, None, None, "No verification target configured.")

        if target_name == "level_area":
            scan = self.scanner.scan()
            passed = bool(scan.ok and scan.level is not None)
            return VerificationResult(
                target_name=target_name,
                attempted=True,
                passed=passed,
                score=scan.ready_score,
                threshold=None,
                message=(
                    "Level screen scan passed: " + scan.message
                    if passed
                    else "Level screen scan failed: " + scan.message
                ),
                preview_path=scan.level_crop_path,
            )

        if not self.calibration.has_area(target_name):
            return VerificationResult(target_name, True, False, None, self.default_threshold, "Missing calibrated verification area.")

        reference_path = paths.CALIBRATION_CROP_DIR / f"{target_name}.png"
        if not reference_path.exists():
            return VerificationResult(target_name, True, False, None, self.default_threshold, f"Missing reference crop: {reference_path}")

        area = self.calibration.get_area(target_name)
        if screenshot is None:
            screenshot = self.scanner.screen_capture.capture()

        live_crop = crop_area(screenshot, area).convert("RGB")
        reference = Image.open(reference_path).convert("RGB")
        if live_crop.size != reference.size:
            return VerificationResult(
                target_name=target_name,
                attempted=True,
                passed=False,
                score=None,
                threshold=self.default_threshold,
                message=f"Crop size mismatch: live={live_crop.size}, reference={reference.size}.",
            )

        score = self._image_diff(live_crop, reference)
        passed = score <= self.default_threshold
        preview_path = self._save_preview(target_name, live_crop, reference, score, passed)
        return VerificationResult(
            target_name=target_name,
            attempted=True,
            passed=passed,
            score=score,
            threshold=self.default_threshold,
            message=f"Verification {'passed' if passed else 'failed'} for {target_name}: score={score:.4f}, threshold={self.default_threshold:.4f}.",
            preview_path=preview_path,
        )

    @staticmethod
    def _image_diff(a: Image.Image, b: Image.Image) -> float:
        arr_a = np.asarray(a, dtype=np.int16)
        arr_b = np.asarray(b, dtype=np.int16)
        return float(np.mean(np.abs(arr_a - arr_b)) / 255.0)

    def _save_preview(self, target_name: str, live_crop: Image.Image, reference: Image.Image, score: float, passed: bool) -> Path:
        width = live_crop.width + reference.width
        height = max(live_crop.height, reference.height) + 24
        preview = Image.new("RGB", (width, height), color=(20, 20, 20))
        preview.paste(live_crop, (0, 24))
        preview.paste(reference, (live_crop.width, 24))
        draw = ImageDraw.Draw(preview)
        draw.text((4, 4), f"live | reference   score={score:.4f}   {'PASS' if passed else 'FAIL'}", fill=(255, 255, 255))
        path = self.preview_dir / f"verify_{target_name}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        preview.save(path)
        return path
