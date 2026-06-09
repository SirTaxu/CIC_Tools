from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
from PIL import Image, ImageDraw

from crafting_bot.domain.models import AreaTarget
from crafting_bot.vision.image_tools import crop_area

SearchAxis = Literal["both", "vertical"]


@dataclass(frozen=True)
class TemplateSearchResult:
    ok: bool
    score: float | None
    x: int | None
    y: int | None
    width: int
    height: int
    center_x: int | None
    center_y: int | None
    message: str
    evaluated_positions: int = 0


class TemplateSearcher:
    """Searches one template crop inside one larger screenshot area.

    The default mode is a normal 2D template search. Dynamic rebuild-button
    detection can use vertical mode because the button X position is expected
    to be stable while the Y position changes.
    """

    def __init__(self, stride: int = 2, refine_radius: int = 4) -> None:
        self.stride = max(1, int(stride))
        self.refine_radius = max(0, int(refine_radius))

    def find(
        self,
        screenshot: Image.Image,
        search_area: AreaTarget,
        template: Image.Image,
        *,
        search_axis: SearchAxis = "both",
        x_tolerance: int = 8,
    ) -> TemplateSearchResult:
        search_crop = crop_area(screenshot, search_area).convert("RGB")
        template = template.convert("RGB")

        if template.width > search_crop.width or template.height > search_crop.height:
            return TemplateSearchResult(
                ok=False,
                score=None,
                x=None,
                y=None,
                width=template.width,
                height=template.height,
                center_x=None,
                center_y=None,
                message=(
                    f"Template {template.width}x{template.height} is larger than "
                    f"search area {search_crop.width}x{search_crop.height}."
                ),
            )

        search_arr = np.asarray(search_crop, dtype=np.int16)
        template_arr = np.asarray(template, dtype=np.int16)
        best_score = float("inf")
        best_local: tuple[int, int] | None = None

        max_y = search_crop.height - template.height
        max_x = search_crop.width - template.width

        x_positions = self._x_positions(max_x=max_x, template_width=template.width, search_width=search_crop.width, search_axis=search_axis, x_tolerance=x_tolerance)
        y_positions = range(0, max_y + 1, self.stride)

        evaluated = 0
        for y in y_positions:
            for x in x_positions:
                evaluated += 1
                score = self._score_at(search_arr, template_arr, x, y)
                if score < best_score:
                    best_score = score
                    best_local = (x, y)

        if best_local is None:
            return TemplateSearchResult(False, None, None, None, template.width, template.height, None, None, "No search positions were evaluated.")

        best_x, best_y = self._refine(search_arr, template_arr, best_local, max_x, max_y, search_axis=search_axis, x_tolerance=x_tolerance, search_width=search_crop.width, template_width=template.width)
        best_score = self._score_at(search_arr, template_arr, best_x, best_y)

        absolute_x = search_area.x + best_x
        absolute_y = search_area.y + best_y
        return TemplateSearchResult(
            ok=True,
            score=best_score,
            x=absolute_x,
            y=absolute_y,
            width=template.width,
            height=template.height,
            center_x=absolute_x + template.width // 2,
            center_y=absolute_y + template.height // 2,
            message=(
                f"Best template match at x={absolute_x}, y={absolute_y}, "
                f"score={best_score:.4f}, evaluated_positions={evaluated}."
            ),
            evaluated_positions=evaluated,
        )

    def _x_positions(
        self,
        *,
        max_x: int,
        template_width: int,
        search_width: int,
        search_axis: SearchAxis,
        x_tolerance: int,
    ) -> list[int]:
        if search_axis == "both":
            return list(range(0, max_x + 1, self.stride))

        centered_x = max(0, min(max_x, (search_width - template_width) // 2))
        tolerance = max(0, int(x_tolerance))
        start_x = max(0, centered_x - tolerance)
        end_x = min(max_x, centered_x + tolerance)
        return list(range(start_x, end_x + 1, self.stride)) or [centered_x]

    def _refine(
        self,
        search_arr: np.ndarray,
        template_arr: np.ndarray,
        best_local: tuple[int, int],
        max_x: int,
        max_y: int,
        *,
        search_axis: SearchAxis,
        x_tolerance: int,
        search_width: int,
        template_width: int,
    ) -> tuple[int, int]:
        if self.refine_radius <= 0:
            return best_local

        start_y = max(0, best_local[1] - self.refine_radius)
        end_y = min(max_y, best_local[1] + self.refine_radius)

        if search_axis == "both":
            start_x = max(0, best_local[0] - self.refine_radius)
            end_x = min(max_x, best_local[0] + self.refine_radius)
        else:
            # Keep vertical searches constrained to the calibrated X strip.
            allowed_x = self._x_positions(max_x=max_x, template_width=template_width, search_width=search_width, search_axis=search_axis, x_tolerance=x_tolerance)
            start_x = min(allowed_x)
            end_x = max(allowed_x)

        refined_score = float("inf")
        refined = best_local
        for y in range(start_y, end_y + 1):
            for x in range(start_x, end_x + 1):
                score = self._score_at(search_arr, template_arr, x, y)
                if score < refined_score:
                    refined_score = score
                    refined = (x, y)
        return refined

    @staticmethod
    def _score_at(search_arr: np.ndarray, template_arr: np.ndarray, x: int, y: int) -> float:
        window = search_arr[y : y + template_arr.shape[0], x : x + template_arr.shape[1], :]
        return float(np.mean(np.abs(window - template_arr)) / 255.0)


def save_match_preview(
    screenshot: Image.Image,
    result: TemplateSearchResult,
    path: Path,
    *,
    search_area: AreaTarget | None = None,
) -> None:
    preview = screenshot.convert("RGB").copy()
    draw = ImageDraw.Draw(preview)

    if search_area is not None:
        draw.rectangle(
            [search_area.x, search_area.y, search_area.x + search_area.width, search_area.y + search_area.height],
            outline=(255, 255, 0),
            width=2,
        )

    if result.ok and result.x is not None and result.y is not None:
        draw.rectangle(
            [result.x, result.y, result.x + result.width, result.y + result.height],
            outline=(255, 0, 0),
            width=3,
        )
        if result.center_x is not None and result.center_y is not None:
            r = 6
            draw.ellipse(
                [result.center_x - r, result.center_y - r, result.center_x + r, result.center_y + r],
                outline=(255, 0, 0),
                width=3,
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    preview.save(path)
