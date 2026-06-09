from __future__ import annotations

from pathlib import Path
from typing import Protocol

from PIL import Image


class ScreenCapture(Protocol):
    def capture(self) -> Image.Image:
        """Return a current screenshot as a PIL image."""


class Tapper(Protocol):
    def tap(self, x: int, y: int) -> None:
        """Tap/click a coordinate in the controlled target."""


class CalibrationReader(Protocol):
    def get_area(self, name: str):
        """Return an area target by name."""

    def get_point(self, name: str):
        """Return a point target by name."""
