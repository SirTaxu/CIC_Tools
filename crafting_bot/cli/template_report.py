from __future__ import annotations

import argparse

from crafting_bot.services.template_health_analyzer import TemplateHealthAnalyzer
from crafting_bot.services.template_health_report_writer import TemplateHealthReportWriter
from crafting_bot.services.template_inventory_service import TemplateInventoryService


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a template health report.")
    parser.add_argument("--max-findings", type=int, default=80, help="Maximum findings to print to the console.")
    args = parser.parse_args()

    inventory = TemplateInventoryService()
    analyzer = TemplateHealthAnalyzer()
    writer = TemplateHealthReportWriter()

    report = analyzer.analyze(inventory.collect())
    paths = writer.write(report)

    print_summary(report.summary)
    print("")
    print(f"text_report: {paths['text']}")
    print(f"csv_report: {paths['csv']}")
    print(f"json_report: {paths['json']}")

    if report.findings:
        print("")
        print("Top findings")
        print("-" * 80)
        for finding in report.findings[: max(0, args.max_findings)]:
            location = finding.relative_path or finding.path or "-"
            print(f"[{finding.severity.upper()}] {finding.code}: {location}")
            print(f"  {finding.message}")
            print(f"  Recommendation: {finding.recommendation}")
    else:
        print("")
        print("No findings.")

    return 0


def print_summary(summary: dict[str, int]) -> None:
    print("Template health summary")
    print("-" * 80)
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    raise SystemExit(main())
