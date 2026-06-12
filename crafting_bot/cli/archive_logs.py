from __future__ import annotations

import argparse

from crafting_bot.services.log_archive_service import LogArchiveService
from crafting_bot.services.log_inventory_service import format_bytes


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive old log files into a zip file.")
    parser.add_argument("--older-than-days", type=int, default=7, help="Select files older than this many days. Default: 7.")
    parser.add_argument("--apply", action="store_true", help="Create the zip and remove archived originals.")
    parser.add_argument(
        "--include-active-files",
        action="store_true",
        help="Also allow archiving log.txt and latest_* files. Not recommended for normal cleanup.",
    )
    parser.add_argument(
        "--category",
        action="append",
        default=[],
        help="Restrict to a category from log_report. Can be repeated.",
    )
    parser.add_argument("--top", type=int, default=40, help="Maximum selected files to print.")
    args = parser.parse_args()

    categories = set(args.category) if args.category else None
    plan = LogArchiveService().build_plan(
        older_than_days=args.older_than_days,
        include_active_files=args.include_active_files,
        categories=categories,
        apply=args.apply,
    )

    print("Log archive")
    print("-" * 80)
    print(f"apply: {plan.apply}")
    print(f"older_than_days: {plan.older_than_days}")
    print(f"archive_path: {plan.archive_path}")
    print(f"selected_count: {plan.selected_count}")
    print(f"selected_size: {format_bytes(plan.selected_size_bytes)}")

    selected = list(plan.selected_actions)
    if selected:
        print("")
        print("Selected files")
        print("-" * 80)
        for action in selected[: max(0, args.top)]:
            print(f"{format_bytes(action.size_bytes):>12s}  {action.category:18s}  {action.relative_path}  [{action.status}]")
        if len(selected) > args.top:
            print(f"... {len(selected) - args.top} more selected file(s) not printed.")

    if not args.apply and selected:
        print("")
        print("Dry-run only. Re-run with --apply to create the archive and remove archived originals from logs.")
    elif args.apply:
        print("")
        print("Archive apply complete.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
