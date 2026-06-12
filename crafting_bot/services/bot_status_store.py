from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from crafting_bot import paths
from crafting_bot.domain.bot_session import BotSessionStatus, new_session_id


class BotStatusStore:
    """File-backed status snapshot store.

    The GUI, CLI, and headless runner can all use this store without sharing the
    same Python object. Writes are atomic enough for this local single-user tool:
    write temporary JSON, then replace the active file.
    """

    def __init__(self, path: Path = paths.LOG_DIR / "bot_status.json") -> None:
        self.path = path

    def read(self) -> BotSessionStatus:
        if not self.path.exists():
            return self.idle_status(message="No bot status file exists yet.")

        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            return self.idle_status(message=f"Could not read bot status: {exc}")

        if not isinstance(data, dict):
            return self.idle_status(message="Bot status file did not contain a JSON object.")

        return BotSessionStatus.from_dict(data)

    def write(self, status: BotSessionStatus) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(json.dumps(status.to_dict(), indent=2), encoding="utf-8")
        temp_path.replace(self.path)

    def write_idle(self, *, message: str = "Bot is idle.") -> BotSessionStatus:
        status = self.idle_status(message=message)
        self.write(status)
        return status

    def idle_status(self, *, message: str = "Bot is idle.") -> BotSessionStatus:
        return BotSessionStatus(
            session_id="none",
            state="idle",
            pid=os.getpid(),
            started_at=None,
            updated_at=timestamp_now(),
            message=message,
        )


def timestamp_now() -> str:
    return datetime.now().isoformat(timespec="seconds")
