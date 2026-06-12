from __future__ import annotations

import argparse

from crafting_bot.services.log_error_finder_service import LogErrorFinderService


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract important failures and warnings from log.txt.")
    parser.add_argument("--tail-lines", type=int, default=5000, help="Only scan the last N lines. Use 0 for all lines.")
    parser.add_argument("--include-info", action="store_true", help="Include info events such as safe no-progress and completed cycles.")
    parser.add_argument("--errors-only", action="store_true", help="Only show error-severity events.")
    parser.add_argument("--code", action="append", default=[], help="Only show a specific event code. Can be repeated.")
    parser.add_argument("--context-lines", type=int, default=0, help="Show N lines before/after each event.")
    parser.add_argument("--max-events", type=int, default=120, help="Maximum events to print.")
    parser.add_argument("--write", action="store_true", help="Write a report to logs/error_reports.")
    parser.add_argument(
        "--show-reset-drops",
        action="store_true",
        help="Do not suppress suspicious level drops near reincarnation/session reset context.",
    )
    args = parser.parse_args()

    tail_lines = None if args.tail_lines == 0 else args.tail_lines
    service = LogErrorFinderService()
    report = service.find(
        tail_lines=tail_lines,
        include_info=args.include_info,
        errors_only=args.errors_only,
        code_filter=set(args.code) if args.code else None,
        context_lines=args.context_lines,
        suppress_expected_resets=not args.show_reset_drops,
    )

    print("Log error finder")
    print("-" * 80)
    print(f"source: {report.source_path}")
    print(f"scanned_lines: {report.scanned_lines}")
    print(f"errors: {report.error_count}")
    print(f"warnings: {report.warning_count}")
    print(f"info: {report.info_count}")

    if args.write:
        output = service.write_report(report)
        print(f"report: {output}")

    print("")
    print("Events")
    print("-" * 80)

    if not report.events:
        print("No important events found.")
        return 0

    for event in report.events[-max(0, args.max_events):]:
        timestamp = event.timestamp or "-"
        print(f"[{event.severity.upper()}] line={event.line_number} time={timestamp} code={event.code}")
        for context_line in event.context_before:
            print(f"  before: {context_line}")
        print(f"  {event.message}")
        for context_line in event.context_after:
            print(f"  after: {context_line}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
