from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from crafting_bot import paths
from crafting_bot.factory import build_adb_client, build_calibration_store
from crafting_bot.services.digit_training_service import DigitTrainingService
from crafting_bot.vision.digit_extractor import DigitExtractionResult, extract_digit_components, normalize_digit_mask
from crafting_bot.vision.image_tools import crop_area, save_preview


def _capture_level_crop() -> Image.Image:
    adb = build_adb_client()
    screenshot = adb.capture_to_file(paths.LATEST_CALIBRATION_SCREENSHOT_PATH)

    calibration = build_calibration_store()
    level_area = calibration.get_area("level_area")
    level_crop = crop_area(screenshot, level_area)

    paths.DEBUG_CROP_DIR.mkdir(parents=True, exist_ok=True)
    level_crop.save(paths.LATEST_LEVEL_CROP_PATH)
    save_preview(level_crop, paths.LATEST_LEVEL_PREVIEW_PATH)
    return level_crop


def _load_level_crop(path: Path) -> Image.Image:
    return Image.open(path).convert("RGB")


def _save_detection_preview(level_crop: Image.Image, result, output_path: Path) -> None:
    preview = level_crop.convert("RGB").copy()
    draw = ImageDraw.Draw(preview)
    for index, digit in enumerate(result.digits, start=1):
        draw.rectangle(
            [digit.x, digit.y, digit.x + digit.width - 1, digit.y + digit.height - 1],
            outline=(255, 0, 0),
            width=1,
        )
        draw.text((digit.x, max(0, digit.y - 10)), str(index), fill=(255, 0, 0))

    # Save an enlarged preview because the level crop is tiny.
    scale = 6
    resample_filter = getattr(Image, "Resampling", Image).NEAREST
    preview = preview.resize((preview.width * scale, preview.height * scale), resample_filter)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    preview.save(output_path)



def _extract_digits_for_training(level_crop: Image.Image, expected_text: str) -> DigitExtractionResult:
    """Extract digits using the expected level to avoid saving noise as templates.

    The generic extractor may find extra star/badge fragments, especially around
    ready multi-digit levels such as 10 and 13. For training, we know the true
    text, so when extra candidates are present we choose the left-to-right group
    that best matches existing templates for the expected digits.
    """

    expected_count = len(expected_text)
    candidates = extract_digit_components(level_crop, max_digits=max(3, expected_count + 3))
    if len(candidates) <= expected_count:
        return DigitExtractionResult(
            expected_text=expected_text,
            found_count=len(candidates),
            digits=tuple(candidates),
            message=f"Extracted {len(candidates)} digit component(s) for level {expected_text}.",
        )

    selected = _select_best_training_components(candidates, expected_text)
    if not selected:
        selected = tuple(sorted(candidates[:expected_count], key=lambda item: item.x))
        message = (
            f"Extracted {len(selected)} digit component(s) for level {expected_text} using area fallback. "
            f"Inspect the preview before trusting these templates."
        )
    else:
        message = (
            f"Extracted {len(selected)} digit component(s) for level {expected_text} using template-guided selection "
            f"from {len(candidates)} candidate component(s)."
        )

    return DigitExtractionResult(
        expected_text=expected_text,
        found_count=len(selected),
        digits=tuple(selected),
        message=message,
    )


def _select_best_training_components(candidates, expected_text: str):
    masks_by_digit = _load_template_masks_by_digit(paths.DIGIT_TEMPLATE_DIR)
    if not masks_by_digit:
        return ()

    ordered_candidates = sorted(candidates, key=lambda item: item.x)
    expected_count = len(expected_text)
    best_combo = None
    best_key = None

    for indexes in _combinations(range(len(ordered_candidates)), expected_count):
        combo = tuple(ordered_candidates[index] for index in indexes)
        score_sum = 0.0
        score_min = 1.0
        missing_template = False

        for component, expected_digit in zip(combo, expected_text):
            score = _score_component_against_digit(component, expected_digit, masks_by_digit)
            if score is None:
                missing_template = True
                break
            score_sum += score
            score_min = min(score_min, score)

        if missing_template:
            continue

        # Tie-breaker: prefer wider left-to-right spans. Real digits usually
        # occupy the outer positions; extra star/badge fragments often appear
        # between them.
        span = (combo[-1].x - combo[0].x) if len(combo) > 1 else 0
        key = (score_sum, score_min, span)
        if best_key is None or key > best_key:
            best_key = key
            best_combo = combo

    return tuple(best_combo or ())


def _load_template_masks_by_digit(template_dir: Path) -> dict[str, list]:
    result: dict[str, list] = {}
    if not template_dir.exists():
        return result

    for path in sorted(template_dir.glob("digit_*.png")):
        parts = path.name.split("_")
        if len(parts) < 2 or not parts[1].isdigit():
            continue
        digit = parts[1]
        try:
            with Image.open(path) as image:
                mask = _mask_from_template_image(image)
        except Exception:
            continue
        if mask.any():
            result.setdefault(digit, []).append(mask)
    return result


