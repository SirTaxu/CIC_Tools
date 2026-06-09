from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
from PIL import Image


@dataclass(frozen=True)
class ExtractedDigit:
    """One automatically isolated digit from a level-area crop."""

    x: int
    y: int
    width: int
    height: int
    area: int
    raw_crop: Image.Image
    mask: np.ndarray


@dataclass(frozen=True)
class DigitExtractionResult:
    """Result of automatic digit extraction from a level-area crop."""

    expected_text: str
    found_count: int
    digits: tuple[ExtractedDigit, ...]
    message: str


def level_digit_mask(image: Image.Image) -> np.ndarray:
    """
    Build the digit mask used by training and reading.

    The visible level digits are bright white/yellow strokes. The blue badge
    background is excluded so the digit body can be isolated from the badge and
    ready star.
    """

    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    r = rgb[:, :, 0].astype(np.int16)
    g = rgb[:, :, 1].astype(np.int16)
    b = rgb[:, :, 2].astype(np.int16)

    bright = (r > 135) & (g > 120) & (b > 80)
    not_blue_bg = ~((b > r + 25) & (b > g + 20))
    return bright & not_blue_bg


def extract_digit_components(
    level_crop: Image.Image,
    *,
    max_digits: int = 3,
    padding: int = 2,
) -> tuple[ExtractedDigit, ...]:
    """
    Automatically isolate likely digit components from the level-area crop.

    This avoids scanning every digit template across the whole badge. The reader
    compares only digit-shaped components, which prevents a single ready level
    such as 1 or 2 from being confused with a different template elsewhere in
    the star/badge area.
    """

    mask = level_digit_mask(level_crop)
    components = _connected_components(mask)
    candidates = _digit_like_components(components, mask.shape)
    selected = sorted(candidates[:max_digits], key=lambda item: item["x1"])

    extracted: list[ExtractedDigit] = []
    for item in selected:
        x1, y1, x2, y2 = _expand_box(
            item["x1"],
            item["y1"],
            item["x2"],
            item["y2"],
            mask.shape[1],
            mask.shape[0],
            padding,
        )
        digit_mask = mask[y1:y2, x1:x2]
        raw_crop = level_crop.crop((x1, y1, x2, y2))
        extracted.append(
            ExtractedDigit(
                x=x1,
                y=y1,
                width=x2 - x1,
                height=y2 - y1,
                area=int(item["area"]),
                raw_crop=raw_crop,
                mask=digit_mask,
            )
        )

    return tuple(extracted)


def extract_digits_for_level(
    level_crop: Image.Image,
    expected_level: int | str,
    *,
    padding: int = 2,
) -> DigitExtractionResult:
    """
    Automatically isolate the digit shapes for the expected level text.

    This is intended for training from known states like "ready level 9". It
    uses the expected level only to know how many digit components should be
    kept. The label for each component still comes from the expected text.
    """

    expected_text = str(expected_level).strip()
    if not expected_text.isdigit():
        raise ValueError(f"Expected level must contain only digits, got {expected_level!r}.")
    if not expected_text:
        raise ValueError("Expected level cannot be empty.")

    expected_count = len(expected_text)
    extracted = extract_digit_components(level_crop, max_digits=expected_count, padding=padding)

    if len(extracted) != expected_count:
        message = (
            f"Expected {expected_count} digit component(s) for level {expected_text}, "
            f"but found {len(extracted)} usable candidate(s)."
        )
    else:
        message = f"Extracted {len(extracted)} digit component(s) for level {expected_text}."

    return DigitExtractionResult(
        expected_text=expected_text,
        found_count=len(extracted),
        digits=tuple(extracted),
        message=message,
    )


def normalize_digit_mask(mask: np.ndarray, *, width: int = 32, height: int = 48) -> Image.Image:
    """Save templates in the normalized black/white 32x48 format."""

    if mask.size == 0 or not mask.any():
        raise ValueError("Cannot normalize an empty digit mask.")

    ys, xs = np.where(mask)
    x1 = int(xs.min())
    x2 = int(xs.max()) + 1
    y1 = int(ys.min())
    y2 = int(ys.max()) + 1
    digit = mask[y1:y2, x1:x2]

    src_h, src_w = digit.shape
    if src_w <= 0 or src_h <= 0:
        raise ValueError("Cannot normalize an empty digit mask.")

    # Preserve shape, fit within a safe box inside 32x48.
    max_w = width - 6
    max_h = height - 6
    scale = min(max_w / src_w, max_h / src_h)
    scaled_w = max(1, int(round(src_w * scale)))
    scaled_h = max(1, int(round(src_h * scale)))

    source = Image.fromarray((digit.astype(np.uint8) * 255), mode="L")
    resample_filter = getattr(Image, "Resampling", Image).NEAREST
    resized = source.resize((scaled_w, scaled_h), resample_filter)

    canvas = Image.new("L", (width, height), 0)
    paste_x = (width - scaled_w) // 2
    paste_y = (height - scaled_h) // 2
    canvas.paste(resized, (paste_x, paste_y))
    return canvas


def _connected_components(mask: np.ndarray) -> list[dict[str, int]]:
    height, width = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    components: list[dict[str, int]] = []

    for y in range(height):
        for x in range(width):
            if not mask[y, x] or seen[y, x]:
                continue

            stack = [(x, y)]
            seen[y, x] = True
            xs: list[int] = []
            ys: list[int] = []

            while stack:
                cx, cy = stack.pop()
                xs.append(cx)
                ys.append(cy)

                for ny in range(cy - 1, cy + 2):
                    for nx in range(cx - 1, cx + 2):
                        if nx == cx and ny == cy:
                            continue
                        if nx < 0 or ny < 0 or nx >= width or ny >= height:
                            continue
                        if seen[ny, nx] or not mask[ny, nx]:
                            continue
                        seen[ny, nx] = True
                        stack.append((nx, ny))

            components.append(
                {
                    "area": len(xs),
                    "x1": min(xs),
                    "y1": min(ys),
                    "x2": max(xs) + 1,
                    "y2": max(ys) + 1,
                }
            )

    return components


def _digit_like_components(components: Iterable[dict[str, int]], shape: tuple[int, int]) -> list[dict[str, int]]:
    image_height, _image_width = shape
    candidates: list[dict[str, int]] = []

    for item in components:
        width = item["x2"] - item["x1"]
        height = item["y2"] - item["y1"]
        area = item["area"]
        bottom = item["y2"]

        # Single digit strokes tend to be tall and lower in the badge. Star
        # pieces are usually shallower and/or higher.
        if area < 35:
            continue
        if height < 14:
            continue
        if width < 4:
            continue
        if bottom < max(24, image_height // 2):
            continue

        candidates.append(item)

    # Keep largest digit-shaped components. For multi-digit levels, the final
    # result is sorted left-to-right after the largest likely components are
    # selected.
    return sorted(candidates, key=lambda item: item["area"], reverse=True)


def _expand_box(x1: int, y1: int, x2: int, y2: int, image_width: int, image_height: int, padding: int) -> tuple[int, int, int, int]:
    return (
        max(0, x1 - padding),
        max(0, y1 - padding),
        min(image_width, x2 + padding),
        min(image_height, y2 + padding),
    )
