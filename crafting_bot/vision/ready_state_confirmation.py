from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

from PIL import Image

from crafting_bot.domain.models import ReadyState
from crafting_bot.vision.image_tools import normalized_mae

_READY_NAME_PATTERNS = (
    re.compile(r"(?P<level>\d+).*_(?P<state>yes|no)_", re.IGNORECASE),
    re.compile(r"(?P<state>yes|no)_(?:manual|auto|loop_auto)?_level_(?P<level>\d+)", re.IGNORECASE),
)

ReadyTemplateSource = Literal["manual", "auto", "loop_auto", "index", "filename", "unknown"]


@dataclass(frozen=True)
class ReadyTemplateRecord:
    """Ready/not-ready template metadata plus cached image data.

    The image is loaded once by ReadyTemplateRepository and reused by all scans.
    This keeps per-scan work limited to comparing the current crop against
    already cached templates.
    """

    state: ReadyState
    path: Path
    image: Image.Image
    level: int | None
    source: str = "unknown"


@dataclass(frozen=True)
class ReadyTemplateScore:
    """One template comparison result."""

    state: ReadyState
    score: float
    template_path: Path | None
    level: int | None
    source: str = "unknown"


@dataclass(frozen=True)
class ReadyStateDecision:
    """Final ready/not-ready decision with diagnostic details."""

    state: ReadyState
    score: float
    template_path: Path | None
    level_hint: int | None
    reason: str
    best_yes: ReadyTemplateScore | None = None
    best_no: ReadyTemplateScore | None = None
    scope: str = "none"

    def diagnostics(self) -> str:
        return (
            f"ready_decision={self.reason}; "
            f"scope={self.scope}; "
            f"level_hint={self.level_hint}; "
            f"best_yes={self._format_score(self.best_yes)}; "
            f"best_no={self._format_score(self.best_no)}"
        )

    @staticmethod
    def _format_score(score: ReadyTemplateScore | None) -> str:
        if score is None:
            return "none"
        template = score.template_path.name if score.template_path else "none"
        return f"{score.score:.4f}:{template}"


