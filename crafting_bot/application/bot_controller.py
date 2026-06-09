from __future__ import annotations

from typing import Any, Callable

from crafting_bot.application.progress_events import BotProgressEvent
from crafting_bot.application.settings import RebuildLoopSettings
from crafting_bot.domain.loop_execution import LoopIterationResult, LoopRunResult
from crafting_bot.services.rebuild_loop_runner import RebuildLoopRunner


class BotController:
    """Application boundary used by both GUI and CLI.

    Presentation layers should call this controller instead of constructing or
    calling lower-level runners directly. This keeps the bot's behavior path
    identical between terminal and GUI execution.
    """

    def __init__(self, *, rebuild_loop_runner: RebuildLoopRunner) -> None:
        self._rebuild_loop_runner = rebuild_loop_runner

    def run_rebuild_loop(
        self,
        settings: RebuildLoopSettings,
        *,
        stop_event: Any | None = None,
        on_event: Callable[[BotProgressEvent], None] | None = None,
    ) -> LoopRunResult:
        def handle_iteration(iteration: LoopIterationResult) -> None:
            if on_event is not None:
                on_event(BotProgressEvent.from_iteration(iteration))

        return self._rebuild_loop_runner.run(
            **settings.to_runner_kwargs(),
            stop_event=stop_event,
            on_iteration=handle_iteration if on_event is not None else None,
        )
