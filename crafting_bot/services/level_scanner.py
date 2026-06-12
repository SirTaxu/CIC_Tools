from __future__ import annotations

from pathlib import Path

from crafting_bot.domain.models import LevelScanResult
from crafting_bot.domain.ports import ScreenCapture
from crafting_bot.infra.calibration_store import CalibrationStore
from crafting_bot.vision.digit_reader import DigitReader
from crafting_bot.vision.image_tools import crop_area, save_preview
from crafting_bot.vision.ready_detector import ReadyDetector


class LevelScanner:
    """Coordinates screen capture, level-area crop, digit reading, and ready-state confirmation."""

    def __init__(
        self,
        screen_capture: ScreenCapture,
        calibration: CalibrationStore,
        ready_detector: ReadyDetector,
        digit_reader: DigitReader,
        screenshot_path: Path,
        level_crop_path: Path,
        level_preview_path: Path,
    ) -> None:
        self.screen_capture = screen_capture
        self.calibration = calibration
        self.ready_detector = ready_detector
        self.digit_reader = digit_reader
        self.screenshot_path = screenshot_path
        self.level_crop_path = level_crop_path
        self.level_preview_path = level_preview_path

    def scan(self) -> LevelScanResult:
        try:
            screenshot = self.screen_capture.capture()
            self.screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            screenshot.save(self.screenshot_path)

            level_area = self.calibration.get_area("level_area")
            level_crop = crop_area(screenshot, level_area)
            self.level_crop_path.parent.mkdir(parents=True, exist_ok=True)
            level_crop.save(self.level_crop_path)
            save_preview(level_crop, self.level_preview_path)

            level_text, digit_matches = self.digit_reader.read(level_crop)
            level = int(level_text) if level_text.isdigit() else None
            digit_score = min((match.score for match in digit_matches), default=None)
            digit_diagnostics = self.digit_reader.diagnostics_for_last_read()

            # Ready/not-ready is confirmed after digit reading so the detector
            # can compare same-level yes/no templates first. If the level is
            # unreadable, it falls back to broader cached templates.
            ready_match = self.ready_detector.classify(level_crop, level_hint=level)
            ready_diagnostics = self.ready_detector.diagnostics_for_last_match()

            return LevelScanResult(
                ok=True,
                screen="LEVEL_SCREEN",
                level_text=level_text,
                level=level,
                ready=ready_match.state,
                ready_score=ready_match.score,
                ready_template=ready_match.template_path.name if ready_match.template_path else None,
                digit_score=digit_score,
                level_crop_path=self.level_crop_path,
                message=self._format_message(
                    level_text,
                    ready_match.state,
                    ready_match.score,
                    digit_score,
                    digit_diagnostics,
                    ready_diagnostics,
                ),
                digit_diagnostics=digit_diagnostics,
                ready_diagnostics=ready_diagnostics,
            )

        except Exception as exc:
            return LevelScanResult(
                ok=False,
                screen="UNKNOWN",
                level_text="unknown",
                level=None,
                ready="unknown",
                ready_score=None,
                ready_template=None,
                digit_score=None,
                level_crop_path=None,
                message=f"Scan failed: {exc}",
                digit_diagnostics=None,
                ready_diagnostics=None,
            )

    @staticmethod
    def _format_message(
        level_text: str,
        ready: str,
        ready_score: float | None,
        digit_score: float | None,
        digit_diagnostics: str | None,
        ready_diagnostics: str | None,
    ) -> str:
        ready_part = f"ready={ready}"
        if ready_score is not None:
            ready_part += f" score={ready_score:.3f}"
        if ready_diagnostics:
            ready_part += f" ({ready_diagnostics})"

        digit_part = "digit_score=none" if digit_score is None else f"digit_score={digit_score:.3f}"
        if digit_diagnostics:
            digit_part += f" ({digit_diagnostics})"
        return f"Scan: level={level_text}, {ready_part}, {digit_part}."
