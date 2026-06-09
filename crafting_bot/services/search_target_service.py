from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from crafting_bot.domain.target_catalog import SearchTargetDefinition
from crafting_bot.infra.calibration_store import CalibrationStore
from crafting_bot.vision.template_search import TemplateSearcher, TemplateSearchResult, save_match_preview


@dataclass(frozen=True)
class SearchTargetRunResult:
    definition: SearchTargetDefinition
    result: TemplateSearchResult
    template_path: Path
    preview_path: Path | None


class SearchTargetService:
    """Runs visual search targets without knowing anything about bot workflow."""

    def __init__(
        self,
        calibration: CalibrationStore,
        crop_dir: Path,
        preview_dir: Path,
        searcher: TemplateSearcher | None = None,
    ) -> None:
        self.calibration = calibration
        self.crop_dir = crop_dir
        self.preview_dir = preview_dir
        self.searcher = searcher or TemplateSearcher()

    def run(self, definition: SearchTargetDefinition, screenshot: Image.Image, save_preview: bool = True) -> SearchTargetRunResult:
        search_area = self.calibration.get_area(definition.search_area_name)
        template_path = self.crop_dir / f"{definition.template_area_name}.png"
        if not template_path.exists():
            raise FileNotFoundError(
                f"Missing template crop: {template_path}. Calibrate or capture {definition.template_area_name} first."
            )

        template = Image.open(template_path).convert("RGB")
        result = self.searcher.find(
            screenshot=screenshot,
            search_area=search_area,
            template=template,
            search_axis=definition.search_axis,
            x_tolerance=definition.x_tolerance,
        )

        preview_path: Path | None = None
        if save_preview:
            preview_path = self.preview_dir / f"{definition.name}_match_preview.png"
            save_match_preview(screenshot, result, preview_path, search_area=search_area)

        return SearchTargetRunResult(
            definition=definition,
            result=result,
            template_path=template_path,
            preview_path=preview_path,
        )
