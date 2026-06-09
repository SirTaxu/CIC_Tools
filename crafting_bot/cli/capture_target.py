from __future__ import annotations

import argparse

from crafting_bot import paths
from crafting_bot.factory import build_adb_client, build_calibration_service


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the saved crop image for one calibrated area target.")
    parser.add_argument("target", help="Area target name, for example rebuild_button_check_area")
    args = parser.parse_args()

    adb = build_adb_client()
    screenshot = adb.capture_to_file(paths.LATEST_CALIBRATION_SCREENSHOT_PATH)

    service = build_calibration_service()
    result = service.refresh_area_crop(args.target, screenshot)
    print("ok: True")
    print(result.message)
    print(f"crop_path: {result.crop_path}")
    print(f"preview_path: {result.preview_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
