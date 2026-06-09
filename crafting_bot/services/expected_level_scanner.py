from __future__ import annotations

from pathlib import Path

from PIL import Image

from crafting_bot.domain.models import LevelScanResult
from crafting_bot.domain.ports import ScreenCapture
from crafting_bot.infra.calibration_store import CalibrationStore
from crafting_bot.vision.digit_reader import DigitReader
from crafting_bot.vision.image_tools import crop_area, save_preview
from crafting_bot.vision.ready_detector import ReadyDetector


class ExpectedLevelScanner:
    """Scan the level badge while tracking a known expected level.

    The normal LevelScanner is intentionally broad: it can be used when the bot
    does not yet know which level is visible. Once the loop has completed two
    consecutive levels, the expected next level is known. This scanner restricts
    ready/not-ready comparison to that expected level and restricts digit
    matching to the digits that can appear in that expected level.

    If the expected level's ready/not-ready marker is visible but the digits are
    weak or unreadable, the result keeps level=None so the loop can train digit
    templates from the saved crop before clicking.
    """

    def __init__(
        self,
        *,
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

    def scan_expected(self, expected_level: int) -> LevelScanResult:
        expected_level = int(expected_level)
        expected_text = str(expected_level)
        allowed_digits = set(expected_text)

        try:
            screenshot = self.screen_capture.capture()
            self.screenshot_path.parent.mkdir(parents=True, exist_ok=True)
            screenshot.save(self.screenshot_path)

            level_area = self.calibration.get_area("level_area")
            level_crop = crop_area(screenshot, level_area)
            self.level_crop_path.parent.mkdir(parents=True, exist_ok=True)
            level_crop.save(self.level_crop_path)
            save_preview(level_crop, self.level_preview_path)

            ready_match = self.ready_detector.classify(
                level_crop,
                level_hint=expected_level,
                require_level_templates=True,
            )

            raw_level_text, digit_matches = self.digit_reader.read(level_crop, allowed_digits=allowed_digits)
            raw_level = int(raw_level_text) if raw_level_text.isdigit() else None
            digit_score = min((match.score for match in digit_matches), default=None)
            digit_diagnostics = self.digit_reader.diagnostics_for_last_read()

            if raw_level == expected_level:
                level_text = expected_text
                level = expected_level
            else:
                level_text = "unknown"
                level = None

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
                    expected_level=expected_level,
                    raw_level_text=raw_level_text,
                    final_level_text=level_text,
                    ready=ready_match.state,
                    ready_score=ready_match.score,
                    digit_score=digit_score,
                    digit_diagnostics=digit_diagnostics,
                ),
                digit_diagnostics=digit_diagnostics,
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
                message=f"Expected-level scan failed for level {expected_level}: {exc}",
                digit_diagnostics=None,
            )

    @staticmethod
    def _format_message(
        *,
        expected_level: int,
        raw_level_text: str,
        final_level_text: str,
        ready: str,
        ready_score: float | None,
        digit_score: float | None,
        digit_diagnostics: str | None,
    ) -> str:
        ready_part = f"ready={ready}"
        if ready_score is not None:
            ready_part += f" score={ready_score:.3f}"

        digit_part = "digit_score=none" if digit_score is None else f"digit_score={digit_score:.3f}"
        if digit_diagnostics:
            digit_part += f" ({digit_diagnostics})"

        return (
            f"Expected-level scan: expected={expected_level}, raw_digits={raw_level_text}, "
            f"level={final_level_text}, {ready_part}, {digit_part}."
        )
