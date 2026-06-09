from __future__ import annotations

from PIL import Image

from crafting_bot import paths
from crafting_bot.domain.target_catalog import PHASE_ORDER, SEARCH_TARGETS, TARGETS, TargetDefinition
from crafting_bot.factory import build_calibration_store


def crop_status(name: str, expected_size: tuple[int, int] | None) -> str:
    crop_path = paths.CALIBRATION_CROP_DIR / f"{name}.png"
    if not crop_path.exists():
        return "missing crop"
    try:
        with Image.open(crop_path) as image:
            actual = image.size
    except Exception as exc:
        return f"bad crop: {exc}"

    if expected_size and actual != expected_size:
        return f"crop size mismatch: actual={actual[0]}x{actual[1]}, expected={expected_size[0]}x{expected_size[1]}"
    return f"crop ok: {actual[0]}x{actual[1]}"


def format_target_line(store, target: TargetDefinition) -> str:
    if target.kind == "point":
        if store.has_point(target.name):
            point = store.get_point(target.name)
            status = f"configured x={point.x}, y={point.y}"
        else:
            status = "missing point"
    else:
        if store.has_area(target.name):
            area = store.get_area(target.name)
            crop_info = crop_status(target.name, (area.width, area.height))
            status = f"configured x={area.x}, y={area.y}, width={area.width}, height={area.height}; {crop_info}"
        else:
            status = "missing area"

    return f"{target.name:<42} {target.kind:<5} {target.phase:<20} {status}"


def main() -> int:
    store = build_calibration_store()
    print("Calibration targets")
    print("=" * 120)
    print(f"Config: {paths.CALIBRATION_PATH}")
    print(f"Crops:  {paths.CALIBRATION_CROP_DIR}")
    print()

    for phase in PHASE_ORDER:
        print(phase)
        print("-" * 120)
        for target in TARGETS:
            if target.phase == phase:
                print(format_target_line(store, target))
        phase_search_targets = [target for target in SEARCH_TARGETS if target.phase == phase]
        for search_target in phase_search_targets:
            print(
                f"{search_target.name:<42} search {search_target.phase:<20} "
                f"template={search_target.template_area_name}, search_area={search_target.search_area_name}, "
                f"threshold={search_target.default_threshold:.3f}, axis={search_target.search_axis}, "
                f"x_tolerance={search_target.x_tolerance}"
            )
        print()

    known_names = {target.name for target in TARGETS}
    extra_points = [name for name in store.list_point_names() if name not in known_names]
    extra_areas = [name for name in store.list_area_names() if name not in known_names]
    if extra_points or extra_areas:
        print("legacy/extra")
        print("-" * 120)
        for name in extra_points:
            point = store.get_point(name)
            print(f"{name:<42} point legacy               configured x={point.x}, y={point.y}")
        for name in extra_areas:
            area = store.get_area(name)
            crop_info = crop_status(name, (area.width, area.height))
            print(f"{name:<42} area  legacy               configured x={area.x}, y={area.y}, width={area.width}, height={area.height}; {crop_info}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
