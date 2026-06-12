from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from PIL import Image

from crafting_bot import paths
from crafting_bot.domain.template_health import TemplateKind, TemplateRecord

_DIGIT_FILENAME_PATTERN = re.compile(
    r"digit_(?P<digit>\d)(?:_(?P<state>ready|not_ready|yes|no))?(?:_level_(?P<level>\d+))?",
    re.IGNORECASE,
)
_READY_FILENAME_PATTERNS = (
    re.compile(r"(?P<level>\d+).*_(?P<state>yes|no)_", re.IGNORECASE),
    re.compile(r"(?P<state>yes|no)_(?:manual|auto|loop_auto)?_level_(?P<level>\d+)", re.IGNORECASE),
)


@dataclass(frozen=True)
class _IndexEntry:
    filename: str
    level: int | None
    state: str | None
    digit: str | None
    source: str | None
    enabled: bool | None


class TemplateInventoryService:
    """Collects ready/digit template metadata without judging it.

    The inventory service only reads template folders and index files. It does
    not decide whether a template is good or bad. That keeps health analysis and
    future GUI actions independent from filesystem parsing.
    """

    def __init__(
        self,
        *,
        ready_template_dir: Path = paths.READY_TEMPLATE_DIR,
        digit_template_dir: Path = paths.DIGIT_TEMPLATE_DIR,
        project_root: Path = paths.PROJECT_ROOT,
    ) -> None:
        self.ready_template_dir = ready_template_dir
        self.digit_template_dir = digit_template_dir
        self.project_root = project_root

    def collect(self) -> list[TemplateRecord]:
        records: list[TemplateRecord] = []
        records.extend(self._collect_kind("ready", self.ready_template_dir))
        records.extend(self._collect_kind("digit", self.digit_template_dir))
        return records

    def _collect_kind(self, kind: TemplateKind, template_dir: Path) -> list[TemplateRecord]:
        if not template_dir.exists():
            return [
                TemplateRecord(
                    kind=kind,
                    path=template_dir,
                    relative_path=self._relative(template_dir),
                    filename=template_dir.name,
                    exists=False,
                    loadable=False,
                    indexed=False,
                    index_enabled=None,
                    level=None,
                    state=None,
                    digit=None,
                    source="missing_directory",
                    parse_message=f"Missing {kind} template directory.",
                )
            ]

        index_entries = self._load_index(template_dir, kind)
        index_by_name = {entry.filename: entry for entry in index_entries}

        file_names = {path.name for path in template_dir.glob("*.png")}
        all_names = sorted(file_names | set(index_by_name.keys()))

        records: list[TemplateRecord] = []
        for filename in all_names:
            path = template_dir / filename
            entry = index_by_name.get(filename)
            records.append(self._record_for_file(kind, path, entry))

        return records

    def _record_for_file(
        self,
        kind: TemplateKind,
        path: Path,
        entry: _IndexEntry | None,
    ) -> TemplateRecord:
        exists = path.exists()
        filename_level, filename_state, filename_digit, parse_message = self._parse_filename(kind, path.name)

        loadable = False
        image_width: int | None = None
        image_height: int | None = None

        if exists:
            try:
                with Image.open(path) as image:
                    image.verify()
                with Image.open(path) as image:
                    image_width, image_height = image.size
                loadable = True
            except Exception as exc:
                parse_message = f"Image could not be loaded: {exc}"

        level = entry.level if entry and entry.level is not None else filename_level
        state = entry.state if entry and entry.state is not None else filename_state
        digit = entry.digit if entry and entry.digit is not None else filename_digit
        source = entry.source if entry and entry.source else infer_source_from_filename(path.name)

        return TemplateRecord(
            kind=kind,
            path=path,
            relative_path=self._relative(path),
            filename=path.name,
            exists=exists,
            loadable=loadable,
            indexed=entry is not None,
            index_enabled=entry.enabled if entry else None,
            level=level,
            state=state,
            digit=digit,
            source=source or "unknown",
            image_width=image_width,
            image_height=image_height,
            filename_level=filename_level,
            filename_state=filename_state,
            filename_digit=filename_digit,
            index_level=entry.level if entry else None,
            index_state=entry.state if entry else None,
            index_digit=entry.digit if entry else None,
            index_source=entry.source if entry else None,
            parse_message=parse_message,
        )

    def _load_index(self, template_dir: Path, kind: TemplateKind) -> list[_IndexEntry]:
        index_path = template_dir / "index.json"
        if not index_path.exists():
            return []

        try:
            with index_path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except Exception:
            return []

        entries = self._normalise_index_container(raw)
        parsed: list[_IndexEntry] = []

        for item in entries:
            if not isinstance(item, dict):
                continue

            filename_value = (
                item.get("filename")
                or item.get("file")
                or item.get("path")
                or item.get("template_path")
                or item.get("name")
            )
            if not filename_value:
                continue

            filename = Path(str(filename_value)).name
            level = as_int(item.get("level"))
            source = as_str(item.get("source"))
            enabled = as_bool_or_none(item.get("enabled"))

            if kind == "ready":
                state = normalize_ready_state(item.get("state") or item.get("ready"))
                digit = None
            else:
                state = normalize_digit_state(item.get("state") or item.get("ready"))
                digit = normalize_digit(item.get("digit"))

            parsed.append(
                _IndexEntry(
                    filename=filename,
                    level=level,
                    state=state,
                    digit=digit,
                    source=source,
                    enabled=enabled,
                )
            )

        return parsed

    @staticmethod
    def _normalise_index_container(raw: Any) -> list[Any]:
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            nested = raw.get("templates") or raw.get("entries") or raw.get("items")
            if isinstance(nested, list):
                return nested
            if isinstance(nested, dict):
                return list(nested.values())
            return list(raw.values())
        return []

    def _parse_filename(
        self,
        kind: TemplateKind,
        filename: str,
    ) -> tuple[int | None, str | None, str | None, str | None]:
        if kind == "digit":
            match = _DIGIT_FILENAME_PATTERN.search(filename)
            if not match:
                return None, None, None, "Digit template filename does not match digit_* pattern."

            return (
                as_int(match.groupdict().get("level")),
                normalize_digit_state(match.groupdict().get("state")),
                normalize_digit(match.groupdict().get("digit")),
                None,
            )

        for pattern in _READY_FILENAME_PATTERNS:
            match = pattern.search(filename)
            if match:
                return (
                    as_int(match.group("level")),
                    normalize_ready_state(match.group("state")),
                    None,
                    None,
                )

        return None, None, None, "Ready template filename does not include a parseable level/state."

    def _relative(self, path: Path) -> Path:
        try:
            return path.resolve().relative_to(self.project_root.resolve())
        except Exception:
            return path


def as_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def as_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def as_bool_or_none(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "enabled"}:
        return True
    if text in {"false", "0", "no", "disabled"}:
        return False
    return None


def normalize_ready_state(value: object) -> str | None:
    text = str(value).strip().lower() if value is not None else ""
    if text in {"yes", "ready", "true", "1"}:
        return "yes"
    if text in {"no", "not_ready", "not-ready", "false", "0"}:
        return "no"
    return None


def normalize_digit_state(value: object) -> str | None:
    text = str(value).strip().lower() if value is not None else ""
    if text in {"yes", "ready", "true", "1"}:
        return "ready"
    if text in {"no", "not_ready", "not-ready", "false", "0"}:
        return "not_ready"
    return None


def normalize_digit(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if len(text) == 1 and text.isdigit() else None


def infer_source_from_filename(filename: str) -> str:
    text = filename.lower()
    if "_manual_" in text:
        return "manual"
    if "_loop_auto_" in text:
        return "loop_auto"
    if "_auto_" in text:
        return "auto"
    return "filename"
