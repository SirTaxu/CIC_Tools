from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from crafting_bot.vision.digit_extractor import ExtractedDigit, normalize_digit_mask
from crafting_bot.vision.image_tools import save_preview


@dataclass(frozen=True)
class DigitTrainingResult:
    digit: str
    template_path: Path
    preview_path: Path
    width: int
    height: int
    message: str


class DigitTrainingService:
    """Saves digit crops as reusable normalized digit templates."""

    def __init__(self, template_dir: Path, preview_dir: Path) -> None:
        self.template_dir = template_dir
        self.preview_dir = preview_dir

    def save_digit_template(
        self,
        digit: str,
        digit_crop: Image.Image,
        *,
        source_label: str = "manual",
    ) -> DigitTrainingResult:
        """
        Save a manually selected digit crop.

        Manual crops are still accepted, but they are normalized into the same
        black/white 32x48 template format used by the older digit samples.
        """

        normalized_digit = self._validate_digit(digit)
        clean_crop = digit_crop.convert("RGB")

        if clean_crop.width < 4 or clean_crop.height < 8:
            raise ValueError(
                f"Selected digit crop is too small: {clean_crop.width}x{clean_crop.height}. "
                "Select the full visible digit, not only part of it."
            )

        # Reuse the reader-style mask for manually selected crops, then store a
        # normalized black/white template. This avoids mixing raw RGB templates
        # with the older normalized mask templates.
        from crafting_bot.vision.digit_extractor import level_digit_mask

        mask = level_digit_mask(clean_crop)
        if mask.sum() < 8:
            raise ValueError(
                "Selected crop did not contain enough bright digit pixels. "
                "Select the visible digit stroke, not the background."
            )

        normalized_crop = normalize_digit_mask(mask)
        return self._save_normalized_template(
            normalized_digit,
            normalized_crop,
            source_label=source_label,
        )

    def save_extracted_digit_template(
        self,
        digit: str,
        extracted: ExtractedDigit,
        *,
        source_label: str = "auto",
    ) -> DigitTrainingResult:
        """Save an automatically isolated digit component as a normalized template."""

        normalized_digit = self._validate_digit(digit)
        normalized_crop = normalize_digit_mask(extracted.mask)
        return self._save_normalized_template(
            normalized_digit,
            normalized_crop,
            source_label=source_label,
        )

    def _save_normalized_template(
        self,
        digit: str,
        normalized_crop: Image.Image,
        *,
        source_label: str,
    ) -> DigitTrainingResult:
        self.template_dir.mkdir(parents=True, exist_ok=True)
        self.preview_dir.mkdir(parents=True, exist_ok=True)

        clean_crop = normalized_crop.convert("L")
        stamp = time.strftime("%Y%m%d_%H%M%S")
        digest = hashlib.sha1(clean_crop.tobytes()).hexdigest()[:10]
        safe_source = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in source_label).strip("_")
        if not safe_source:
            safe_source = "manual"

        template_path = self.template_dir / f"digit_{digit}_{safe_source}_{stamp}_{digest}.png"
        preview_path = self.preview_dir / f"digit_{digit}_{safe_source}_{stamp}_{digest}_preview.png"

        clean_crop.save(template_path)
        save_preview(clean_crop, preview_path)

        return DigitTrainingResult(
            digit=digit,
            template_path=template_path,
            preview_path=preview_path,
            width=clean_crop.width,
            height=clean_crop.height,
            message=(
                f"Saved digit {digit} template: {clean_crop.width}x{clean_crop.height} normalized mask. "
                "Run scan_once again to verify recognition."
            ),
        )

    @staticmethod
    def _validate_digit(digit: str) -> str:
        value = str(digit).strip()
        if len(value) != 1 or value not in "0123456789":
            raise ValueError(f"Digit must be one character from 0 to 9, got {digit!r}.")
        return value
