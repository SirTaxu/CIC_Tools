from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from crafting_bot.domain.models import DigitMatch
from crafting_bot.vision.digit_extractor import extract_digit_components, normalize_digit_mask

_DIGIT_NAME_PATTERN = re.compile(r"digit_(?P<digit>\d)", re.IGNORECASE)


@dataclass(frozen=True)
class DigitTemplate:
    digit: str
    path: Path
    mask: np.ndarray
    width: int
    height: int


class DigitReader:
    """
    Reads the visible level number by isolating digit components first.

    Earlier versions slid every template over the whole level badge. That was
    too easy to confuse on ready/starred single-digit levels, because a template
    could match a badge/star fragment better than the actual digit. This reader
    first extracts likely digit-shaped components, normalizes each component to
    the same 32x48 black/white format used by training, and only then compares
    the component against digit templates.
    """

    def __init__(
        self,
        template_dir: Path,
        min_score: float = 0.50,
        min_margin: float = 0.07,
        max_supported_level: int = 999,
    ) -> None:
        self.template_dir = template_dir
        self.min_score = min_score
        self.min_margin = min_margin
        self.max_supported_level = max_supported_level
        self._templates: list[DigitTemplate] = []
        self._last_diagnostics = "Digit reader has not run yet."

    def load(self) -> None:
        if not self.template_dir.exists():
            raise FileNotFoundError(f"Missing digit template directory: {self.template_dir}")

        templates: list[DigitTemplate] = []
        for path in self._template_paths():
            match = _DIGIT_NAME_PATTERN.search(path.name)
            if not match:
                continue

            with Image.open(path) as image:
                mask = self._mask_from_template(image)
                if mask.sum() < 8:
                    continue

                templates.append(
                    DigitTemplate(
                        digit=match.group("digit"),
                        path=path,
                        mask=mask,
                        width=image.width,
                        height=image.height,
                    )
                )

        if not templates:
            raise ValueError(f"No digit templates found in {self.template_dir}")

        self._templates = templates


    def _template_paths(self) -> list[Path]:
        """Return active digit template paths, using index.json when present.

        The index is optional and forward-compatible with a future Template
        Manager. Enabled entries are loaded first, then any PNG not yet listed
        in the index is added by filename so manual file additions still work.
        """
        indexed_paths: list[Path] = []
        indexed_names: set[str] = set()
        index_path = self.template_dir / "index.json"

        if index_path.exists():
            try:
                with index_path.open("r", encoding="utf-8") as handle:
                    raw = json.load(handle)
            except Exception:
                raw = None

            items: object
            if isinstance(raw, dict):
                items = raw.get("templates", raw.get("entries", raw))
            else:
                items = raw

            if isinstance(items, dict):
                iterable = items.values()
            elif isinstance(items, list):
                iterable = items
            else:
                iterable = []

            for item in iterable:
                if not isinstance(item, dict):
                    continue
                if not item.get("enabled", True):
                    continue
                filename = item.get("filename") or item.get("file") or item.get("path") or item.get("template_path")
                if not filename:
                    continue
                path = self.template_dir / Path(str(filename)).name
                if path.exists() and _DIGIT_NAME_PATTERN.search(path.name):
                    indexed_paths.append(path)
                    indexed_names.add(path.name)

        filename_paths = [
            path
            for path in sorted(self.template_dir.glob("digit_*.png"))
            if path.name not in indexed_names
        ]

        unique: dict[Path, Path] = {}
        for path in [*indexed_paths, *filename_paths]:
            unique.setdefault(path.resolve(), path)
        return sorted(unique.values(), key=lambda item: item.name)

    def read(self, crop: Image.Image, allowed_digits: set[str] | None = None) -> tuple[str, list[DigitMatch]]:
        if not self._templates:
            self.load()

        component_matches = self._read_by_components(crop, allowed_digits=allowed_digits)
        if component_matches:
            accepted_matches, ignored_matches = self._filter_component_matches(component_matches)
            self._last_diagnostics = self._format_diagnostics(
                component_matches,
                mode="component",
                accepted=accepted_matches,
                ignored=ignored_matches,
            )

            if not accepted_matches:
                return "unknown", component_matches

            # If there is only one accepted component but other uncertain
            # components were found, stop instead of accidentally reading a
            # two-digit level as a single-digit level. The exception is a true
            # single-component crop, which is how levels 1-9 normally appear.
            if len(accepted_matches) == 1 and len(component_matches) > 1:
                return "unknown", component_matches

            ordered_accepted = sorted(accepted_matches, key=lambda item: item.x)
            ordered_accepted = self._reduce_unsupported_level_read(ordered_accepted)
            if not ordered_accepted:
                return "unknown", component_matches

            text = "".join(match.digit for match in ordered_accepted)
            return text, ordered_accepted

        # Fallback only when no usable digit component was isolated. This keeps
        # older data usable but prevents it from overriding clean component reads.
        crop_mask = self._mask_from_crop(crop)
        raw_matches = self._find_matches_legacy(crop_mask, allowed_digits=allowed_digits)
        matches = self._deduplicate_matches(raw_matches)
        self._last_diagnostics = self._format_diagnostics(matches, mode="legacy-fallback")

        if not matches or any(match.score < self.min_score for match in matches):
            return "unknown", matches

        ordered_matches = sorted(matches, key=lambda item: item.x)
        ordered_matches = self._reduce_unsupported_level_read(ordered_matches)
        if not ordered_matches:
            return "unknown", matches

        text = "".join(match.digit for match in ordered_matches)
        return text, ordered_matches

    def diagnostics_for_last_read(self) -> str:
        return self._last_diagnostics

    def _read_by_components(self, crop: Image.Image, allowed_digits: set[str] | None = None) -> list[DigitMatch]:
        components = extract_digit_components(crop, max_digits=3)
        matches: list[DigitMatch] = []

        for component in components:
            normalized = normalize_digit_mask(component.mask)
            normalized_mask = self._mask_from_template(normalized)
            ranked = self._rank_templates(normalized_mask, allowed_digits=allowed_digits)
            if not ranked:
                continue

            best = ranked[0]
            second = ranked[1] if len(ranked) > 1 else None
            second_digit = second.digit if second else None
            second_score = second.score if second else None
            ambiguous = False
            if second is not None and best.digit != second.digit:
                ambiguous = (best.score - second.score) < self.min_margin

            matches.append(
                DigitMatch(
                    digit=best.digit,
                    score=best.score,
                    x=component.x,
                    y=component.y,
                    template_path=best.template_path,
                    second_digit=second_digit,
                    second_score=second_score,
                    ambiguous=ambiguous,
                    source="component",
                )
            )

        return sorted(matches, key=lambda item: item.x)


    def _filter_component_matches(self, matches: list[DigitMatch]) -> tuple[list[DigitMatch], list[DigitMatch]]:
        """Return confident digit components and ignore obvious badge/star noise.

        Ready level 10 exposed a common case: the extractor found the real
        digits 1 and 0, but also isolated a small noisy component from the
        badge/star between them. The old reader rejected the whole level because
        one component was ambiguous. The safer behavior is to accept strong,
        non-ambiguous components and ignore weak/ambiguous extras only when at
        least two reliable digits remain.
        """

        accepted: list[DigitMatch] = []
        ignored: list[DigitMatch] = []

        for match in sorted(matches, key=lambda item: item.x):
            if match.score >= self.min_score and not match.ambiguous:
                accepted.append(match)
            else:
                ignored.append(match)

        if not accepted:
            return [], ignored

        if not ignored:
            return accepted, []

        # Keep the old safety behavior for likely single-digit reads: if there
        # is one reliable component plus extra uncertain components, do not
        # guess. For multi-digit reads, weak/ambiguous extras can be ignored.
        if len(accepted) >= 2:
            return accepted, ignored

        return [], matches


    def _reduce_unsupported_level_read(self, matches: list[DigitMatch]) -> list[DigitMatch]:
        """Drop likely extra noise components when the assembled level is impossible.

        Ready level 13 exposed a bad-training/noise case where the components
        were read as 1, 1, 3. The project currently has reliable ready templates
        only up to level 100, and the bot should not click for unsupported level
        numbers. If the full read is above max_supported_level, try removing one
        or more components and keep the strongest plausible subset. Prefer wider
        left-to-right spans on ties, because real level digits usually occupy the
        outer digit positions while badge/star noise appears between them.
        """

        ordered = sorted(matches, key=lambda item: item.x)
        text = "".join(match.digit for match in ordered)
        if self._is_supported_level_text(text):
            return ordered

        best_subset: tuple[DigitMatch, ...] | None = None
        best_key: tuple[int, float, int, float] | None = None

        # Prefer the longest supported text first. This keeps level 100 intact
        # and only shortens reads that are impossible with the current level cap.
        for subset_size in range(len(ordered) - 1, 0, -1):
            for indexes in self._combinations(range(len(ordered)), subset_size):
                subset = tuple(ordered[index] for index in indexes)
                subset_text = "".join(match.digit for match in subset)
                if not self._is_supported_level_text(subset_text):
                    continue

                score_sum = sum(match.score for match in subset)
                span = (subset[-1].x - subset[0].x) if len(subset) > 1 else 0
                score_min = min(match.score for match in subset)
                key = (subset_size, score_sum, span, score_min)
                if best_key is None or key > best_key:
                    best_key = key
                    best_subset = subset

            if best_subset is not None:
                break

        return list(best_subset or [])

    def _is_supported_level_text(self, text: str) -> bool:
        if not text or not text.isdigit():
            return False
        value = int(text)
        return 0 <= value <= self.max_supported_level

    @staticmethod
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
            for rest in DigitReader._combinations(values[i + 1 :], size - 1):
                yield (value, *rest)

    def _rank_templates(self, component_mask: np.ndarray, allowed_digits: set[str] | None = None) -> list[DigitMatch]:
        best_by_digit: dict[str, DigitMatch] = {}

        for template in self._templates:
            if allowed_digits is not None and template.digit not in allowed_digits:
                continue
            template_mask = template.mask
            if template_mask.shape != component_mask.shape:
                template_mask = self._resize_mask(template_mask, component_mask.shape[1], component_mask.shape[0])

            score = self._mask_score(component_mask, template_mask)
            existing = best_by_digit.get(template.digit)
            if existing is None or score > existing.score:
                best_by_digit[template.digit] = DigitMatch(
                    digit=template.digit,
                    score=float(score),
                    x=0,
                    y=0,
                    template_path=template.path,
                    source="component-candidate",
                )

        return sorted(best_by_digit.values(), key=lambda item: item.score, reverse=True)

    def _find_matches_legacy(self, crop_mask: np.ndarray, allowed_digits: set[str] | None = None) -> list[DigitMatch]:
        matches: list[DigitMatch] = []
        crop_h, crop_w = crop_mask.shape

        for template in self._templates:
            if allowed_digits is not None and template.digit not in allowed_digits:
                continue
            if template.height > crop_h or template.width > crop_w:
                continue

            best_score = -1.0
            best_xy = (0, 0)

            for y in range(0, crop_h - template.height + 1):
                for x in range(0, crop_w - template.width + 1):
                    patch = crop_mask[y:y + template.height, x:x + template.width]
                    score = self._mask_score(patch, template.mask)
                    if score > best_score:
                        best_score = score
                        best_xy = (x, y)

            if best_score >= self.min_score:
                matches.append(
                    DigitMatch(
                        digit=template.digit,
                        score=float(best_score),
                        x=best_xy[0],
                        y=best_xy[1],
                        template_path=template.path,
                        source="legacy-fallback",
                    )
                )

        return matches

    def _deduplicate_matches(self, matches: list[DigitMatch]) -> list[DigitMatch]:
        if not matches:
            return []

        ordered = sorted(matches, key=lambda item: item.score, reverse=True)
        kept: list[DigitMatch] = []

        for candidate in ordered:
            if any(abs(candidate.x - existing.x) < 14 for existing in kept):
                continue
            kept.append(candidate)
            if len(kept) >= 3:
                break

        return sorted(kept, key=lambda item: item.x)

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
    def _mask_from_template(image: Image.Image) -> np.ndarray:
        gray = np.asarray(ImageOps.grayscale(image), dtype=np.uint8)
        return gray > 60

    @staticmethod
    def _mask_from_crop(image: Image.Image) -> np.ndarray:
        rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
        r = rgb[:, :, 0].astype(np.int16)
        g = rgb[:, :, 1].astype(np.int16)
        b = rgb[:, :, 2].astype(np.int16)

        bright = (r > 135) & (g > 120) & (b > 80)
        not_blue_bg = ~((b > r + 25) & (b > g + 20))
        return bright & not_blue_bg

    @staticmethod
    def _resize_mask(mask: np.ndarray, width: int, height: int) -> np.ndarray:
        image = Image.fromarray((mask.astype(np.uint8) * 255), mode="L")
        resample_filter = getattr(Image, "Resampling", Image).NEAREST
        resized = image.resize((width, height), resample_filter)
        return np.asarray(resized, dtype=np.uint8) > 60

    @staticmethod
    def _format_diagnostics(
        matches: list[DigitMatch],
        *,
        mode: str,
        accepted: list[DigitMatch] | None = None,
        ignored: list[DigitMatch] | None = None,
    ) -> str:
        if not matches:
            return f"digit_reader={mode}; no usable digit components/matches."

        accepted_ids = {id(match) for match in accepted or []}
        ignored_ids = {id(match) for match in ignored or []}

        parts: list[str] = [f"digit_reader={mode}"]
        for idx, match in enumerate(sorted(matches, key=lambda item: item.x), start=1):
            detail = f"component{idx}: best={match.digit} score={match.score:.3f}"
            if match.second_digit is not None and match.second_score is not None:
                detail += f", second={match.second_digit} score={match.second_score:.3f}"
            if match.ambiguous:
                detail += ", ambiguous=yes"
            if id(match) in accepted_ids:
                detail += ", accepted=yes"
            elif id(match) in ignored_ids:
                detail += ", ignored=yes"
            detail += f", template={match.template_path.name}"
            parts.append(detail)
        return "; ".join(parts) + "."
