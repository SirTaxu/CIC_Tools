from __future__ import annotations

import argparse

from crafting_bot.services.log_inventory_service import format_bytes
from crafting_bot.services.log_trim_service import MainLogTrimService


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive old lines from logs/log.txt and keep the active log focused.")
    parser.add_argument("--before", default=None, help="Archive log lines before this timestamp, e.g. '2026-06-10 12:00:00'.")
    parser.add_argument("--keep-last-lines", type=int, default=None, help="Archive everything except the last N lines.")
    parser.add_argument("--apply", action="store_true", help="Actually write archive and rewrite log.txt. Dry-run by default.")
    args = parser.parse_args()

    if args.before and args.keep_last_lines:
        raise SystemExit("Use either --before or --keep-last-lines, not both.")

    service = MainLogTrimService()
    plan = service.build_plan(
        before_timestamp=args.before,
        keep_last_lines=args.keep_last_lines,
        apply=args.apply,
    )

    print("Main log trim")
    print("-" * 80)
    print(f"apply: {plan.apply}")
    print(f"mode: {plan.mode}")
    print(f"source: {plan.source_path}")
    print(f"archive_path: {plan.archive_path}")
    print(f"original_line_count: {plan.original_line_count}")
    print(f"archived_line_count: {plan.archived_line_count}")
    print(f"kept_line_count: {plan.kept_line_count}")

    if not plan.apply and plan.archived_line_count > 0:
        print("")
        print("Dry-run only. Re-run with --apply to archive old lines and rewrite log.txt.")
    elif plan.apply:
        print("")
        print("Trim apply complete. Older lines were archived before log.txt was rewritten.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
