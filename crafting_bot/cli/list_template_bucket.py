from __future__ import annotations

import argparse

from crafting_bot.services.template_inventory_service import TemplateInventoryService


def main() -> int:
    parser = argparse.ArgumentParser(description="List templates for a specific level/state/digit bucket.")
    parser.add_argument("--level", type=int, default=None, help="Filter by level.")
    parser.add_argument("--kind", choices=("ready", "digit", "all"), default="all", help="Filter by template kind.")
    parser.add_argument("--state", default=None, help="Filter by state: yes/no/ready/not_ready.")
    parser.add_argument("--digit", default=None, help="Filter by digit 0-9.")
    args = parser.parse_args()

    records = TemplateInventoryService().collect()

    filtered = []
    for record in records:
        if args.kind != "all" and record.kind != args.kind:
            continue
        if args.level is not None and record.level != args.level:
            continue
        if args.state is not None and record.state != args.state:
            continue
        if args.digit is not None and record.digit != args.digit:
            continue
        filtered.append(record)

    print("Template bucket")
    print("-" * 80)
    print(f"count: {len(filtered)}")
    print(f"level: {args.level}")
    print(f"kind: {args.kind}")
    print(f"state: {args.state}")
    print(f"digit: {args.digit}")
    print("")

    for record in sorted(filtered, key=lambda item: (item.kind, item.level or 9999, item.state or "", item.digit or "", item.filename)):
        status = "ok" if record.exists and record.loadable else "bad"
        indexed = "indexed" if record.indexed else "unindexed"
        print(
            f"[{record.kind}] {record.filename} "
            f"level={record.level} state={record.state} digit={record.digit} "
            f"source={record.source} {indexed} {status}"
        )
        print(f"  {record.relative_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
