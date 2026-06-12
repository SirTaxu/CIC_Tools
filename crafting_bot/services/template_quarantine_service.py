from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from crafting_bot import paths
from crafting_bot.domain.template_health import TemplateHealthFinding


class TemplateQuarantineService:
    """Moves selected template files into a timestamped quarantine folder.

    This service never deletes files. The default CLI path is dry-run only, and
    applying quarantine requires an explicit --apply flag.
    """

    def __init__(
        self,
        *,
        project_root: Path = paths.PROJECT_ROOT,
        quarantine_root: Path = paths.DATA_DIR / "template_quarantine",
    ) -> None:
        self.project_root = project_root
        self.quarantine_root = quarantine_root

    def quarantine(
        self,
        findings: list[TemplateHealthFinding],
        *,
        apply: bool,
        reason: str,
    ) -> dict[str, object]:
        selected = [finding for finding in findings if finding.path and finding.path.exists()]
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        target_root = self.quarantine_root / f"{stamp}_{safe_name(reason)}"

        moved: list[dict[str, str]] = []

        for finding in selected:
            assert finding.path is not None
            source = finding.path

            relative = finding.relative_path or self._relative(source)
            destination = target_root / relative

            moved.append(
                {
                    "source": str(source),
                    "destination": str(destination),
                    "code": finding.code,
                    "severity": finding.severity,
                    "message": finding.message,
                }
            )

            if apply:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(destination))

        if apply:
            target_root.mkdir(parents=True, exist_ok=True)
            manifest = target_root / "manifest.json"
            manifest.write_text(json.dumps(moved, indent=2), encoding="utf-8")

        return {
            "apply": apply,
            "count": len(moved),
            "quarantine_dir": str(target_root),
            "items": moved,
        }

    def _relative(self, path: Path) -> Path:
        try:
            return path.resolve().relative_to(self.project_root.resolve())
        except Exception:
            return path.name  # type: ignore[return-value]


def safe_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.strip())
    return cleaned[:60] or "template_quarantine"
