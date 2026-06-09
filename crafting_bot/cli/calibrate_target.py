from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from crafting_bot import paths
from crafting_bot.cli.calibration_ui import select_target
from crafting_bot.domain.models import AreaTarget, PointTarget
from crafting_bot.domain.target_catalog import infer_target_kind
from crafting_bot.factory import build_adb_client, build_calibration_service


def _load_screenshot(path: Path | None) -> Image.Image:
    if path is not None:
        return Image.open(path).convert("RGB")
    adb = build_adb_client()
    return adb.capture_to_file(paths.LATEST_CALIBRATION_SCREENSHOT_PATH)


def main() -> int:
    parser = argparse.ArgumentParser(description="Calibrate one point or area target from a live ADB screenshot.")
    parser.add_argument("target", help="Target name, for example rebuild_button_check_area or rebuild_button")
    parser.add_argument(
        "--kind",
        choices=("point", "area"),
        default=None,
        help="Target type. If omitted, it is inferred from the known target list or the target name.",
    )
    parser.add_argument(
        "--from-file",
        type=Path,
        default=None,
        help="Use an existing screenshot instead of capturing from ADB.",
    )
    args = parser.parse_args()

    kind = args.kind or infer_target_kind(args.target)
    if kind is None:
        print("ok: False")
        print(f"message: Could not infer target kind for {args.target!r}. Use --kind point or --kind area.")
        return 2

    screenshot = _load_screenshot(args.from_file)
    selected = select_target(screenshot, args.target, kind)
    if selected is None:
        print("ok: False")
        print("message: Calibration cancelled.")
        return 1

    service = build_calibration_service()
    if isinstance(selected, PointTarget):
        result = service.save_point(selected)
    elif isinstance(selected, AreaTarget):
        result = service.save_area(selected, screenshot)
    else:
        print("ok: False")
        print("message: Unexpected selection result.")
        return 1

    print("ok: True")
    print(result.message)
    print(f"config_path: {result.saved_config_path}")
    if result.crop_path:
        print(f"crop_path: {result.crop_path}")
    if result.preview_path:
        print(f"preview_path: {result.preview_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
