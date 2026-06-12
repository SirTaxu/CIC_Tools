from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image

from crafting_bot import paths
from crafting_bot.services.template_index_service import TemplateIndexService


@dataclass(frozen=True)
class ReadyStateTrainingResult:
    level: int
    state: str
    template_path: Path
    duplicate: bool
    index_action: str
    message: str


class ReadyStateTrainingService:
    """Saves explicit ready/not-ready level templates.

    This service does not capture screenshots and does not decide whether the
    current screen is truly ready. The CLI or GUI must provide the crop after
    the user intentionally requests training.
    """

    def __init__(
        self,
        *,
        template_dir: Path = paths.READY_TEMPLATE_DIR,
        index_service: TemplateIndexService | None = None,
    ) -> None:
        self.template_dir = template_dir
        self.index_service = index_service or TemplateIndexService()

    def save_ready_template(
        self,
        *,
        level: int,
        state: str,
        crop: Image.Image,
        source_label: str = "manual",
    ) -> ReadyStateTrainingResult:
        if level < 1:
            raise ValueError("Cannot train ready state for level 0. Level 0 does not exist.")
        if state not in {"yes", "no"}:
            raise ValueError("Ready state must be 'yes' or 'no'.")

        self.template_dir.mkdir(parents=True, exist_ok=True)

        image = crop.convert("RGB")
        digest = hashlib.sha256(image.tobytes()).hexdigest()[:10]
        safe_source = safe_label(source_label)

        duplicate = self._find_duplicate(level, state, safe_source, digest)
        if duplicate is not None:
            action = self.index_service.ensure_ready_entry(
                template_path=duplicate,
                level=level,
                state=state,
                source=safe_source,
                apply=True,
            )
            return ReadyStateTrainingResult(
                level=level,
                state=state,
                template_path=duplicate,
                duplicate=True,
                index_action=action.action,
                message=(
                    f"Skipped duplicate ready template for level {level} state={state}: "
                    f"{duplicate.name}. Index action={action.action}."
                ),
            )

        sequence = self._next_sequence(level, state, safe_source)
        filename = f"{level:03d}_{state}_{safe_source}_{sequence:03d}_{digest}.png"
        template_path = self.template_dir / filename
        image.save(template_path)

        action = self.index_service.ensure_ready_entry(
            template_path=template_path,
            level=level,
            state=state,
            source=safe_source,
            apply=True,
        )

        return ReadyStateTrainingResult(
            level=level,
            state=state,
            template_path=template_path,
            duplicate=False,
            index_action=action.action,
            message=(
                f"Saved ready template for level {level} state={state}: {template_path}. "
                f"Index action={action.action}."
            ),
        )

    def _find_duplicate(self, level: int, state: str, source: str, digest: str) -> Path | None:
        pattern = f"{level:03d}_{state}_{source}_*_{digest}.png"
        matches = sorted(self.template_dir.glob(pattern))
        return matches[0] if matches else None

    def _next_sequence(self, level: int, state: str, source: str) -> int:
        pattern = f"{level:03d}_{state}_{source}_*.png"
        return len(list(self.template_dir.glob(pattern))) + 1


def safe_label(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value.strip())
    return cleaned.strip("_") or "manual"
