from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from crafting_bot.domain.models import AreaTarget, PointTarget


class CalibrationStore:
    """Loads calibrated click points and crop areas from adb_bot_config.json."""

    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self._points: dict[str, PointTarget] = {}
        self._areas: dict[str, AreaTarget] = {}
        self._raw: dict[str, Any] = {}

    def load(self) -> None:
        if not self.config_path.exists():
            raise FileNotFoundError(f"Missing calibration file: {self.config_path}")

        with self.config_path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)

        self._raw = raw

        targets = raw.get("targets")
        if not isinstance(targets, dict):
            raise ValueError("Calibration file does not contain a valid 'targets' object.")

        points: dict[str, PointTarget] = {}
        areas: dict[str, AreaTarget] = {}

        for name, value in targets.items():
            if not isinstance(value, dict):
                continue

            if self._is_area(value):
                areas[name] = AreaTarget(
                    name=name,
                    x=int(value["x"]),
                    y=int(value["y"]),
                    width=int(value["width"]),
                    height=int(value["height"]),
                )
            elif self._is_point(value):
                points[name] = PointTarget(
                    name=name,
                    x=int(value["x"]),
                    y=int(value["y"]),
                )

        self._points = points
        self._areas = areas


    def save(self) -> None:
        targets = self._raw.setdefault("targets", {})
        if not isinstance(targets, dict):
            targets = {}
            self._raw["targets"] = targets

        for name, target in self._points.items():
            targets[name] = {"x": int(target.x), "y": int(target.y)}

        for name, target in self._areas.items():
            targets[name] = {
                "x": int(target.x),
                "y": int(target.y),
                "width": int(target.width),
                "height": int(target.height),
            }

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open("w", encoding="utf-8") as handle:
            json.dump(self._raw, handle, indent=2)
            handle.write("\n")

    def update_point(self, target: PointTarget) -> None:
        self._points[target.name] = target
        self._areas.pop(target.name, None)

    def update_area(self, target: AreaTarget) -> None:
        self._areas[target.name] = target
        self._points.pop(target.name, None)

    def list_point_names(self) -> list[str]:
        return sorted(self._points)

    def list_area_names(self) -> list[str]:
        return sorted(self._areas)

    def get_area(self, name: str) -> AreaTarget:
        try:
            return self._areas[name]
        except KeyError as exc:
            raise KeyError(f"Missing calibrated area: {name}") from exc

    def get_point(self, name: str) -> PointTarget:
        try:
            return self._points[name]
        except KeyError as exc:
            raise KeyError(f"Missing calibrated point: {name}") from exc

    def has_area(self, name: str) -> bool:
        return name in self._areas

    def has_point(self, name: str) -> bool:
        return name in self._points

    @staticmethod
    def _is_point(value: dict[str, Any]) -> bool:
        return "x" in value and "y" in value and "width" not in value and "height" not in value

    @staticmethod
    def _is_area(value: dict[str, Any]) -> bool:
        return all(key in value for key in ("x", "y", "width", "height"))
