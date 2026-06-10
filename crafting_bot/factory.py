from __future__ import annotations

from pathlib import Path

from crafting_bot import paths
from crafting_bot.application.bot_controller import BotController
from crafting_bot.composition.container import BotContainer
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
from crafting_bot.services.recovery_runner import RecoveryRunner
from crafting_bot.services.reward_selection_service import RewardSelectionService
from crafting_bot.services.screen_classifier import ScreenClassifier
from crafting_bot.services.screen_verifier import ScreenVerifier
from crafting_bot.services.screen_waiter import ScreenWaiter
from crafting_bot.services.search_target_service import SearchTargetService


def _container() -> BotContainer:
    """Return a fresh composition container.

    Factory functions remain as compatibility wrappers for existing CLI/tools,
    but object construction now lives in crafting_bot.composition.container.
    """

    return BotContainer()


def _read_adb_path(config_path: Path) -> str | None:
    return _container().read_adb_path(config_path)


def build_bot_controller() -> BotController:
    return _container().build_bot_controller()


def build_level_scanner() -> LevelScanner:
    return _container().build_level_scanner()


def build_expected_level_scanner() -> ExpectedLevelScanner:
    return _container().build_expected_level_scanner()


def build_adb_client() -> AdbClient:
    return _container().build_adb_client()


def build_calibration_store() -> CalibrationStore:
    return _container().build_calibration_store()


def build_calibration_service() -> CalibrationService:
    return _container().build_calibration_service()


def build_digit_training_service() -> DigitTrainingService:
    return _container().build_digit_training_service()


def build_search_target_service() -> SearchTargetService:
    return _container().build_search_target_service()


def build_cycle_dry_run_service() -> CycleDryRunService:
    return _container().build_cycle_dry_run_service()


def build_screen_verifier() -> ScreenVerifier:
    return _container().build_screen_verifier()


def build_screen_waiter() -> ScreenWaiter:
    return _container().build_screen_waiter()


def build_reward_selection_service() -> RewardSelectionService:
    return _container().build_reward_selection_service()


def build_cycle_runner() -> CycleRunner:
    return _container().build_cycle_runner()


def build_hire_runner() -> HireRunner:
    return _container().build_hire_runner()


def build_reincarnation_runner() -> ReincarnationRunner:
    return _container().build_reincarnation_runner()


def build_screen_classifier() -> ScreenClassifier:
    return _container().build_screen_classifier()


def build_recovery_runner() -> RecoveryRunner:
    return _container().build_recovery_runner()


def build_rebuild_loop_runner() -> RebuildLoopRunner:
    return _container().build_rebuild_loop_runner()
