from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from crafting_bot.domain.cycle_execution import VerificationResult
from crafting_bot.domain.target_catalog import SearchTargetDefinition
from crafting_bot.infra.adb_client import AdbClient
from crafting_bot.services.screen_verifier import ScreenVerifier
from crafting_bot.services.search_target_service import SearchTargetRunResult, SearchTargetService


@dataclass(frozen=True)
class SearchWaitResult:
    """Result of polling for a visual search target.

    This stays outside the domain layer because it is an execution detail of
    waiting on live screenshots. The cycle runner only consumes the final
    accepted match, if any.
    """

    accepted: bool
    attempts: int
    elapsed_seconds: float
    search: SearchTargetRunResult | None
    message: str


@dataclass(frozen=True)
class VerificationWaitPolicy:
    """Stability requirements for a verification target.

    A single low-diff frame is not always enough in Crafting Idle Clicker:
    panels can be partially drawn or visually similar during transitions. The
    waiter therefore supports a minimum delay before the first check and a
    target-specific number of consecutive passing frames.
    """

    minimum_wait_seconds: float = 0.0
    consecutive_passes_required: int = 1


class ScreenWaiter:
    """Polls live screenshots until the expected next screen/target appears.

    CycleRunner should not know how to repeatedly capture, compare, or search.
    It only asks this service to wait for the next expected condition.
    """

    # Conservative, target-specific stability rules. These are deliberately kept
    # here, not in cycle definitions, because they describe live-screen waiting
    # behavior rather than game-flow structure.
    _VERIFICATION_POLICIES: dict[str, VerificationWaitPolicy] = {
        # Opening the fixed early rebuild panel is fast, but still needs to be
        # stable before clicking the fixed rebuild button.
        "early_rebuild_button_check_area": VerificationWaitPolicy(0.30, 2),

        # Take Reward screens can be briefly half-rendered after Rebuild.
        "early_reward_button_check_area": VerificationWaitPolicy(0.60, 2),
        "reward_button_check_area": VerificationWaitPolicy(0.75, 2),

        # Free screens are the most timing-sensitive transition in the current
        # flow, so wait slightly longer and require stable confirmation.
        "early_free_button_check_area": VerificationWaitPolicy(0.75, 2),
        "free_button_check_area": VerificationWaitPolicy(0.90, 2),

        # Dynamic workshop panel can render in pieces; don't run the dynamic
        # button search until the screen marker is stable.
        "rebuild_workshop_check_area": VerificationWaitPolicy(0.60, 2),

        # Reincarnation navigation screens should also be stable before the next tap.
        "dynasty_button_check_area": VerificationWaitPolicy(0.50, 2),
        "reincarnate_button_check_area": VerificationWaitPolicy(0.60, 2),
        "default_button_check_area": VerificationWaitPolicy(0.75, 2),

        # Returning to the level screen includes animations and digit rendering.
        "level_area": VerificationWaitPolicy(1.00, 2),
    }

    def __init__(
        self,
        *,
        adb: AdbClient,
        verifier: ScreenVerifier,
        search_targets: SearchTargetService,
        latest_screenshot_path: Path,
    ) -> None:
        self.adb = adb
        self.verifier = verifier
        self.search_targets = search_targets
        self.latest_screenshot_path = latest_screenshot_path

    def wait_for_verification(
        self,
        target_name: str | None,
        *,
        timeout_seconds: float,
        poll_interval_seconds: float,
        stop_event: Any | None = None,
    ) -> VerificationResult:
        if not target_name:
            return VerificationResult(None, False, None, None, None, "No verification target configured.")

        if self._stop_requested(stop_event):
            return self._stop_verification(target_name, "Stop requested before verification polling.")

        timeout_seconds = max(0.0, float(timeout_seconds))
        poll_interval_seconds = max(0.05, float(poll_interval_seconds))
        policy = self._policy_for(target_name)
        required_passes = max(1, int(policy.consecutive_passes_required))
        minimum_wait_seconds = max(0.0, float(policy.minimum_wait_seconds))

        started = time.monotonic()
        attempts = 0
        consecutive_passes = 0
        last_result: VerificationResult | None = None

        if minimum_wait_seconds > 0:
            if self._sleep_interruptible(min(minimum_wait_seconds, timeout_seconds), stop_event):
                return self._stop_verification(target_name, "Stop requested during verification minimum wait.")

        while True:
            if self._stop_requested(stop_event):
                return self._stop_verification(target_name, "Stop requested during verification polling.")
            attempts += 1
            screenshot: Image.Image | None = None
            if target_name != "level_area":
                screenshot = self.adb.capture()
                self._save_latest_screenshot(screenshot)

            result = self.verifier.verify(target_name, screenshot=screenshot)
            elapsed = time.monotonic() - started

            if result.passed is True:
                consecutive_passes += 1
            else:
                consecutive_passes = 0

            result = self._with_wait_message(
                result,
                attempts=attempts,
                elapsed=elapsed,
                consecutive_passes=consecutive_passes,
                required_passes=required_passes,
                minimum_wait_seconds=minimum_wait_seconds,
            )
            last_result = result

            if result.passed is True and consecutive_passes >= required_passes:
                return result

            if self._is_non_retryable_verification_failure(result):
                return result

            if elapsed >= timeout_seconds:
                return self._with_timeout_message(result, timeout_seconds=timeout_seconds)

            if self._sleep_interruptible(min(poll_interval_seconds, max(0.0, timeout_seconds - elapsed)), stop_event):
                return self._stop_verification(target_name, "Stop requested during verification poll wait.")

    def wait_for_search_target(
        self,
        definition: SearchTargetDefinition,
        *,
        timeout_seconds: float,
        poll_interval_seconds: float,
        save_preview: bool = True,
        stop_event: Any | None = None,
    ) -> SearchWaitResult:
        timeout_seconds = max(0.0, float(timeout_seconds))
        poll_interval_seconds = max(0.05, float(poll_interval_seconds))
        started = time.monotonic()
        attempts = 0
        last_search: SearchTargetRunResult | None = None
        last_error: str | None = None

        if self._stop_requested(stop_event):
            return SearchWaitResult(False, attempts, 0.0, None, f"Stop requested before search target {definition.name} polling.")

        while True:
            if self._stop_requested(stop_event):
                elapsed = time.monotonic() - started
                return SearchWaitResult(False, attempts, elapsed, last_search, f"Stop requested while waiting for search target {definition.name}.")
            attempts += 1
            try:
                screenshot = self.adb.capture()
                self._save_latest_screenshot(screenshot)
                search = self.search_targets.run(definition, screenshot=screenshot, save_preview=save_preview)
                last_search = search
                found = search.result
                accepted = bool(found.ok and found.score is not None and found.score <= definition.default_threshold)
                elapsed = time.monotonic() - started

                if accepted:
                    return SearchWaitResult(
                        accepted=True,
                        attempts=attempts,
                        elapsed_seconds=elapsed,
                        search=search,
                        message=(
                            f"Search target {definition.name} accepted after {attempts} attempt(s), "
                            f"{elapsed:.2f}s. {found.message}"
                        ),
                    )

                last_error = found.message

            except Exception as exc:
                elapsed = time.monotonic() - started
                last_error = str(exc)
                return SearchWaitResult(
                    accepted=False,
                    attempts=attempts,
                    elapsed_seconds=elapsed,
                    search=last_search,
                    message=f"Search target {definition.name} failed: {exc}",
                )

            elapsed = time.monotonic() - started
            if elapsed >= timeout_seconds:
                score_text = "unknown"
                if last_search and last_search.result.score is not None:
                    score_text = f"{last_search.result.score:.4f}"
                return SearchWaitResult(
                    accepted=False,
                    attempts=attempts,
                    elapsed_seconds=elapsed,
                    search=last_search,
                    message=(
                        f"Timed out after {timeout_seconds:.2f}s waiting for search target {definition.name}. "
                        f"attempts={attempts}, last_score={score_text}, last_message={last_error or 'none'}"
                    ),
                )

            if self._sleep_interruptible(min(poll_interval_seconds, max(0.0, timeout_seconds - elapsed)), stop_event):
                elapsed = time.monotonic() - started
                return SearchWaitResult(False, attempts, elapsed, last_search, f"Stop requested during search target {definition.name} poll wait.")

    @staticmethod
    def _stop_requested(stop_event: Any | None) -> bool:
        if stop_event is None:
            return False
        is_set = getattr(stop_event, "is_set", None)
        return bool(is_set()) if callable(is_set) else False

    @classmethod
    def _sleep_interruptible(cls, seconds: float, stop_event: Any | None) -> bool:
        deadline = time.monotonic() + max(0.0, float(seconds))
        while time.monotonic() < deadline:
            if cls._stop_requested(stop_event):
                return True
            time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
        return cls._stop_requested(stop_event)

    @staticmethod
    def _stop_verification(target_name: str | None, message: str) -> VerificationResult:
        return VerificationResult(
            target_name=target_name,
            attempted=False,
            passed=False,
            score=None,
            threshold=None,
            message=message,
            preview_path=None,
        )

    def _save_latest_screenshot(self, screenshot: Image.Image) -> None:
        self.latest_screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot.save(self.latest_screenshot_path)

    @classmethod
    def _policy_for(cls, target_name: str) -> VerificationWaitPolicy:
        return cls._VERIFICATION_POLICIES.get(target_name, VerificationWaitPolicy())

    @staticmethod
    def _with_wait_message(
        result: VerificationResult,
        *,
        attempts: int,
        elapsed: float,
        consecutive_passes: int,
        required_passes: int,
        minimum_wait_seconds: float,
    ) -> VerificationResult:
        stability_text = (
            f" attempts={attempts}, elapsed={elapsed:.2f}s, "
            f"stable_passes={consecutive_passes}/{required_passes}, "
            f"min_wait={minimum_wait_seconds:.2f}s."
        )
        return VerificationResult(
            target_name=result.target_name,
            attempted=result.attempted,
            passed=result.passed,
            score=result.score,
            threshold=result.threshold,
            message=f"{result.message}{stability_text}",
            preview_path=result.preview_path,
        )

    @staticmethod
    def _with_timeout_message(result: VerificationResult, *, timeout_seconds: float) -> VerificationResult:
        return VerificationResult(
            target_name=result.target_name,
            attempted=result.attempted,
            passed=False,
            score=result.score,
            threshold=result.threshold,
            message=f"Timed out after {timeout_seconds:.2f}s. Last check: {result.message}",
            preview_path=result.preview_path,
        )

    @staticmethod
    def _is_non_retryable_verification_failure(result: VerificationResult) -> bool:
        message = result.message.lower()
        return (
            "missing calibrated verification area" in message
            or "missing reference crop" in message
            or "crop size mismatch" in message
        )
