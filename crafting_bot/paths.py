from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
DEBUG_CROP_DIR = LOG_DIR / "debug_crops"
CALIBRATION_CROP_DIR = DATA_DIR / "calibration" / "adb_calibration_crops"

CALIBRATION_PATH = DATA_DIR / "calibration" / "adb_bot_config.json"
READY_TEMPLATE_DIR = DATA_DIR / "level_ready_templates"
DIGIT_TEMPLATE_DIR = DATA_DIR / "level_digit_templates"

LATEST_SCREENSHOT_PATH = LOG_DIR / "latest_adb_screenshot.png"
LATEST_CALIBRATION_SCREENSHOT_PATH = LOG_DIR / "latest_calibration_screenshot.png"
LATEST_LEVEL_CROP_PATH = DEBUG_CROP_DIR / "latest_level_area.png"
LATEST_LEVEL_PREVIEW_PATH = DEBUG_CROP_DIR / "latest_level_area_preview.png"
