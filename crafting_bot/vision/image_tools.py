from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from crafting_bot.domain.models import AreaTarget


def crop_area(image: Image.Image, area: AreaTarget) -> Image.Image:
    return image.crop((area.x, area.y, area.x + area.width, area.y + area.height))


def center_crop_to(image: Image.Image, width: int, height: int) -> Image.Image:
    if image.width < width or image.height < height:
        return image.resize((width, height))

    left = max(0, (image.width - width) // 2)
    top = max(0, (image.height - height) // 2)
    return image.crop((left, top, left + width, top + height))


def grayscale_array(image: Image.Image) -> np.ndarray:
    return np.asarray(ImageOps.grayscale(image), dtype=np.float32)


def normalized_mae(a: Image.Image, b: Image.Image) -> float:
    width = min(a.width, b.width)
    height = min(a.height, b.height)
    a2 = center_crop_to(a.convert("RGB"), width, height)
    b2 = center_crop_to(b.convert("RGB"), width, height)

    arr_a = np.asarray(a2, dtype=np.float32)
    arr_b = np.asarray(b2, dtype=np.float32)
    return float(np.mean(np.abs(arr_a - arr_b)) / 255.0)


def save_preview(crop: Image.Image, path: Path, scale: int = 4) -> None:
    preview = ImageOps.autocontrast(ImageOps.grayscale(crop))
    resample_filter = getattr(Image, "Resampling", Image).NEAREST
    preview = preview.resize((preview.width * scale, preview.height * scale), resample_filter)
    path.parent.mkdir(parents=True, exist_ok=True)
    preview.save(path)
