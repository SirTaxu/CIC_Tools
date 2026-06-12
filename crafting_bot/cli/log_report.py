from __future__ import annotations

import argparse

from crafting_bot.services.log_inventory_service import LogInventoryService, format_bytes


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize logs folder size and largest files.")
    parser.add_argument("--top", type=int, default=20, help="Number of largest files to print.")
    parser.add_argument("--include-archives", action="store_true", help="Include logs/archive in the summary.")
    args = parser.parse_args()

    report = LogInventoryService().collect(include_archives=args.include_archives)

    print("Log report")
    print("-" * 80)
    print(f"log_dir: {report.log_dir}")
    print(f"total_files: {report.total_files}")
    print(f"total_size: {format_bytes(report.total_size_bytes)}")
    print("")

    print("By category")
    print("-" * 80)
    for category, size in sorted(report.size_by_category.items(), key=lambda item: item[1], reverse=True):
        count = report.count_by_category.get(category, 0)
        print(f"{category:20s} {count:6d} files  {format_bytes(size):>12s}")

    print("")
    print(f"Top {args.top} largest files")
    print("-" * 80)
    for record in sorted(report.records, key=lambda item: item.size_bytes, reverse=True)[: max(0, args.top)]:
        active = " active" if record.is_active_file else ""
        print(f"{format_bytes(record.size_bytes):>12s}  {record.category:18s}  {record.relative_path}{active}")

    print("")
    print("Archive dry-run example:")
    print('$env:PYTHONDONTWRITEBYTECODE="1"; python -B -m crafting_bot.cli.archive_logs --older-than-days 7')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
