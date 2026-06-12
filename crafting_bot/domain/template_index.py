from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

TemplateKind = Literal["ready", "digit"]


@dataclass(frozen=True)
class TemplateIndexAction:
    """One planned/applied index repair action."""

    kind: TemplateKind
    filename: str
    path: Path
    action: str
    reason: str
    level: int | None = None
    state: str | None = None
    digit: str | None = None
    source: str | None = None
    applied: bool = False


@dataclass(frozen=True)
class TemplateIndexSyncResult:
    """Result from synchronizing template files into index.json."""

    apply: bool
    actions: tuple[TemplateIndexAction, ...]
    ready_index_path: Path
    digit_index_path: Path

    @property
    def action_count(self) -> int:
        return len(self.actions)