class ReadyTemplateRepository:
    """Loads and caches ready/not-ready templates.

    Disk IO happens only during load/reload. Scans use the cached records and
    cached images. The repository is intentionally separate from matching and
    decision logic so new template sources can be added without changing the
    scanner.
    """

    def __init__(self, template_dir: Path) -> None:
        self.template_dir = template_dir
        self._templates: list[ReadyTemplateRecord] = []
        self._loaded = False

    @property
    def templates(self) -> list[ReadyTemplateRecord]:
        if not self._loaded:
            self.load()
        return self._templates

    def load(self) -> None:
        if not self.template_dir.exists():
            raise FileNotFoundError(f"Missing ready template directory: {self.template_dir}")

        records: list[_ReadyTemplateCandidate] = []
        index_path = self.template_dir / "index.json"

        if index_path.exists():
            records.extend(self._load_candidates_from_index(index_path))
        records.extend(self._load_candidates_from_filenames())

        records = self._deduplicate_candidates(records)
        if not records:
            raise ValueError(f"No ready templates found in {self.template_dir}")

        loaded: list[ReadyTemplateRecord] = []
        for record in records:
            try:
                with Image.open(record.path) as image:
                    cached = image.convert("RGB").copy()
            except Exception:
                continue

            loaded.append(
                ReadyTemplateRecord(
                    state=record.state,
                    path=record.path,
                    image=cached,
                    level=record.level,
                    source=record.source,
                )
            )

        if not loaded:
            raise ValueError(f"No readable ready templates found in {self.template_dir}")

        self._templates = sorted(
            loaded,
            key=lambda item: (
                item.level is None,
                item.level if item.level is not None else 10_000,
                item.state,
                self._source_priority(item.source),
                item.path.name,
            ),
        )
        self._loaded = True

    def reload(self) -> None:
        self._loaded = False
        self._templates = []
        self.load()

    def get_for_level(self, level: int) -> list[ReadyTemplateRecord]:
        level = int(level)
        return [item for item in self.templates if item.level == level]

    def get_all(self) -> list[ReadyTemplateRecord]:
        return list(self.templates)

    def _load_candidates_from_index(self, index_path: Path) -> list["_ReadyTemplateCandidate"]:
        with index_path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)

        if isinstance(raw, dict):
            items = raw.get("templates", raw.get("entries", raw))
        else:
            items = raw

        if isinstance(items, dict):
            iterable: Iterable[object] = items.values()
        elif isinstance(items, list):
            iterable = items
        else:
            return []

        candidates: list[_ReadyTemplateCandidate] = []
        for item in iterable:
            if not isinstance(item, dict):
                continue

            filename = item.get("filename") or item.get("file") or item.get("path") or item.get("template_path")
            state = normalize_ready_state(item.get("ready") or item.get("state"))
            level = item.get("level")
            enabled = item.get("enabled", True)
            source = str(item.get("source") or "index")

            if not enabled or not filename or state not in {"yes", "no"}:
                continue

            path = self.template_dir / Path(str(filename)).name
            if path.exists():
                candidates.append(
                    _ReadyTemplateCandidate(
                        state=state,
                        path=path,
                        level=int(level) if level is not None else None,
                        source=source,
                    )
                )

        return candidates

    def _load_candidates_from_filenames(self) -> list["_ReadyTemplateCandidate"]:
        candidates: list[_ReadyTemplateCandidate] = []

        for path in sorted(self.template_dir.glob("*.png")):
            match = match_ready_filename(path.name)
            if not match:
                continue

            candidates.append(
                _ReadyTemplateCandidate(
                    state=match.group("state").lower(),  # type: ignore[arg-type]
                    path=path,
                    level=int(match.group("level")),
                    source=infer_source_from_filename(path.name),
                )
            )

        return candidates

    @staticmethod
    def _deduplicate_candidates(candidates: list["_ReadyTemplateCandidate"]) -> list["_ReadyTemplateCandidate"]:
        unique: dict[Path, _ReadyTemplateCandidate] = {}
        for candidate in candidates:
            key = candidate.path.resolve()
            existing = unique.get(key)
            if existing is None:
                unique[key] = candidate
                continue

            # Prefer richer metadata and higher-trust sources if the same file
            # appears in both index.json and filename scanning.
            if ReadyTemplateRepository._source_priority(candidate.source) < ReadyTemplateRepository._source_priority(existing.source):
                unique[key] = candidate
            elif existing.level is None and candidate.level is not None:
                unique[key] = candidate

        return list(unique.values())

    @staticmethod
    def _source_priority(source: str) -> int:
        text = source.lower()
        if text == "manual":
            return 0
        if text in {"curated", "boot"}:
            return 1
        if text == "loop_auto":
            return 2
        if text == "auto":
            return 3
        if text == "index":
            return 4
        if text == "filename":
            return 5
        return 6


class ReadyTemplateMatcher:
    """Compares a level crop against cached ready templates."""

    def best_match(
        self,
        crop: Image.Image,
        templates: Iterable[ReadyTemplateRecord],
        *,
        state: ReadyState | None = None,
    ) -> ReadyTemplateScore | None:
        crop_rgb = crop.convert("RGB")
        best: ReadyTemplateScore | None = None

        for template in templates:
            if state is not None and template.state != state:
                continue

            score = normalized_mae(crop_rgb, template.image)
            if best is None or score < best.score:
                best = ReadyTemplateScore(
                    state=template.state,
                    score=score,
                    template_path=template.path,
                    level=template.level,
                    source=template.source,
                )

        return best


