from __future__ import annotations

import argparse

from crafting_bot.services.template_index_service import TemplateIndexService
from crafting_bot.services.template_inventory_service import TemplateInventoryService


def main() -> int:
    parser = argparse.ArgumentParser(description="Add valid unindexed template files to index.json.")
    parser.add_argument("--apply", action="store_true", help="Write changes. Without this, the command is a dry-run.")
    parser.add_argument("--max-actions", type=int, default=80, help="Maximum actions to print.")
    args = parser.parse_args()

    records = TemplateInventoryService().collect()
    result = TemplateIndexService().sync_unindexed_records(records, apply=args.apply)

    print("Template index sync")
    print("-" * 80)
    print(f"apply: {result.apply}")
    print(f"actions: {result.action_count}")
    print(f"ready_index: {result.ready_index_path}")
    print(f"digit_index: {result.digit_index_path}")

    if result.actions:
        print("")
        print("Planned/applied actions")
        print("-" * 80)
        for action in result.actions[: max(0, args.max_actions)]:
            print(
                f"[{action.kind}] {action.action}: {action.filename} "
                f"level={action.level} state={action.state} digit={action.digit} applied={action.applied}"
            )
            print(f"  {action.reason}")
        if result.action_count > args.max_actions:
            print(f"... {result.action_count - args.max_actions} more action(s) not printed.")
    else:
        print("")
        print("No unindexed valid templates found.")

    if not args.apply and result.actions:
        print("")
        print("Dry-run only. Re-run with --apply to update index.json.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
