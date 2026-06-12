from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Callable

from crafting_bot.application.bot_controller import BotController
from crafting_bot.application.progress_events import BotProgressEvent
from crafting_bot.application.settings import RebuildLoopSettings
from crafting_bot.domain.bot_session import BotSessionCounters, BotSessionStatus, new_session_id
from crafting_bot.domain.loop_execution import LoopRunResult
from crafting_bot.services.bot_command_store import BotCommandStore, CommandAwareStopEvent
from crafting_bot.services.bot_status_store import BotStatusStore, timestamp_now


@dataclass
class BotSessionHandle:
    """Handle for an in-process background bot session."""

    session_id: str
    thread: threading.Thread
    stop_event: CommandAwareStopEvent

    def stop(self) -> None:
        self.stop_event.set()

    @property
    def running(self) -> bool:
        return self.thread.is_alive()


class BotSessionController:
    """Runtime boundary between presentation layers and the bot.

    GUI and CLI code should depend on this controller instead of constructing
    workers that directly own loop runners.
    """

    def __init__(
        self,
        *,
        bot_controller: BotController | None = None,
        status_store: BotStatusStore | None = None,
        command_store: BotCommandStore | None = None,
    ) -> None:
        if bot_controller is None:
            # Import here to avoid a factory/session-controller circular import.
            from crafting_bot.composition.container import BotContainer

            bot_controller = BotContainer().build_bot_controller()

        self.bot_controller = bot_controller
        self.status_store = status_store or BotStatusStore()
        self.command_store = command_store or BotCommandStore()
        self._handle: BotSessionHandle | None = None

    def read_status(self) -> BotSessionStatus:
        return self.status_store.read()

    def request_stop(self, *, session_id: str | None = None, reason: str = "manual_stop") -> None:
        if self._handle is not None and (session_id is None or session_id == self._handle.session_id):
            self._handle.stop()

        self.command_store.request_stop(session_id=session_id, reason=reason)

        current = self.status_store.read()
        if current.state in {"starting", "running"} and (session_id is None or session_id == current.session_id):
            self.status_store.write(
                _replace_status(
                    current,
                    state="stopping",
                    updated_at=timestamp_now(),
                    last_action="stop requested",
                    message=f"Stop requested: {reason}",
                )
            )

    def run_sync(
        self,
        settings: RebuildLoopSettings,
        *,
        session_id: str | None = None,
        on_status: Callable[[BotSessionStatus], None] | None = None,
    ) -> LoopRunResult:
        actual_session_id = session_id or new_session_id()
        self.command_store.clear()
        stop_event = CommandAwareStopEvent(
            command_store=self.command_store,
            session_id=actual_session_id,
        )
        return self._run_sync_with_stop_event(
            settings,
            session_id=actual_session_id,
            stop_event=stop_event,
            on_status=on_status,
        )

    def start_background(
        self,
        settings: RebuildLoopSettings,
        *,
        on_status: Callable[[BotSessionStatus], None] | None = None,
    ) -> BotSessionHandle:
        if self._handle is not None and self._handle.running:
            return self._handle

        session_id = new_session_id()
        local_event = threading.Event()
        stop_event = CommandAwareStopEvent(
            local_event=local_event,
            command_store=self.command_store,
            session_id=session_id,
        )

        def target() -> None:
            self._run_sync_with_stop_event(
                settings,
                session_id=session_id,
                stop_event=stop_event,
                on_status=on_status,
            )

        thread = threading.Thread(target=target, daemon=True)
        self._handle = BotSessionHandle(session_id=session_id, thread=thread, stop_event=stop_event)
        thread.start()
        return self._handle

    def _run_sync_with_stop_event(
        self,
        settings: RebuildLoopSettings,
        *,
        session_id: str,
        stop_event: CommandAwareStopEvent,
        on_status: Callable[[BotSessionStatus], None] | None,
    ) -> LoopRunResult:
        self.command_store.clear()
        started_at = timestamp_now()
        counters = BotSessionCounters()

        self._publish(
            BotSessionStatus(
                session_id=session_id,
                state="starting",
                pid=os.getpid(),
                started_at=started_at,
                updated_at=started_at,
                mode=settings.mode,
                last_action="start",
                message="Bot session starting.",
            ),
            on_status,
        )

        try:
            result = self.bot_controller.run_rebuild_loop(
                settings,
                stop_event=stop_event,
                on_event=lambda event: self._on_event(
                    event=event,
                    settings=settings,
                    session_id=session_id,
                    started_at=started_at,
                    counters=counters,
                    on_status=on_status,
                ),
            )

            final_state = "stopped" if result.stopped_reason != "error" else "failed"
            self._publish(
                BotSessionStatus(
                    session_id=session_id,
                    state=final_state,
                    pid=os.getpid(),
                    started_at=started_at,
                    updated_at=timestamp_now(),
                    mode=result.mode,
                    cycles_completed=result.cycles_completed,
                    hire_setups_completed=counters.hire_setups_completed,
                    reincarnations_completed=counters.reincarnations_completed,
                    last_action="stopped",
                    message=result.message,
                    stopped_reason=result.stopped_reason,
                    error=None if final_state == "stopped" else result.message,
                ),
                on_status,
            )
            return result
        except Exception as exc:
            self._publish(
                BotSessionStatus(
                    session_id=session_id,
                    state="failed",
                    pid=os.getpid(),
                    started_at=started_at,
                    updated_at=timestamp_now(),
                    mode=settings.mode,
                    cycles_completed=counters.cycles_completed,
                    hire_setups_completed=counters.hire_setups_completed,
                    reincarnations_completed=counters.reincarnations_completed,
                    last_action="error",
                    message=f"Bot session failed: {exc}",
                    error=str(exc),
                ),
                on_status,
            )
            raise
        finally:
            self.command_store.clear()

    def _on_event(
        self,
        *,
        event: BotProgressEvent,
        settings: RebuildLoopSettings,
        session_id: str,
        started_at: str,
        counters: BotSessionCounters,
        on_status: Callable[[BotSessionStatus], None] | None,
    ) -> None:
        iteration = event.original_iteration
        if iteration is not None:
            if iteration.action == "cycle" and event.cycle_success:
                counters.cycles_completed += 1
            elif iteration.action == "hire" and "completed" in iteration.message.lower() and "failed" not in iteration.message.lower():
                counters.hire_setups_completed += 1
            elif iteration.action == "reincarnate" and "completed" in iteration.message.lower() and "failed" not in iteration.message.lower():
                counters.reincarnations_completed += 1

        message = event.message
        if event.selected_cycle:
            message = f"{message} Selected cycle: {event.selected_cycle}."

        self._publish(
            BotSessionStatus(
                session_id=session_id,
                state="running",
                pid=os.getpid(),
                started_at=started_at,
                updated_at=timestamp_now(),
                mode=settings.mode,
                screen=event.screen,
                level_text=event.level_text,
                ready=event.ready,
                cycles_completed=counters.cycles_completed,
                hire_setups_completed=counters.hire_setups_completed,
                reincarnations_completed=counters.reincarnations_completed,
                same_level_seconds=event.same_level_seconds,
                last_action=event.event_type,
                trigger_reason=event.trigger_reason,
                selected_cycle=event.selected_cycle,
                message=message,
            ),
            on_status,
        )

    def _publish(
        self,
        status: BotSessionStatus,
        on_status: Callable[[BotSessionStatus], None] | None,
    ) -> None:
        self.status_store.write(status)
        if on_status is not None:
            on_status(status)


def _replace_status(status: BotSessionStatus, **changes: object) -> BotSessionStatus:
    data = status.to_dict()
    data.update(changes)
    return BotSessionStatus.from_dict(data)