def _score_component_against_digit(component, expected_digit: str, masks_by_digit: dict[str, list]) -> float | None:
    templates = masks_by_digit.get(expected_digit)
    if not templates:
        return None

    normalized_image = normalize_digit_mask(component.mask)
    component_mask = _mask_from_template_image(normalized_image)
    best = 0.0
    for template_mask in templates:
        if template_mask.shape != component_mask.shape:
            template_mask = _resize_mask(template_mask, component_mask.shape[1], component_mask.shape[0])
        best = max(best, _mask_score(component_mask, template_mask))
    return best


def _mask_from_template_image(image: Image.Image):
    import numpy as np

    gray = np.asarray(ImageOps.grayscale(image), dtype=np.uint8)
    return gray > 60


def _resize_mask(mask, width: int, height: int):
    import numpy as np

    image = Image.fromarray((mask.astype(np.uint8) * 255), mode="L")
    resample_filter = getattr(Image, "Resampling", Image).NEAREST
    resized = image.resize((width, height), resample_filter)
    return np.asarray(resized, dtype=np.uint8) > 60


def _mask_score(patch, template) -> float:
    import numpy as np

    patch_bool = patch.astype(bool)
    template_bool = template.astype(bool)
    intersection = np.logical_and(patch_bool, template_bool).sum()
    union = np.logical_or(patch_bool, template_bool).sum()
    if union == 0:
        return 0.0
    return float(intersection / union)


def _combinations(values, size: int):
    values = list(values)
    if size == 0:
        yield ()
        return
    if size > len(values):
        return
    if size == 1:
        for value in values:
            yield (value,)
        return
    for i, value in enumerate(values[: len(values) - size + 1]):
        for rest in _combinations(values[i + 1 :], size - 1):
            yield (value, *rest)

def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Automatically add digit templates from the current level_area crop. "
            "Use this when you know the visible level, for example ready level 9. "
            "It auto-isolates the digit shape so manual crops are not too tight or too loose."
        )
    )
    parser.add_argument("level", help="Correct visible level number. Example: 9")
    parser.add_argument(
        "--state",
        choices=("ready", "not_ready", "unknown"),
        default="ready",
        help="State label used only in output filenames. Default: ready.",
    )
    parser.add_argument(
        "--from-file",
        type=Path,
        default=None,
        help="Use an existing level-area crop instead of capturing from ADB.",
    )
    parser.add_argument(
        "--source-label",
        default=None,
        help="Override the text included in the output filename.",
    )
    parser.add_argument(
        "--allow-count-mismatch",
        action="store_true",
        help="Save whatever digit components were found even if the count differs from the expected level length.",
    )
    args = parser.parse_args()

    level_text = str(args.level).strip()
    if not level_text.isdigit():
        print("ok: False")
        print(f"message: level must contain only digits, got {args.level!r}.")
        return 2

    try:
        level_crop = _load_level_crop(args.from_file) if args.from_file else _capture_level_crop()
    except Exception as exc:
        print("ok: False")
        print(f"message: Could not prepare level crop: {exc}")
        return 1

    try:
        extraction = _extract_digits_for_training(level_crop, level_text)
    except Exception as exc:
        print("ok: False")
        print(f"message: Could not extract digits: {exc}")
        return 1

    preview_path = paths.DEBUG_CROP_DIR / f"auto_digit_detection_level_{level_text}_{args.state}.png"
    _save_detection_preview(level_crop, extraction, preview_path)

    expected_count = len(level_text)
    if extraction.found_count != expected_count and not args.allow_count_mismatch:
        print("ok: False")
        print(extraction.message)
        print(f"expected_level: {level_text}")
        print(f"expected_count: {expected_count}")
        print(f"found_count: {extraction.found_count}")
        print(f"preview_path: {preview_path}")
        print("message: Auto extraction count mismatch. Inspect preview or rerun with --allow-count-mismatch only if intentional.")
        return 1

    service = DigitTrainingService(
        template_dir=paths.DIGIT_TEMPLATE_DIR,
        preview_dir=paths.DEBUG_CROP_DIR,
    )

    saved = []
    source_label = args.source_label or f"{args.state}_level_{level_text}_auto"
    for expected_digit, extracted_digit in zip(level_text, extraction.digits):
        try:
            saved.append(
                service.save_extracted_digit_template(
                    expected_digit,
                    extracted_digit,
                    source_label=source_label,
                )
            )
        except Exception as exc:
            print("ok: False")
            print(f"message: Could not save digit {expected_digit}: {exc}")
            print(f"preview_path: {preview_path}")
            return 1

    print("ok: True")
    print(extraction.message)
    print(f"expected_level: {level_text}")
    print(f"state: {args.state}")
    print(f"level_crop_path: {paths.LATEST_LEVEL_CROP_PATH if not args.from_file else args.from_file}")
    print(f"detection_preview_path: {preview_path}")
    for index, item in enumerate(saved, start=1):
        print(f"digit_{index}: {item.digit}")
        print(f"template_{index}_path: {item.template_path}")
        print(f"preview_{index}_path: {item.preview_path}")
        print(f"template_{index}_size: {item.width}x{item.height}")
    print("message: Saved normalized digit templates. Run scan_once again to verify recognition.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
