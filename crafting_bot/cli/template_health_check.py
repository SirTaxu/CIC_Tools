from __future__ import annotations

import argparse

from crafting_bot.services.template_health_analyzer import TemplateHealthAnalyzer
from crafting_bot.services.template_health_report_writer import TemplateHealthReportWriter
from crafting_bot.services.template_inventory_service import TemplateInventoryService


def main() -> int:
    parser = argparse.ArgumentParser(description="Check template health and return a useful exit code.")
    parser.add_argument("--fail-on-warnings", action="store_true", help="Return exit code 1 when warnings exist.")
    args = parser.parse_args()

    inventory = TemplateInventoryService()
    analyzer = TemplateHealthAnalyzer()
    writer = TemplateHealthReportWriter()

    report = analyzer.analyze(inventory.collect())
    paths = writer.write(report)

    for key, value in report.summary.items():
        print(f"{key}: {value}")

    print(f"text_report: {paths['text']}")

    if report.has_errors:
        print("template_health_check: failed because errors were found.")
        return 1

    if args.fail_on_warnings and report.has_warnings:
        print("template_health_check: failed because warnings were found and --fail-on-warnings was used.")
        return 1

    print("template_health_check: passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
