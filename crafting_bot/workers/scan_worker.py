from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

from crafting_bot.services.level_scanner import LevelScanner


@dataclass(frozen=True)
class BotStatus:
    running: bool
    screen: str = "UNKNOWN"
    level: str = "-"
    ready: str = "unknown"
    same_level_seconds: float = 0.0
    last_action: str = "-"
    message: str = ""


class ScanWorker:
    """Background worker that scans only. It does not click yet."""

    def __init__(self, scanner: LevelScanner, event_queue: queue.Queue[BotStatus]) -> None:
        self.scanner = scanner
        self.event_queue = event_queue
        self.stop_requested = threading.Event()
        self.thread: threading.Thread | None = None
        self.running = False
        self._last_level: int | None = None
        self._same_level_started_at = time.monotonic()

    def start(self) -> None:
        if self.running:
            return

        self.stop_requested.clear()
        self.running = True
        self._emit(BotStatus(running=True, screen="STARTING", message="Bot started."))
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if not self.running:
            return

        self.stop_requested.set()
        self._emit(
            BotStatus(
                running=True,
                screen="STOPPING",
                message="Stop requested. Waiting for loop boundary.",
            )
        )

    def _run_loop(self) -> None:
        try:
            while not self.stop_requested.is_set():
                result = self.scanner.scan()
                same_level_seconds = self._update_same_level_timer(result.level)

                self._emit(
                    BotStatus(
                        running=True,
                        screen=result.screen,
                        level=str(result.level) if result.level is not None else result.level_text,
                        ready=result.ready,
                        same_level_seconds=same_level_seconds,
                        last_action="scan",
                        message=result.message,
                    )
                )

                time.sleep(0.75)

        finally:
            self.running = False
            self._emit(BotStatus(running=False, screen="STOPPED", message="Bot stopped."))

    def _update_same_level_timer(self, level: int | None) -> float:
        now = time.monotonic()

        if level is None:
            self._last_level = None
            self._same_level_started_at = now
            return 0.0

        if level != self._last_level:
            self._last_level = level
            self._same_level_started_at = now
            return 0.0

        return now - self._same_level_started_at

    def _emit(self, status: BotStatus) -> None:
        self.event_queue.put(status)
