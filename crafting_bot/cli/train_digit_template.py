from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from crafting_bot import paths
from crafting_bot.cli.calibration_ui import select_target
from crafting_bot.factory import build_adb_client, build_calibration_store
from crafting_bot.services.digit_training_service import DigitTrainingService
from crafting_bot.vision.image_tools import crop_area, save_preview


def _capture_level_crop() -> Image.Image:
    adb = build_adb_client()
    screenshot = adb.capture_to_file(paths.LATEST_CALIBRATION_SCREENSHOT_PATH)

    calibration = build_calibration_store()
    level_area = calibration.get_area("level_area")
    level_crop = crop_area(screenshot, level_area)

    paths.DEBUG_CROP_DIR.mkdir(parents=True, exist_ok=True)
    level_crop.save(paths.LATEST_LEVEL_CROP_PATH)
    save_preview(level_crop, paths.LATEST_LEVEL_PREVIEW_PATH)
    return level_crop


def _load_level_crop(path: Path) -> Image.Image:
    return Image.open(path).convert("RGB")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Manually add one digit template from the current level_area crop. "
            "Use this when a visible level digit is being confused, such as ready level 1 being read as 4."
        )
    )
    parser.add_argument("digit", help="Correct digit label to save, from 0 to 9. Example: 1")
    parser.add_argument(
        "--from-file",
        type=Path,
        default=None,
        help=(
            "Use an existing level-area crop instead of capturing from ADB. "
            "Example: logs/debug_crops/latest_level_area.png"
        ),
    )
    parser.add_argument(
        "--source-label",
        default="manual",
        help="Text included in the output filename, e.g. ready_single_level_1.",
    )
    args = parser.parse_args()

    digit = str(args.digit).strip()
    if len(digit) != 1 or digit not in "0123456789":
        print("ok: False")
        print(f"message: digit must be one character from 0 to 9, got {args.digit!r}.")
        return 2

    try:
        level_crop = _load_level_crop(args.from_file) if args.from_file else _capture_level_crop()
    except Exception as exc:
        print("ok: False")
        print(f"message: Could not prepare level crop: {exc}")
        return 1

    selected = select_target(level_crop, f"digit_{digit}_template", "area")
    if selected is None:
        print("ok: False")
        print("message: Digit training cancelled.")
        return 1

    digit_crop = crop_area(level_crop, selected)
    service = DigitTrainingService(
        template_dir=paths.DIGIT_TEMPLATE_DIR,
        preview_dir=paths.DEBUG_CROP_DIR,
    )

    try:
        result = service.save_digit_template(digit, digit_crop, source_label=args.source_label)
    except Exception as exc:
        print("ok: False")
        print(f"message: Could not save digit template: {exc}")
        return 1

    print("ok: True")
    print(result.message)
    print(f"digit: {result.digit}")
    print(f"template_path: {result.template_path}")
    print(f"preview_path: {result.preview_path}")
    print(f"width: {result.width}")
    print(f"height: {result.height}")
    print(f"level_crop_path: {paths.LATEST_LEVEL_CROP_PATH if not args.from_file else args.from_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
