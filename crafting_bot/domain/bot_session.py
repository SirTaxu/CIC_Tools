from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

BotSessionState = Literal["idle", "starting", "running", "stopping", "stopped", "failed"]
BotSessionCommandKind = Literal["stop"]


@dataclass(frozen=True)
class BotSessionStatus:
    """Serializable status snapshot for a bot session.

    This is the shared boundary between the headless runtime, GUI, and CLI.
    Presentation layers should be able to read this without importing loop
    internals or touching RebuildLoopRunner directly.
    """

    session_id: str
    state: BotSessionState
    pid: int | None
    started_at: str | None
    updated_at: str
    mode: str = "-"
    screen: str = "UNKNOWN"
    level_text: str = "-"
    ready: str = "unknown"
    cycles_completed: int = 0
    hire_setups_completed: int = 0
    reincarnations_completed: int = 0
    same_level_seconds: float = 0.0
    last_action: str = "-"
    trigger_reason: str = "-"
    selected_cycle: str | None = None
    message: str = ""
    stopped_reason: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "state": self.state,
            "pid": self.pid,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "mode": self.mode,
            "screen": self.screen,
            "level_text": self.level_text,
            "ready": self.ready,
            "cycles_completed": self.cycles_completed,
            "hire_setups_completed": self.hire_setups_completed,
            "reincarnations_completed": self.reincarnations_completed,
            "same_level_seconds": self.same_level_seconds,
            "last_action": self.last_action,
            "trigger_reason": self.trigger_reason,
            "selected_cycle": self.selected_cycle,
            "message": self.message,
            "stopped_reason": self.stopped_reason,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BotSessionStatus":
        return cls(
            session_id=str(data.get("session_id") or "none"),
            state=_status_state(data.get("state")),
            pid=_optional_int(data.get("pid")),
            started_at=_optional_str(data.get("started_at")),
            updated_at=str(data.get("updated_at") or ""),
            mode=str(data.get("mode") or "-"),
            screen=str(data.get("screen") or "UNKNOWN"),
            level_text=str(data.get("level_text") or "-"),
            ready=str(data.get("ready") or "unknown"),
            cycles_completed=_int_value(data.get("cycles_completed")),
            hire_setups_completed=_int_value(data.get("hire_setups_completed")),
            reincarnations_completed=_int_value(data.get("reincarnations_completed")),
            same_level_seconds=_float_value(data.get("same_level_seconds")),
            last_action=str(data.get("last_action") or "-"),
            trigger_reason=str(data.get("trigger_reason") or "-"),
            selected_cycle=_optional_str(data.get("selected_cycle")),
            message=str(data.get("message") or ""),
            stopped_reason=_optional_str(data.get("stopped_reason")),
            error=_optional_str(data.get("error")),
        )


@dataclass(frozen=True)
class BotSessionCommand:
    """Serializable command for a running bot session.

    The first supported command is stop. Keeping this as a domain object lets a
    future headless process and GUI communicate without being the same object.
    """

    command: BotSessionCommandKind
    session_id: str | None
    requested_at: str
    reason: str = "manual_stop"

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "session_id": self.session_id,
            "requested_at": self.requested_at,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BotSessionCommand":
        return cls(
            command="stop",
            session_id=_optional_str(data.get("session_id")),
            requested_at=str(data.get("requested_at") or ""),
            reason=str(data.get("reason") or "manual_stop"),
        )


@dataclass
class BotSessionCounters:
    """Mutable counters owned by a session controller."""

    cycles_completed: int = 0
    hire_setups_completed: int = 0
    reincarnations_completed: int = 0


def new_session_id() -> str:
    return uuid4().hex[:12]


def _status_state(value: object) -> BotSessionState:
    text = str(value or "idle")
    if text in {"idle", "starting", "running", "stopping", "stopped", "failed"}:
        return text  # type: ignore[return-value]
    return "idle"


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _int_value(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float_value(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
