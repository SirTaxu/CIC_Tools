from __future__ import annotations

import itertools
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from crafting_bot import paths
from crafting_bot.services.digit_training_service import DigitTrainingResult, DigitTrainingService
from crafting_bot.vision.digit_extractor import ExtractedDigit, extract_digit_components, normalize_digit_mask
from crafting_bot.vision.image_tools import save_preview


@dataclass(frozen=True)
class AutoDigitTrainingResult:
    ok: bool
    expected_level: int
    state: str
    crop_path: Path
    preview_path: Path | None
    saved_templates: tuple[DigitTrainingResult, ...]
    message: str


class AutoDigitTrainingService:
    """Train level digit templates from a saved level_area crop.

    This service is used by the rebuild loop when the level reader safely says
    "unknown", but the previous confirmed levels and ready-template match make
    the next expected level clear. It trains from the saved failed crop, not from
    a new live screenshot, because the live screen can change while the user is
    being asked for confirmation.
    """

    def __init__(
        self,
        *,
        training_service: DigitTrainingService,
        template_dir: Path,
        preview_dir: Path,
    ) -> None:
        self.training_service = training_service
        self.template_dir = template_dir
        self.preview_dir = preview_dir

    def train_from_crop(
        self,
        *,
        crop_path: Path,
        expected_level: int,
        state: str,
        source_label: str = "loop_auto",
    ) -> AutoDigitTrainingResult:
        expected_text = str(int(expected_level))
        state_label = _safe_label(state)
        source = _safe_label(f"{source_label}_{state_label}_level_{expected_text}")
        preview_path = self.preview_dir / f"auto_digit_training_{state_label}_level_{expected_text}.png"

        try:
            with Image.open(crop_path) as image:
                level_crop = image.convert("RGB")
        except Exception as exc:
            return AutoDigitTrainingResult(
                ok=False,
                expected_level=int(expected_level),
                state=state_label,
                crop_path=crop_path,
                preview_path=None,
                saved_templates=(),
                message=f"Could not open saved level crop {crop_path}: {exc}",
            )

        try:
            selected = self._extract_for_expected_level(level_crop, expected_text)
        except Exception as exc:
            return AutoDigitTrainingResult(
                ok=False,
                expected_level=int(expected_level),
                state=state_label,
                crop_path=crop_path,
                preview_path=None,
                saved_templates=(),
                message=f"Could not extract digit components for level {expected_text}: {exc}",
            )

        if len(selected) != len(expected_text):
            self._save_preview(level_crop, selected, preview_path)
            return AutoDigitTrainingResult(
                ok=False,
                expected_level=int(expected_level),
                state=state_label,
                crop_path=crop_path,
                preview_path=preview_path,
                saved_templates=(),
                message=(
                    f"Expected {len(expected_text)} digit component(s) for level {expected_text}, "
                    f"but selected {len(selected)}. Preview saved: {preview_path}"
                ),
            )

        saved: list[DigitTrainingResult] = []
        try:
            for expected_digit, component in zip(expected_text, selected):
                saved.append(
                    self.training_service.save_extracted_digit_template(
                        expected_digit,
                        component,
                        source_label=source,
                    )
                )
        except Exception as exc:
            self._save_preview(level_crop, selected, preview_path)
            return AutoDigitTrainingResult(
                ok=False,
                expected_level=int(expected_level),
                state=state_label,
                crop_path=crop_path,
                preview_path=preview_path,
                saved_templates=tuple(saved),
                message=f"Failed while saving digit templates for level {expected_text}: {exc}",
            )

        self._save_preview(level_crop, selected, preview_path)
        return AutoDigitTrainingResult(
            ok=True,
            expected_level=int(expected_level),
            state=state_label,
            crop_path=crop_path,
            preview_path=preview_path,
            saved_templates=tuple(saved),
            message=(
                f"Saved {len(saved)} digit template(s) for {state_label} level {expected_text} "
                f"from saved crop {crop_path}. Preview: {preview_path}"
            ),
        )

    def _extract_for_expected_level(self, level_crop: Image.Image, expected_text: str) -> tuple[ExtractedDigit, ...]:
        expected_count = len(expected_text)
        candidates = extract_digit_components(level_crop, max_digits=max(3, expected_count + 4))
        if len(candidates) < expected_count:
            return tuple(candidates)
        if len(candidates) == expected_count:
            return tuple(sorted(candidates, key=lambda item: item.x))

        selected = self._select_best_training_components(candidates, expected_text)
        if selected:
            return selected

        # Conservative fallback: keep the left-to-right components with the
        # largest areas, which matches the original automatic trainer behavior.
        largest = sorted(candidates, key=lambda item: item.area, reverse=True)[:expected_count]
        return tuple(sorted(largest, key=lambda item: item.x))

    def _select_best_training_components(
        self,
        candidates: Iterable[ExtractedDigit],
        expected_text: str,
    ) -> tuple[ExtractedDigit, ...]:
        masks_by_digit = self._load_template_masks_by_digit()
        if not masks_by_digit:
            return ()

        ordered = sorted(candidates, key=lambda item: item.x)
        expected_count = len(expected_text)
        best_combo: tuple[ExtractedDigit, ...] | None = None
        best_key: tuple[float, float, int, int] | None = None

        for indexes in itertools.combinations(range(len(ordered)), expected_count):
            combo = tuple(ordered[index] for index in indexes)
            score_sum = 0.0
            score_min = 1.0
            missing_template = False

            for component, expected_digit in zip(combo, expected_text):
                score = self._score_component_against_digit(component, expected_digit, masks_by_digit)
                if score is None:
                    missing_template = True
                    break
                score_sum += score
                score_min = min(score_min, score)

            if missing_template:
                continue

            # Prefer strong matches first. On ties, prefer a wider span because
            # badge/star noise often appears between the real outer digits.
            span = (combo[-1].x - combo[0].x) if len(combo) > 1 else 0
            area_sum = sum(component.area for component in combo)
            key = (score_sum, score_min, span, area_sum)
            if best_key is None or key > best_key:
                best_key = key
                best_combo = combo

        return best_combo or ()

    def _load_template_masks_by_digit(self) -> dict[str, list[np.ndarray]]:
        result: dict[str, list[np.ndarray]] = {}
        if not self.template_dir.exists():
            return result

        for path in sorted(self.template_dir.glob("digit_*.png")):
            parts = path.name.split("_")
            if len(parts) < 2 or parts[1] not in set("0123456789"):
                continue
            try:
                with Image.open(path) as image:
                    mask = self._mask_from_template_image(image)
            except Exception:
                continue
            if mask.any():
                result.setdefault(parts[1], []).append(mask)
        return result

    def _score_component_against_digit(
        self,
        component: ExtractedDigit,
        expected_digit: str,
        masks_by_digit: dict[str, list[np.ndarray]],
    ) -> float | None:
        templates = masks_by_digit.get(expected_digit)
        if not templates:
            return None

        normalized_image = normalize_digit_mask(component.mask)
        component_mask = self._mask_from_template_image(normalized_image)
        best = 0.0
        for template_mask in templates:
            if template_mask.shape != component_mask.shape:
                template_mask = self._resize_mask(template_mask, component_mask.shape[1], component_mask.shape[0])
            best = max(best, self._mask_score(component_mask, template_mask))
        return best

    @staticmethod
    def _mask_from_template_image(image: Image.Image) -> np.ndarray:
        gray = np.asarray(ImageOps.grayscale(image), dtype=np.uint8)
        return gray > 60

    @staticmethod
    def _resize_mask(mask: np.ndarray, width: int, height: int) -> np.ndarray:
        image = Image.fromarray((mask.astype(np.uint8) * 255), mode="L")
        resample_filter = getattr(Image, "Resampling", Image).NEAREST
        resized = image.resize((width, height), resample_filter)
        return np.asarray(resized, dtype=np.uint8) > 60

    @staticmethod
    def _mask_score(patch: np.ndarray, template: np.ndarray) -> float:
        patch_bool = patch.astype(bool)
        template_bool = template.astype(bool)
        intersection = np.logical_and(patch_bool, template_bool).sum()
        union = np.logical_or(patch_bool, template_bool).sum()
        if union == 0:
            return 0.0
        return float(intersection / union)

    @staticmethod
    def _save_preview(level_crop: Image.Image, digits: Iterable[ExtractedDigit], output_path: Path) -> None:
        preview = level_crop.convert("RGB").copy()
        draw = ImageDraw.Draw(preview)
        for index, digit in enumerate(digits, start=1):
            draw.rectangle(
                [digit.x, digit.y, digit.x + digit.width - 1, digit.y + digit.height - 1],
                outline=(255, 0, 0),
                width=1,
            )
            draw.text((digit.x, max(0, digit.y - 10)), str(index), fill=(255, 0, 0))

        scale = 6
        resample_filter = getattr(Image, "Resampling", Image).NEAREST
        preview = preview.resize((preview.width * scale, preview.height * scale), resample_filter)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        preview.save(output_path)


def build_default_auto_digit_training_service() -> AutoDigitTrainingService:
    return AutoDigitTrainingService(
        training_service=DigitTrainingService(
            template_dir=paths.DIGIT_TEMPLATE_DIR,
            preview_dir=paths.DEBUG_CROP_DIR,
        ),
        template_dir=paths.DIGIT_TEMPLATE_DIR,
        preview_dir=paths.DEBUG_CROP_DIR,
    )


def _safe_label(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in str(value)).strip("_")
    return cleaned or "unknown"
