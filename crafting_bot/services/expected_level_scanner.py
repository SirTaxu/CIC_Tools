from __future__ import annotations

from pathlib import Path

from crafting_bot.domain.models import LevelScanResult
from crafting_bot.domain.ports import ScreenCapture
from crafting_bot.infra.calibration_store import CalibrationStore
from crafting_bot.vision.digit_reader import DigitReader
from crafting_bot.vision.image_tools import crop_area, save_preview
from crafting_bot.vision.ready_detector import ReadyDetector


class ExpectedLevelScanner:
    """Scan the level badge while using an expected level as context only.

    The expected level is a hint, not proof. A normal broad digit read is always
    attempted first because it is the safest source for the actual visible level.
    A restricted expected-level read is used only when the broad read is unknown;
    it must never override a readable broad result.
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

            broad_text, broad_matches = self.digit_reader.read(level_crop)
            broad_level = int(broad_text) if broad_text.isdigit() else None
            broad_diagnostics = self.digit_reader.diagnostics_for_last_read()

            selected_text = broad_text
            selected_level = broad_level
            selected_matches = broad_matches
            selected_source = "broad"
            restricted_text: str | None = None
            restricted_diagnostics: str | None = None

            # Restricted reads are a fallback for unreadable crops only. If the
            # broad read already produced a number, that number is the observed
            # level even when it differs from the expected level.
            if broad_level is None:
                restricted_matches = []
                restricted_text, restricted_matches = self.digit_reader.read(
                    level_crop,
                    allowed_digits=allowed_digits,
                )
                restricted_diagnostics = self.digit_reader.diagnostics_for_last_read()
                restricted_level = int(restricted_text) if restricted_text.isdigit() else None

                if restricted_level == expected_level:
                    selected_text = restricted_text
                    selected_level = restricted_level
                    selected_matches = restricted_matches
                    selected_source = "restricted_expected_fallback"

            digit_score = min((match.score for match in selected_matches), default=None)
            level_text = str(selected_level) if selected_level is not None else "unknown"

            ready_level_hint = selected_level if selected_level is not None else expected_level
            ready_match = self.ready_detector.classify(
                level_crop,
                level_hint=ready_level_hint,
                require_level_templates=False,
            )
            ready_diagnostics = self.ready_detector.diagnostics_for_last_match()

            return LevelScanResult(
                ok=True,
                screen="LEVEL_SCREEN",
                level_text=level_text,
                level=selected_level,
                ready=ready_match.state,
                ready_score=ready_match.score,
                ready_template=ready_match.template_path.name if ready_match.template_path else None,
                digit_score=digit_score,
                level_crop_path=self.level_crop_path,
                message=self._format_message(
                    expected_level=expected_level,
                    broad_text=broad_text,
                    restricted_text=restricted_text,
                    final_level_text=level_text,
                    selected_source=selected_source,
                    ready=ready_match.state,
                    ready_score=ready_match.score,
                    digit_score=digit_score,
                    broad_diagnostics=broad_diagnostics,
                    restricted_diagnostics=restricted_diagnostics,
                    ready_diagnostics=ready_diagnostics,
                ),
                digit_diagnostics=broad_diagnostics if selected_source == "broad" else restricted_diagnostics,
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
                message=f"Expected-level scan failed for level {expected_level}: {exc}",
                digit_diagnostics=None,
                ready_diagnostics=None,
            )

    @staticmethod
    def _format_message(
        *,
        expected_level: int,
        broad_text: str,
        restricted_text: str | None,
        final_level_text: str,
        selected_source: str,
        ready: str,
        ready_score: float | None,
        digit_score: float | None,
        broad_diagnostics: str | None,
        restricted_diagnostics: str | None,
        ready_diagnostics: str | None,
    ) -> str:
        ready_part = f"ready={ready}"
        if ready_score is not None:
            ready_part += f" score={ready_score:.3f}"
        if ready_diagnostics:
            ready_part += f" ({ready_diagnostics})"

        digit_part = "digit_score=none" if digit_score is None else f"digit_score={digit_score:.3f}"
        diagnostics = broad_diagnostics if selected_source == "broad" else restricted_diagnostics
        if diagnostics:
            digit_part += f" ({diagnostics})"

        restricted_part = ""
        if restricted_text is not None:
            restricted_part = f", restricted_digits={restricted_text}"

        return (
            f"Expected-level scan: expected={expected_level}, broad_digits={broad_text}"
            f"{restricted_part}, selected={selected_source}, level={final_level_text}, "
            f"{ready_part}, {digit_part}."
        )
