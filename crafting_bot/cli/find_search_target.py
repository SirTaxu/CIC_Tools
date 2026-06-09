from __future__ import annotations

import argparse

from crafting_bot import paths
from crafting_bot.domain.target_catalog import SEARCH_TARGETS, get_search_target_definition
from crafting_bot.factory import build_adb_client, build_search_target_service


def main() -> int:
    names = [target.name for target in SEARCH_TARGETS]
    parser = argparse.ArgumentParser(description="Find a dynamic visual target without clicking it.")
    parser.add_argument("target", nargs="?", default="rebuild_button_dynamic", choices=names)
    args = parser.parse_args()

    definition = get_search_target_definition(args.target)
    if definition is None:
        print("ok: False")
        print(f"message: Unknown search target: {args.target}")
        return 2

    adb = build_adb_client()
    screenshot = adb.capture_to_file(paths.LATEST_CALIBRATION_SCREENSHOT_PATH)
    service = build_search_target_service()
    try:
        run_result = service.run(definition, screenshot=screenshot, save_preview=True)
    except Exception as exc:
        print("ok: False")
        print(f"message: {exc}")
        return 1

    result = run_result.result
    print(f"ok: {result.ok}")
    print(f"target: {definition.name}")
    print(f"template: {run_result.template_path}")
    print(f"search_area: {definition.search_area_name}")
    print(f"score: {result.score}")
    print(f"x: {result.x}")
    print(f"y: {result.y}")
    print(f"width: {result.width}")
    print(f"height: {result.height}")
    print(f"center_x: {result.center_x}")
    print(f"center_y: {result.center_y}")
    print(f"threshold: {definition.default_threshold}")
    print(f"search_axis: {definition.search_axis}")
    print(f"x_tolerance: {definition.x_tolerance}")
    print(f"evaluated_positions: {result.evaluated_positions}")
    print(f"accepted_by_default_threshold: {bool(result.ok and result.score is not None and result.score <= definition.default_threshold)}")
    print(f"preview_path: {run_result.preview_path}")
    print(f"message: {result.message}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
