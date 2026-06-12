from __future__ import annotations

import argparse
import json

from crafting_bot.services.template_health_analyzer import TemplateHealthAnalyzer
from crafting_bot.services.template_inventory_service import TemplateInventoryService
from crafting_bot.services.template_quarantine_service import TemplateQuarantineService

DEFAULT_SAFE_CODES = {"unreadable_image"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run or apply template quarantine from health findings.")
    parser.add_argument(
        "--code",
        action="append",
        default=[],
        help="Finding code to quarantine. Can be repeated. Default: unreadable_image.",
    )
    parser.add_argument(
        "--severity",
        choices=("error", "warning", "info", "all"),
        default="error",
        help="Limit selected findings by severity. Default: error.",
    )
    parser.add_argument("--apply", action="store_true", help="Actually move files. Without this, only dry-run.")
    args = parser.parse_args()

    selected_codes = set(args.code) if args.code else set(DEFAULT_SAFE_CODES)

    report = TemplateHealthAnalyzer().analyze(TemplateInventoryService().collect())

    selected = []
    for finding in report.findings:
        if finding.code not in selected_codes:
            continue
        if args.severity != "all" and finding.severity != args.severity:
            continue
        if not finding.path:
            continue
        selected.append(finding)

    service = TemplateQuarantineService()
    result = service.quarantine(
        selected,
        apply=args.apply,
        reason="_".join(sorted(selected_codes)),
    )

    print("Template quarantine")
    print("-" * 80)
    print(f"apply: {result['apply']}")
    print(f"selected_count: {result['count']}")
    print(f"quarantine_dir: {result['quarantine_dir']}")

    if not args.apply:
        print("")
        print("Dry-run only. Re-run with --apply to move the selected files.")

    print("")
    print(json.dumps(result["items"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
