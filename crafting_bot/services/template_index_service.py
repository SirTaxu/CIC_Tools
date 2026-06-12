from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from crafting_bot import paths
from crafting_bot.domain.template_health import TemplateRecord
from crafting_bot.domain.template_index import TemplateIndexAction, TemplateIndexSyncResult


@dataclass
class _IndexDocument:
    path: Path
    data: Any
    entries: list[dict[str, Any]]


class TemplateIndexService:
    """Repairs and synchronizes template index.json files.

    This service owns index file IO. It writes UTF-8 without BOM through
    pathlib.write_text(), and backs up index.json before any apply-mode change.
    """

    def __init__(
        self,
        *,
        ready_template_dir: Path = paths.READY_TEMPLATE_DIR,
        digit_template_dir: Path = paths.DIGIT_TEMPLATE_DIR,
        backup_root: Path = paths.DATA_DIR / "template_index_backups",
    ) -> None:
        self.ready_template_dir = ready_template_dir
        self.digit_template_dir = digit_template_dir
        self.backup_root = backup_root

    def sync_unindexed_records(
        self,
        records: Iterable[TemplateRecord],
        *,
        apply: bool,
    ) -> TemplateIndexSyncResult:
        ready_doc = self._load_index(self.ready_template_dir / "index.json")
        digit_doc = self._load_index(self.digit_template_dir / "index.json")

        ready_names = self._entry_names(ready_doc.entries)
        digit_names = self._entry_names(digit_doc.entries)

        actions: list[TemplateIndexAction] = []

        for record in records:
            if not self._is_syncable(record):
                continue

            if record.kind == "ready":
                if record.filename in ready_names:
                    continue
                entry = self._entry_from_record(record)
                actions.append(self._action_from_record(record, "add_index_entry", "Valid ready template was missing from index.json."))
                if apply:
                    ready_doc.entries.append(entry)
                    ready_names.add(record.filename)

            elif record.kind == "digit":
                if record.filename in digit_names:
                    continue
                entry = self._entry_from_record(record)
                actions.append(self._action_from_record(record, "add_index_entry", "Valid digit template was missing from index.json."))
                if apply:
                    digit_doc.entries.append(entry)
                    digit_names.add(record.filename)

        if apply and actions:
            self._backup_and_save(ready_doc)
            self._backup_and_save(digit_doc)

        if apply:
            actions = [self._mark_applied(action) for action in actions]

        return TemplateIndexSyncResult(
            apply=apply,
            actions=tuple(actions),
            ready_index_path=ready_doc.path,
            digit_index_path=digit_doc.path,
        )

    def ensure_ready_entry(
        self,
        *,
        template_path: Path,
        level: int,
        state: str,
        source: str,
        apply: bool,
    ) -> TemplateIndexAction:
        if level < 1:
            raise ValueError(f"Invalid ready template level {level}. Level 0 does not exist.")
        if state not in {"yes", "no"}:
            raise ValueError(f"Invalid ready state {state!r}; expected yes or no.")

        doc = self._load_index(self.ready_template_dir / "index.json")
        existing_names = self._entry_names(doc.entries)
        filename = template_path.name

        action = TemplateIndexAction(
            kind="ready",
            filename=filename,
            path=template_path,
            action="add_index_entry",
            reason="Ready template was added by train_ready_state.",
            level=level,
            state=state,
            digit=None,
            source=source,
            applied=False,
        )

        if filename in existing_names:
            return TemplateIndexAction(
                **{**action.__dict__, "action": "skip_existing_index_entry", "reason": "Ready template already exists in index.json.", "applied": apply}
            )

        if apply:
            doc.entries.append(
                {
                    "filename": filename,
                    "level": level,
                    "state": state,
                    "ready": state,
                    "source": source,
                    "enabled": True,
                    "sha256": sha256_file(template_path),
                }
            )
            self._backup_and_save(doc)
            action = self._mark_applied(action)

        return action

    def _is_syncable(self, record: TemplateRecord) -> bool:
        if not record.exists or not record.loadable or record.indexed:
            return False

        if record.level is not None and record.level < 1:
            return False

        if record.kind == "ready":
            return record.level is not None and record.state in {"yes", "no"}

        if record.kind == "digit":
            return record.digit is not None

        return False

    def _entry_from_record(self, record: TemplateRecord) -> dict[str, Any]:
        base: dict[str, Any] = {
            "filename": record.filename,
            "source": record.source or "filename",
            "enabled": True,
            "sha256": sha256_file(record.path),
        }

        if record.level is not None:
            base["level"] = record.level

        if record.kind == "ready":
            base["state"] = record.state
            base["ready"] = record.state
            return base

        if record.digit is not None:
            base["digit"] = record.digit
        if record.state is not None:
            base["state"] = record.state

        return base

    @staticmethod
    def _action_from_record(record: TemplateRecord, action: str, reason: str) -> TemplateIndexAction:
        return TemplateIndexAction(
            kind=record.kind,
            filename=record.filename,
            path=record.path,
            action=action,
            reason=reason,
            level=record.level,
            state=record.state,
            digit=record.digit,
            source=record.source,
            applied=False,
        )

    @staticmethod
    def _mark_applied(action: TemplateIndexAction) -> TemplateIndexAction:
        return TemplateIndexAction(
            kind=action.kind,
            filename=action.filename,
            path=action.path,
            action=action.action,
            reason=action.reason,
            level=action.level,
            state=action.state,
            digit=action.digit,
            source=action.source,
            applied=True,
        )

    def _load_index(self, index_path: Path) -> _IndexDocument:
        if index_path.exists():
            try:
                raw = json.loads(index_path.read_text(encoding="utf-8-sig"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in {index_path}: {exc}") from exc
        else:
            raw = {"templates": []}

        if isinstance(raw, list):
            entries = raw
        elif isinstance(raw, dict):
            container = raw.get("templates")
            if container is None:
                raw["templates"] = []
                entries = raw["templates"]
            elif isinstance(container, list):
                entries = container
            else:
                raise ValueError(f"Unsupported index format in {index_path}: templates must be a list.")
        else:
            raise ValueError(f"Unsupported index format in {index_path}: root must be an object or list.")

        return _IndexDocument(path=index_path, data=raw, entries=entries)

    def _backup_and_save(self, document: _IndexDocument) -> None:
        document.path.parent.mkdir(parents=True, exist_ok=True)
        if document.path.exists():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = self.backup_root / stamp
            backup_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(document.path, backup_dir / document.path.name)

        document.path.write_text(
            json.dumps(document.data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _entry_names(entries: list[dict[str, Any]]) -> set[str]:
        names: set[str] = set()
        for entry in entries:
            filename = entry.get("filename") or entry.get("file") or entry.get("path") or entry.get("template_path")
            if filename:
                names.add(Path(str(filename)).name)
        return names


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
