from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from crafting_bot import paths
from crafting_bot.domain.template_health import TemplateHealthFinding, TemplateHealthReport, TemplateRecord


class TemplateHealthReportWriter:
    """Writes template health reports in text, CSV, and JSON formats."""

    def __init__(self, output_dir: Path = paths.LOG_DIR / "template_health") -> None:
        self.output_dir = output_dir

    def write(self, report: TemplateHealthReport) -> dict[str, Path]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        text_path = self.output_dir / f"{stamp}_template_health_report.txt"
        csv_path = self.output_dir / f"{stamp}_template_health_findings.csv"
        json_path = self.output_dir / f"{stamp}_template_health_report.json"

        text_path.write_text(self._format_text(report), encoding="utf-8")
        self._write_csv(report.findings, csv_path)
        json_path.write_text(self._format_json(report), encoding="utf-8")

        return {
            "text": text_path,
            "csv": csv_path,
            "json": json_path,
        }

    def _format_text(self, report: TemplateHealthReport) -> str:
        lines: list[str] = []
        lines.append("Template Health Report")
        lines.append("=" * 80)
        lines.append("")
        lines.append("Summary")
        lines.append("-" * 80)
        for key, value in report.summary.items():
            lines.append(f"{key}: {value}")

        lines.append("")
        lines.append("Findings")
        lines.append("-" * 80)

        if not report.findings:
            lines.append("No findings.")
        else:
            for index, finding in enumerate(report.findings, start=1):
                location = finding.relative_path or finding.path or "-"
                lines.append(f"{index}. [{finding.severity.upper()}] {finding.code}")
                lines.append(f"   location: {location}")
                lines.append(f"   kind: {finding.kind} level={finding.level} state={finding.state} digit={finding.digit}")
                lines.append(f"   message: {finding.message}")
                lines.append(f"   recommendation: {finding.recommendation}")
                lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _write_csv(findings: tuple[TemplateHealthFinding, ...], path: Path) -> None:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "severity",
                    "code",
                    "kind",
                    "level",
                    "state",
                    "digit",
                    "relative_path",
                    "message",
                    "recommendation",
                ],
            )
            writer.writeheader()
            for finding in findings:
                writer.writerow(
                    {
                        "severity": finding.severity,
                        "code": finding.code,
                        "kind": finding.kind,
                        "level": finding.level,
                        "state": finding.state,
                        "digit": finding.digit,
                        "relative_path": str(finding.relative_path or finding.path or ""),
                        "message": finding.message,
                        "recommendation": finding.recommendation,
                    }
                )

    @staticmethod
    def _format_json(report: TemplateHealthReport) -> str:
        payload: dict[str, Any] = {
            "summary": report.summary,
            "findings": [TemplateHealthReportWriter._safe_asdict(item) for item in report.findings],
            "records": [TemplateHealthReportWriter._safe_asdict(item) for item in report.records],
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)

    @staticmethod
    def _safe_asdict(value: object) -> dict[str, object]:
        raw = asdict(value)  # type: ignore[arg-type]
        for key, item in list(raw.items()):
            if isinstance(item, Path):
                raw[key] = str(item)
        return raw
