from __future__ import annotations

from pathlib import Path

from PIL import Image

from crafting_bot.domain.models import ReadyMatch
from crafting_bot.vision.ready_state_confirmation import (
    ReadyStateConfirmer,
    ReadyTemplateMatcher,
    ReadyTemplateRepository,
)


class ReadyDetector:
    """Facade for cached ready/not-ready template confirmation.

    Template files are loaded once into ReadyTemplateRepository and reused for
    all scans. Use reload() only after training/cleanup changes the template
    files on disk.
    """

    def __init__(self, template_dir: Path, max_good_score: float = 0.22) -> None:
        self.template_dir = template_dir
        self.max_good_score = max_good_score
        self.repository = ReadyTemplateRepository(template_dir)
        self.matcher = ReadyTemplateMatcher()
        self.confirmer = ReadyStateConfirmer(
            repository=self.repository,
            matcher=self.matcher,
            max_good_score=max_good_score,
        )
        self._last_diagnostics: str | None = None

    def load(self) -> None:
        self.repository.load()

    def reload(self) -> None:
        self.repository.reload()

    def classify(
        self,
        crop: Image.Image,
        level_hint: int | None = None,
        *,
        require_level_templates: bool = False,
    ) -> ReadyMatch:
        decision = self.confirmer.confirm(
            crop,
            level_hint=level_hint,
            require_level_templates=require_level_templates,
        )
        self._last_diagnostics = decision.diagnostics()

        return ReadyMatch(
            state=decision.state,
            score=decision.score,
            template_path=decision.template_path,
            level_hint=level_hint,
        )

    def diagnostics_for_last_match(self) -> str | None:
        return self._last_diagnostics
