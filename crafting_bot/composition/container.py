from __future__ import annotations

import json
from pathlib import Path

from crafting_bot import paths
from crafting_bot.application.bot_controller import BotController
from crafting_bot.infra.adb_client import AdbClient
from crafting_bot.infra.calibration_store import CalibrationStore
from crafting_bot.services.calibration_service import CalibrationService
from crafting_bot.services.cycle_dry_run_service import CycleDryRunService
from crafting_bot.services.cycle_runner import CycleRunner
from crafting_bot.services.digit_training_service import DigitTrainingService
from crafting_bot.services.expected_level_scanner import ExpectedLevelScanner
from crafting_bot.services.hire_runner import HireRunner
from crafting_bot.services.level_scanner import LevelScanner
from crafting_bot.services.rebuild_loop_runner import RebuildLoopRunner
from crafting_bot.services.reincarnation_runner import ReincarnationRunner
from crafting_bot.services.screen_verifier import ScreenVerifier
from crafting_bot.services.screen_waiter import ScreenWaiter
from crafting_bot.services.search_target_service import SearchTargetService
from crafting_bot.services.target_status_service import TargetStatusService
from crafting_bot.vision.digit_reader import DigitReader
from crafting_bot.vision.ready_detector import ReadyDetector


class BotContainer:
    """Composition root for the bot.

    This class centralizes construction of infrastructure, vision, and service
    objects. Keeping construction here prevents GUI/CLI drift and avoids hidden
    patch conflicts around constructor arguments.

    Instances are intentionally lightweight and not cached globally. Each CLI or
    GUI run gets fresh calibration/templates from disk, preserving the previous
    behavior of the tool.
    """

    def read_adb_path(self, config_path: Path = paths.CALIBRATION_PATH) -> str | None:
        try:
            with config_path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except Exception:
            return None

        adb_path = raw.get("adb_path")
        return str(adb_path) if adb_path else None

    def build_adb_client(self) -> AdbClient:
        return AdbClient(adb_path=self.read_adb_path())

    def build_calibration_store(self) -> CalibrationStore:
        calibration = CalibrationStore(paths.CALIBRATION_PATH)
        calibration.load()
        return calibration

    def build_ready_detector(self) -> ReadyDetector:
        ready_detector = ReadyDetector(paths.READY_TEMPLATE_DIR)
        ready_detector.load()
        return ready_detector

    def build_digit_reader(self) -> DigitReader:
        digit_reader = DigitReader(paths.DIGIT_TEMPLATE_DIR)
        digit_reader.load()
        return digit_reader

    def build_level_scanner(self) -> LevelScanner:
        return LevelScanner(
            screen_capture=self.build_adb_client(),
            calibration=self.build_calibration_store(),
            ready_detector=self.build_ready_detector(),
            digit_reader=self.build_digit_reader(),
            screenshot_path=paths.LATEST_SCREENSHOT_PATH,
            level_crop_path=paths.LATEST_LEVEL_CROP_PATH,
            level_preview_path=paths.LATEST_LEVEL_PREVIEW_PATH,
        )

    def build_expected_level_scanner(self) -> ExpectedLevelScanner:
        return ExpectedLevelScanner(
            screen_capture=self.build_adb_client(),
            calibration=self.build_calibration_store(),
            ready_detector=self.build_ready_detector(),
            digit_reader=self.build_digit_reader(),
            screenshot_path=paths.LATEST_SCREENSHOT_PATH,
            level_crop_path=paths.LATEST_LEVEL_CROP_PATH,
            level_preview_path=paths.LATEST_LEVEL_PREVIEW_PATH,
        )

    def build_calibration_service(self) -> CalibrationService:
        return CalibrationService(
            store=self.build_calibration_store(),
            crop_dir=paths.CALIBRATION_CROP_DIR,
            preview_dir=paths.DEBUG_CROP_DIR,
        )

    def build_digit_training_service(self) -> DigitTrainingService:
        return DigitTrainingService(
            template_dir=paths.DIGIT_TEMPLATE_DIR,
            preview_dir=paths.DEBUG_CROP_DIR,
        )

    def build_search_target_service(self) -> SearchTargetService:
        return SearchTargetService(
            calibration=self.build_calibration_store(),
            crop_dir=paths.CALIBRATION_CROP_DIR,
            preview_dir=paths.DEBUG_CROP_DIR,
        )

    def build_cycle_dry_run_service(self) -> CycleDryRunService:
        calibration = self.build_calibration_store()
        return CycleDryRunService(
            scanner=self.build_level_scanner(),
            calibration=calibration,
            target_status=TargetStatusService(calibration),
            search_targets=self.build_search_target_service(),
            latest_screenshot_path=paths.LATEST_SCREENSHOT_PATH,
        )

    def build_screen_verifier(self) -> ScreenVerifier:
        return ScreenVerifier(
            calibration=self.build_calibration_store(),
            scanner=self.build_level_scanner(),
            preview_dir=paths.DEBUG_CROP_DIR,
        )

    def build_screen_waiter(self) -> ScreenWaiter:
        return ScreenWaiter(
            adb=self.build_adb_client(),
            verifier=self.build_screen_verifier(),
            search_targets=self.build_search_target_service(),
            latest_screenshot_path=paths.LATEST_SCREENSHOT_PATH,
        )

    def build_cycle_runner(self) -> CycleRunner:
        calibration = self.build_calibration_store()
        search_targets = self.build_search_target_service()
        verifier = ScreenVerifier(
            calibration=calibration,
            scanner=self.build_level_scanner(),
            preview_dir=paths.DEBUG_CROP_DIR,
        )
        waiter = ScreenWaiter(
            adb=self.build_adb_client(),
            verifier=verifier,
            search_targets=search_targets,
            latest_screenshot_path=paths.LATEST_SCREENSHOT_PATH,
        )
        return CycleRunner(
            scanner=self.build_level_scanner(),
            adb=self.build_adb_client(),
            calibration=calibration,
            search_targets=search_targets,
            verifier=verifier,
            waiter=waiter,
            target_status=TargetStatusService(calibration),
            latest_screenshot_path=paths.LATEST_SCREENSHOT_PATH,
        )

    def build_hire_runner(self) -> HireRunner:
        return HireRunner(
            adb=self.build_adb_client(),
            calibration=self.build_calibration_store(),
            waiter=self.build_screen_waiter(),
        )

    def build_reincarnation_runner(self) -> ReincarnationRunner:
        return ReincarnationRunner(
            adb=self.build_adb_client(),
            calibration=self.build_calibration_store(),
            waiter=self.build_screen_waiter(),
            scanner=self.build_level_scanner(),
        )

    def build_rebuild_loop_runner(self) -> RebuildLoopRunner:
        return RebuildLoopRunner(
            scanner=self.build_level_scanner(),
            expected_scanner=self.build_expected_level_scanner(),
            cycle_runner=self.build_cycle_runner(),
            reincarnation_runner=self.build_reincarnation_runner(),
            hire_runner=self.build_hire_runner(),
        )

    def build_bot_controller(self) -> BotController:
        return BotController(rebuild_loop_runner=self.build_rebuild_loop_runner())
