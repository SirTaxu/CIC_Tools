from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from crafting_bot import paths
from crafting_bot.factory import build_adb_client, build_calibration_store
from crafting_bot.services.ready_state_training_service import ReadyStateTrainingService
from crafting_bot.vision.image_tools import crop_area, save_preview


def main() -> int:
    parser = argparse.ArgumentParser(description="Train an explicit ready/not-ready template for the current level area.")
    parser.add_argument("level", type=int, help="The true visible level number. Must be >= 1.")
    parser.add_argument("--state", choices=("yes", "no"), required=True, help="Use yes only if the level is visibly ready.")
    parser.add_argument("--source", default="manual", help="Source label to store in filename/index. Default: manual.")
    parser.add_argument(
        "--from-latest-crop",
        action="store_true",
        help="Use logs/debug_crops/latest_level_area.png instead of capturing a new ADB screenshot.",
    )
    args = parser.parse_args()

    if args.level < 1:
        raise SystemExit("Refusing to train level 0. Level 0 does not exist.")

    crop = _load_or_capture_crop(from_latest=args.from_latest_crop)
    result = ReadyStateTrainingService().save_ready_template(
        level=args.level,
        state=args.state,
        crop=crop,
        source_label=args.source,
    )

    print(result.message)
    print(f"level: {result.level}")
    print(f"state: {result.state}")
    print(f"template_path: {result.template_path}")
    print(f"duplicate: {result.duplicate}")
    print(f"index_action: {result.index_action}")
    print("")
    print("Next check:")
    print('$env:PYTHONDONTWRITEBYTECODE="1"; python -B -m crafting_bot.cli.template_report')
    return 0


def _load_or_capture_crop(*, from_latest: bool) -> Image.Image:
    if from_latest:
        if not paths.LATEST_LEVEL_CROP_PATH.exists():
            raise FileNotFoundError(f"Latest level crop not found: {paths.LATEST_LEVEL_CROP_PATH}")
        return Image.open(paths.LATEST_LEVEL_CROP_PATH).convert("RGB")

    adb = build_adb_client()
    screenshot = adb.capture_to_file(paths.LATEST_CALIBRATION_SCREENSHOT_PATH)

    calibration = build_calibration_store()
    level_area = calibration.get_area("level_area")
    crop = crop_area(screenshot, level_area)

    paths.DEBUG_CROP_DIR.mkdir(parents=True, exist_ok=True)
    crop.save(paths.LATEST_LEVEL_CROP_PATH)
    save_preview(crop, paths.LATEST_LEVEL_PREVIEW_PATH)
    return crop


if __name__ == "__main__":
    raise SystemExit(main())
