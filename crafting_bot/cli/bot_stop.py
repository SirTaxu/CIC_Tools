from __future__ import annotations

import argparse

from crafting_bot.services.bot_command_store import BotCommandStore
from crafting_bot.services.bot_status_store import BotStatusStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Request a running bot session to stop.")
    parser.add_argument("--session-id", default=None, help="Optional session id to stop. Defaults to latest status session.")
    parser.add_argument("--reason", default="manual_stop", help="Reason stored with the stop command.")
    args = parser.parse_args()

    status = BotStatusStore().read()
    session_id = args.session_id or (status.session_id if status.session_id != "none" else None)

    command = BotCommandStore().request_stop(session_id=session_id, reason=args.reason)

    print("Stop requested")
    print("-" * 80)
    print(f"session_id: {command.session_id}")
    print(f"requested_at: {command.requested_at}")
    print(f"reason: {command.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
