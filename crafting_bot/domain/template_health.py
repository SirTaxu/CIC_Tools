from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

TemplateKind = Literal["ready", "digit"]
TemplateSeverity = Literal["info", "warning", "error"]


@dataclass(frozen=True)
class TemplateRecord:
    """Metadata for one template file or index entry.

    This is intentionally data-only. Inventory, analysis, reporting, and
    quarantine behavior live in separate services.
    """

    kind: TemplateKind
    path: Path
    relative_path: Path
    filename: str
    exists: bool
    loadable: bool
    indexed: bool
    index_enabled: bool | None
    level: int | None
    state: str | None
    digit: str | None
    source: str
    image_width: int | None = None
    image_height: int | None = None
    filename_level: int | None = None
    filename_state: str | None = None
    filename_digit: str | None = None
    index_level: int | None = None
    index_state: str | None = None
    index_digit: str | None = None
    index_source: str | None = None
    parse_message: str | None = None


@dataclass(frozen=True)
class TemplateHealthFinding:
    """One health finding generated from template inventory."""

    severity: TemplateSeverity
    code: str
    message: str
    recommendation: str
    path: Path | None = None
    relative_path: Path | None = None
    kind: TemplateKind | None = None
    level: int | None = None
    state: str | None = None
    digit: str | None = None


@dataclass(frozen=True)
class TemplateHealthReport:
    """Complete health report result."""

    records: tuple[TemplateRecord, ...]
    findings: tuple[TemplateHealthFinding, ...]
    summary: dict[str, int] = field(default_factory=dict)

    @property
    def has_errors(self) -> bool:
        return any(finding.severity == "error" for finding in self.findings)

    @property
    def has_warnings(self) -> bool:
        return any(finding.severity == "warning" for finding in self.findings)
