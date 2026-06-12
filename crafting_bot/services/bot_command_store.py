from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from crafting_bot import paths
from crafting_bot.domain.bot_session import BotSessionCommand
from crafting_bot.services.bot_status_store import timestamp_now


class BotCommandStore:
    """File-backed command store for bot runtime control.

    The immediate goal is stop requests. This lets a future GUI or CLI request a
    stop from a headless bot without owning the bot's thread object.
    """

    def __init__(self, path: Path = paths.LOG_DIR / "bot_command.json") -> None:
        self.path = path

    def request_stop(self, *, session_id: str | None = None, reason: str = "manual_stop") -> BotSessionCommand:
        command = BotSessionCommand(
            command="stop",
            session_id=session_id,
            requested_at=timestamp_now(),
            reason=reason,
        )
        self.write(command)
        return command

    def write(self, command: BotSessionCommand) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(json.dumps(command.to_dict(), indent=2), encoding="utf-8")
        temp_path.replace(self.path)

    def read(self) -> BotSessionCommand | None:
        if not self.path.exists():
            return None

        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return None

        if not isinstance(data, dict):
            return None

        try:
            return BotSessionCommand.from_dict(data)
        except Exception:
            return None

    def stop_requested(self, *, session_id: str | None = None) -> bool:
        command = self.read()
        if command is None:
            return False

        if command.command != "stop":
            return False

        if command.session_id and session_id and command.session_id != session_id:
            return False

        return True

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


class CommandAwareStopEvent:
    """Stop-token compatible with the runner's stop_event usage.

    It behaves like a threading.Event for in-process control, but also checks the
    command store so external tools can request stop later.
    """

    def __init__(
        self,
        *,
        local_event: threading.Event | None = None,
        command_store: BotCommandStore | None = None,
        session_id: str | None = None,
    ) -> None:
        self.local_event = local_event or threading.Event()
        self.command_store = command_store
        self.session_id = session_id

    def is_set(self) -> bool:
        if self.local_event.is_set():
            return True

        if self.command_store is not None and self.command_store.stop_requested(session_id=self.session_id):
            self.local_event.set()
            return True

        return False

    def set(self) -> None:
        self.local_event.set()
        if self.command_store is not None:
            self.command_store.request_stop(session_id=self.session_id)

    def clear(self) -> None:
        self.local_event.clear()
        if self.command_store is not None:
            self.command_store.clear()

    def wait(self, timeout: float | None = None) -> bool:
        end_time = None if timeout is None else time.monotonic() + max(0.0, timeout)

        while True:
            if self.is_set():
                return True

            if end_time is not None:
                remaining = end_time - time.monotonic()
                if remaining <= 0:
                    return self.is_set()
                time.sleep(min(0.05, remaining))
            else:
                time.sleep(0.05)
