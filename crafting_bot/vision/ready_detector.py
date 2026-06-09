from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from crafting_bot.domain.models import ReadyMatch, ReadyState
from crafting_bot.vision.image_tools import normalized_mae

_READY_NAME_PATTERN = re.compile(r"(?P<level>\d+).*_(?P<state>yes|no)_", re.IGNORECASE)


@dataclass(frozen=True)
class ReadyTemplate:
    state: ReadyState
    path: Path
    level: int | None


class ReadyDetector:
    """Classifies the level crop as ready/starred or not ready."""

    def __init__(self, template_dir: Path, max_good_score: float = 0.22) -> None:
        self.template_dir = template_dir
        self.max_good_score = max_good_score
        self._templates: list[ReadyTemplate] = []

    def load(self) -> None:
        if not self.template_dir.exists():
            raise FileNotFoundError(f"Missing ready template directory: {self.template_dir}")

        templates: list[ReadyTemplate] = []
        index_path = self.template_dir / "index.json"

        if index_path.exists():
            templates.extend(self._load_from_index(index_path))

        if not templates:
            templates.extend(self._load_from_filenames())

        if not templates:
            raise ValueError(f"No ready templates found in {self.template_dir}")

        self._templates = templates

    def classify(
        self,
        crop: Image.Image,
        level_hint: int | None = None,
        *,
        require_level_templates: bool = False,
    ) -> ReadyMatch:
        if not self._templates:
            self.load()

        candidates = self._templates
        if level_hint is not None:
            level_candidates = [item for item in candidates if item.level == level_hint]
            if level_candidates:
                candidates = level_candidates
            elif require_level_templates:
                return ReadyMatch(
                    state="unknown",
                    score=1.0,
                    template_path=None,
                    level_hint=level_hint,
                )

        best_template: ReadyTemplate | None = None
        best_score = float("inf")

        for template in candidates:
            with Image.open(template.path) as template_image:
                score = normalized_mae(crop, template_image.convert("RGB"))

            if score < best_score:
                best_score = score
                best_template = template

        if best_template is None or best_score > self.max_good_score:
            return ReadyMatch(
                state="unknown",
                score=best_score if best_score != float("inf") else 1.0,
                template_path=best_template.path if best_template else None,
                level_hint=level_hint,
            )

        return ReadyMatch(
            state=best_template.state,
            score=best_score,
            template_path=best_template.path,
            level_hint=level_hint,
        )

    def _load_from_index(self, index_path: Path) -> list[ReadyTemplate]:
        with index_path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)

        templates: list[ReadyTemplate] = []

        if isinstance(raw, dict):
            items = raw.get("templates", raw.get("entries", raw))
        else:
            items = raw

        if isinstance(items, dict):
            iterable = items.values()
        elif isinstance(items, list):
            iterable = items
        else:
            return []

        for item in iterable:
            if not isinstance(item, dict):
                continue

            filename = item.get("filename") or item.get("file") or item.get("path") or item.get("template_path")
            state = item.get("ready") or item.get("state")
            level = item.get("level")

            if not filename or state not in {"yes", "no"}:
                continue

            path = self.template_dir / Path(str(filename)).name
            if path.exists():
                templates.append(
                    ReadyTemplate(
                        state=state,
                        path=path,
                        level=int(level) if level is not None else None,
                    )
                )

        return templates

    def _load_from_filenames(self) -> list[ReadyTemplate]:
        templates: list[ReadyTemplate] = []

        for path in sorted(self.template_dir.glob("*.png")):
            match = _READY_NAME_PATTERN.search(path.name)
            if not match:
                continue

            templates.append(
                ReadyTemplate(
                    state=match.group("state").lower(),
                    path=path,
                    level=int(match.group("level")),
                )
            )

        return templates