class ReadyStateConfirmer:
    """Decides ready/not-ready by comparing yes and no evidence.

    Lower scores are better. The confirmer prefers same-level templates and
    only falls back to broader templates when same-level templates are not
    available. The decision is intentionally conservative: if yes/no evidence
    is too close, it returns unknown instead of starting a rebuild early.
    """

    def __init__(
        self,
        *,
        repository: ReadyTemplateRepository,
        matcher: ReadyTemplateMatcher,
        max_good_score: float = 0.22,
        min_state_margin: float = 0.015,
        single_state_max_good_score: float = 0.12,
    ) -> None:
        self.repository = repository
        self.matcher = matcher
        self.max_good_score = max_good_score
        self.min_state_margin = min_state_margin
        self.single_state_max_good_score = single_state_max_good_score

    def confirm(
        self,
        crop: Image.Image,
        *,
        level_hint: int | None = None,
        require_level_templates: bool = False,
    ) -> ReadyStateDecision:
        templates: list[ReadyTemplateRecord]
        scope: str

        if level_hint is not None:
            level_templates = self.repository.get_for_level(level_hint)
            if level_templates:
                templates = level_templates
                scope = "level_specific"
            elif require_level_templates:
                return ReadyStateDecision(
                    state="unknown",
                    score=1.0,
                    template_path=None,
                    level_hint=level_hint,
                    reason="missing_required_level_templates",
                    scope="none",
                )
            else:
                templates = self.repository.get_all()
                scope = "global_fallback"
        else:
            templates = self.repository.get_all()
            scope = "global"

        best_yes = self.matcher.best_match(crop, templates, state="yes")
        best_no = self.matcher.best_match(crop, templates, state="no")

        return self._decide(
            level_hint=level_hint,
            scope=scope,
            best_yes=best_yes,
            best_no=best_no,
        )

    def _decide(
        self,
        *,
        level_hint: int | None,
        scope: str,
        best_yes: ReadyTemplateScore | None,
        best_no: ReadyTemplateScore | None,
    ) -> ReadyStateDecision:
        if best_yes is None and best_no is None:
            return ReadyStateDecision(
                state="unknown",
                score=1.0,
                template_path=None,
                level_hint=level_hint,
                reason="no_templates_available",
                best_yes=best_yes,
                best_no=best_no,
                scope=scope,
            )

        if best_yes is not None and best_no is not None:
            yes_good = best_yes.score <= self.max_good_score
            no_good = best_no.score <= self.max_good_score

            if yes_good and best_yes.score + self.min_state_margin <= best_no.score:
                return self._decision("yes", best_yes, level_hint, "yes_wins_margin", best_yes, best_no, scope)

            if no_good and best_no.score + self.min_state_margin <= best_yes.score:
                return self._decision("no", best_no, level_hint, "no_wins_margin", best_yes, best_no, scope)

            if yes_good and not no_good:
                return self._decision("yes", best_yes, level_hint, "yes_only_under_threshold", best_yes, best_no, scope)

            if no_good and not yes_good:
                return self._decision("no", best_no, level_hint, "no_only_under_threshold", best_yes, best_no, scope)

            best_score = min(best_yes.score, best_no.score)
            return ReadyStateDecision(
                state="unknown",
                score=best_score,
                template_path=(best_yes.template_path if best_yes.score <= best_no.score else best_no.template_path),
                level_hint=level_hint,
                reason="yes_no_too_close_or_above_threshold",
                best_yes=best_yes,
                best_no=best_no,
                scope=scope,
            )

        single = best_yes or best_no
        assert single is not None

        if single.score <= self.single_state_max_good_score:
            return self._decision(
                single.state,
                single,
                level_hint,
                f"{single.state}_single_state_strong_match",
                best_yes,
                best_no,
                scope,
            )

        return ReadyStateDecision(
            state="unknown",
            score=single.score,
            template_path=single.template_path,
            level_hint=level_hint,
            reason=f"{single.state}_single_state_not_strong_enough",
            best_yes=best_yes,
            best_no=best_no,
            scope=scope,
        )

    @staticmethod
    def _decision(
        state: ReadyState,
        score: ReadyTemplateScore,
        level_hint: int | None,
        reason: str,
        best_yes: ReadyTemplateScore | None,
        best_no: ReadyTemplateScore | None,
        scope: str,
    ) -> ReadyStateDecision:
        return ReadyStateDecision(
            state=state,
            score=score.score,
            template_path=score.template_path,
            level_hint=level_hint,
            reason=reason,
            best_yes=best_yes,
            best_no=best_no,
            scope=scope,
        )


@dataclass(frozen=True)
class _ReadyTemplateCandidate:
    state: ReadyState
    path: Path
    level: int | None
    source: str = "unknown"


def normalize_ready_state(value: object) -> ReadyState | None:
    text = str(value).strip().lower() if value is not None else ""
    if text in {"yes", "ready", "true", "1"}:
        return "yes"
    if text in {"no", "not_ready", "not-ready", "false", "0"}:
        return "no"
    return None


def infer_source_from_filename(filename: str) -> str:
    text = filename.lower()
    if "_manual_" in text:
        return "manual"
    if "_loop_auto_" in text:
        return "loop_auto"
    if "_auto_" in text:
        return "auto"
    return "filename"


def match_ready_filename(filename: str) -> re.Match[str] | None:
    for pattern in _READY_NAME_PATTERNS:
        match = pattern.search(filename)
        if match:
            return match
    return None
