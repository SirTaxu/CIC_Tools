from __future__ import annotations

import argparse
import json

from crafting_bot.services.bot_status_store import BotStatusStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Show the latest bot session status.")
    parser.add_argument("--json", action="store_true", help="Print raw JSON status.")
    args = parser.parse_args()

    status = BotStatusStore().read()

    if args.json:
        print(json.dumps(status.to_dict(), indent=2))
        return 0

    print("Bot status")
    print("-" * 80)
    print(f"state: {status.state}")
    print(f"session_id: {status.session_id}")
    print(f"pid: {status.pid}")
    print(f"started_at: {status.started_at}")
    print(f"updated_at: {status.updated_at}")
    print(f"mode: {status.mode}")
    print(f"screen: {status.screen}")
    print(f"level: {status.level_text}")
    print(f"ready: {status.ready}")
    print(f"cycles_completed: {status.cycles_completed}")
    print(f"hire_setups_completed: {status.hire_setups_completed}")
    print(f"reincarnations_completed: {status.reincarnations_completed}")
    print(f"same_level_seconds: {status.same_level_seconds:.1f}")
    print(f"last_action: {status.last_action}")
    print(f"trigger_reason: {status.trigger_reason}")
    print(f"selected_cycle: {status.selected_cycle}")
    print(f"stopped_reason: {status.stopped_reason}")
    print(f"error: {status.error}")
    print(f"message: {status.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
