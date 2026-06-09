from __future__ import annotations

from PIL import Image

from crafting_bot import paths
from crafting_bot.domain.target_catalog import get_search_target_definition, get_target_definition
from crafting_bot.infra.calibration_store import CalibrationStore


class TargetStatusService:
    """Describes target readiness for reports without executing bot actions."""

    def __init__(self, store: CalibrationStore) -> None:
        self.store = store

    def describe(self, target_name: str) -> str:
        target = get_target_definition(target_name)
        if target is None:
            search_target = get_search_target_definition(target_name)
            if search_target is not None:
                template_status = self.describe(search_target.template_area_name)
                search_area_status = self.describe(search_target.search_area_name)
                return f"search target; template: {template_status}; search area: {search_area_status}"
            return "unknown target"

        if target.kind == "point":
            if not self.store.has_point(target.name):
                return "missing point"
            point = self.store.get_point(target.name)
            return f"point ok x={point.x}, y={point.y}"

        if not self.store.has_area(target.name):
            return "missing area"
        area = self.store.get_area(target.name)
        return (
            f"area ok x={area.x}, y={area.y}, width={area.width}, height={area.height}; "
            f"{self.crop_status(target.name, (area.width, area.height))}"
        )

    @staticmethod
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
