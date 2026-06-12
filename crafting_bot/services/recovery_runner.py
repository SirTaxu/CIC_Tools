from __future__ import annotations

import hashlib
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from crafting_bot import paths
from crafting_bot.domain.recovery import (
    RecoveryContextName,
    RecoveryDecision,
    RecoveryExecutionResult,
    RecoveryRequest,
)
from crafting_bot.domain.screen_classification import ScreenClassificationResult
from crafting_bot.infra.adb_client import AdbClient
from crafting_bot.infra.calibration_store import CalibrationStore
from crafting_bot.services.recovery_policy import RecoveryPolicy
from crafting_bot.services.screen_classifier import ScreenClassifier


@dataclass(frozen=True)
class RecoveryRunResult:
    ok: bool
    before: ScreenClassificationResult
    decision: RecoveryDecision
    execution: RecoveryExecutionResult | None
    after: ScreenClassificationResult | None
    message: str
    report_path: Path | None = None


class RecoveryRunner:
    """Executes one bounded context-aware recovery action.

    Safety rules:
    - Return/navigation recovery uses slow BACK/ESC, up to three presses.
    - A safe/irrelevant tap is sent between repeated ESC presses to reduce the
      risk of closing the game accidentally.
    - Take Reward and Free are never escaped; they are completed forward.
    - When recovery returns to LEVEL_SCREEN, the loop must restart tracking from
      zero instead of keeping old expected-level history.
    """

    def __init__(
        self,
        *,
        classifier: ScreenClassifier,
        adb: AdbClient,
        calibration: CalibrationStore,
        policy: RecoveryPolicy | None = None,
    ) -> None:
        self.classifier = classifier
        self.adb = adb
        self.calibration = calibration
        self.policy = policy or RecoveryPolicy()

    def run(
        self,
        *,
        context: RecoveryContextName = "general",
        execute: bool = False,
        allow_forward_clicks: bool = False,
        reclassify_delay_seconds: float = 1.0,
        current_level: int | None = None,
    ) -> RecoveryRunResult:
        recovery_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        before = self.classifier.classify()
        before_snapshot = self._copy_latest_screenshot(recovery_id, "before")
        decision = self.policy.decide(RecoveryRequest(screen=before.screen, context=context))

        if not execute:
            result = RecoveryRunResult(
                ok=True,
                before=before,
                decision=decision,
                execution=None,
                after=None,
                message=(
                    f"Recovery dry-run: screen={before.screen}, action={decision.action}, "
                    f"risk={decision.risk}. No action executed."
                ),
            )
            report = self._write_report(recovery_id, result, before_snapshot, None)
            return RecoveryRunResult(**{**result.__dict__, "report_path": report})

        execution = self._execute_decision(
            decision,
            before=before,
            allow_forward_clicks=allow_forward_clicks,
            reclassify_delay_seconds=reclassify_delay_seconds,
            current_level=current_level,
        )
        after = self.classifier.classify()
        after_snapshot = self._copy_latest_screenshot(recovery_id, "after")

        ok = bool(
            execution.ok
            and (
                decision.expected_after_action is None
                or after.screen == decision.expected_after_action
                or execution.after_screen == decision.expected_after_action
                or execution.action_executed in {"none", "resume"}
            )
        )

        result = RecoveryRunResult(
            ok=ok,
            before=before,
            decision=decision,
            execution=execution,
            after=after,
            message=(
                f"Recovery executed: {execution.action_executed}. "
                f"before={before.screen}, after={after.screen}, ok={ok}."
            ),
        )
        report = self._write_report(recovery_id, result, before_snapshot, after_snapshot)
        return RecoveryRunResult(**{**result.__dict__, "report_path": report})

    def _execute_decision(
        self,
        decision: RecoveryDecision,
        *,
        before: ScreenClassificationResult,
        allow_forward_clicks: bool,
        reclassify_delay_seconds: float,
        current_level: int | None,
    ) -> RecoveryExecutionResult:
        action = decision.action

        if action in {"none", "resume", "stop"}:
            return RecoveryExecutionResult(
                ok=True,
                action_executed=action,
                decision=decision,
                before_screen=before.screen,
                after_screen=before.screen,
                message=f"No recovery movement needed for action={action}.",
            )

        if action in {"safe_return_to_level", "press_esc_once", "press_esc_twice_slowly"}:
            max_presses = max(1, min(3, int(decision.esc_presses or 1)))
            if action == "press_esc_once":
                max_presses = 1
            elif action == "press_esc_twice_slowly":
                max_presses = 2

            return self._safe_return_to_level(
                decision,
                before=before,
                max_presses=max_presses,
                delay_seconds=max(1.0, float(decision.delay_between_esc_seconds)),
            )

        if action == "click_take_reward":
            if not allow_forward_clicks:
                return RecoveryExecutionResult(
                    ok=False,
                    action_executed="blocked",
                    decision=decision,
                    before_screen=before.screen,
                    after_screen=before.screen,
                    message=(
                        "Forward recovery for Take Reward is blocked unless "
                        "allow_forward_clicks is enabled."
                    ),
                )
            return self._complete_from_take_reward(
                decision,
                before=before,
                current_level=current_level,
                timeout_seconds=8.0,
            )

        if action == "click_free":
            if not allow_forward_clicks:
                return RecoveryExecutionResult(
                    ok=False,
                    action_executed="blocked",
                    decision=decision,
                    before_screen=before.screen,
                    after_screen=before.screen,
                    message=(
                        "Forward recovery for Free is blocked unless "
                        "allow_forward_clicks is enabled."
                    ),
                )
            return self._complete_from_free(
                decision,
                before=before,
                current_level=current_level,
                timeout_seconds=8.0,
            )

        if action == "continue_reincarnation":
            self._tap_point("default_button")
            after = self._wait_for_screen("LEVEL_SCREEN", timeout_seconds=8.0)
            return RecoveryExecutionResult(
                ok=after is not None and after.screen == "LEVEL_SCREEN",
                action_executed="click:default_button",
                decision=decision,
                before_screen=before.screen,
                after_screen=after.screen if after is not None else None,
                message=(
                    "Clicked default_button to complete reincarnation recovery. "
                    f"after={after.screen if after is not None else 'timeout'}."
                ),
            )

        return RecoveryExecutionResult(
            ok=False,
            action_executed="unsupported",
            decision=decision,
            before_screen=before.screen,
            after_screen=before.screen,
            message=f"Recovery action {action!r} is not executable by RecoveryRunner.",
        )

    def _safe_return_to_level(
        self,
        decision: RecoveryDecision,
        *,
        before: ScreenClassificationResult,
        max_presses: int,
        delay_seconds: float,
    ) -> RecoveryExecutionResult:
        last_hash = self._latest_screenshot_hash()
        last_seen_screen = before.screen

        for press_index in range(1, max_presses + 1):
            self.adb.press_back()
            time.sleep(delay_seconds)
            after = self.classifier.classify()
            after_hash = self._latest_screenshot_hash()

            if after.screen == "LEVEL_SCREEN":
                return RecoveryExecutionResult(
                    ok=True,
                    action_executed=f"safe_return_esc_{press_index}",
                    decision=decision,
                    before_screen=before.screen,
                    after_screen=after.screen,
                    message=f"Reached LEVEL_SCREEN after {press_index} BACK/ESC press(es).",
                )

            if after.screen in {"TAKE_REWARD_SCREEN", "FREE_SCREEN"}:
                return RecoveryExecutionResult(
                    ok=False,
                    action_executed=f"safe_return_esc_{press_index}",
                    decision=decision,
                    before_screen=before.screen,
                    after_screen=after.screen,
                    message=(
                        f"Stopped safe return on {after.screen}; these screens must be "
                        "completed forward, not escaped."
                    ),
                )

            if after.screen == "UNKNOWN" and after_hash == last_hash:
                return RecoveryExecutionResult(
                    ok=False,
                    action_executed=f"safe_return_esc_{press_index}",
                    decision=decision,
                    before_screen=before.screen,
                    after_screen=after.screen,
                    message=(
                        "Stopped safe return because screen remained UNKNOWN and the "
                        "screenshot did not change."
                    ),
                )

            if press_index < max_presses:
                self._safe_irrelevant_tap()
                time.sleep(0.20)

            last_hash = after_hash
            last_seen_screen = after.screen

        return RecoveryExecutionResult(
            ok=False,
            action_executed=f"safe_return_esc_{max_presses}",
            decision=decision,
            before_screen=before.screen,
            after_screen=last_seen_screen,
            message=f"Safe return did not reach LEVEL_SCREEN after {max_presses} BACK/ESC press(es).",
        )

    def _complete_from_take_reward(
        self,
        decision: RecoveryDecision,
        *,
        before: ScreenClassificationResult,
        current_level: int | None,
        timeout_seconds: float,
    ) -> RecoveryExecutionResult:
        reward_target = self._choose_take_reward_point(before, current_level)
        self._tap_point(reward_target)

        free_screen = self._wait_for_screen("FREE_SCREEN", timeout_seconds=timeout_seconds)
        if free_screen is None:
            return RecoveryExecutionResult(
                ok=False,
                action_executed=f"click:{reward_target}",
                decision=decision,
                before_screen=before.screen,
                after_screen=None,
                message="Clicked Take Reward but FREE_SCREEN did not appear.",
            )

        free_target = self._choose_free_point(free_screen, current_level)
        self._tap_point(free_target)

        level_screen = self._wait_for_screen("LEVEL_SCREEN", timeout_seconds=timeout_seconds)
        return RecoveryExecutionResult(
            ok=level_screen is not None and level_screen.screen == "LEVEL_SCREEN",
            action_executed=f"click:{reward_target}->click:{free_target}",
            decision=decision,
            before_screen=before.screen,
            after_screen=level_screen.screen if level_screen is not None else None,
            message=(
                f"Completed forward recovery from TAKE_REWARD_SCREEN using {reward_target} "
                f"then {free_target}. after={level_screen.screen if level_screen is not None else 'timeout'}."
            ),
        )

    def _complete_from_free(
        self,
        decision: RecoveryDecision,
        *,
        before: ScreenClassificationResult,
        current_level: int | None,
        timeout_seconds: float,
    ) -> RecoveryExecutionResult:
        free_target = self._choose_free_point(before, current_level)
        self._tap_point(free_target)
        level_screen = self._wait_for_screen("LEVEL_SCREEN", timeout_seconds=timeout_seconds)

        return RecoveryExecutionResult(
            ok=level_screen is not None and level_screen.screen == "LEVEL_SCREEN",
            action_executed=f"click:{free_target}",
            decision=decision,
            before_screen=before.screen,
            after_screen=level_screen.screen if level_screen is not None else None,
            message=(
                f"Completed forward recovery from FREE_SCREEN using {free_target}. "
                f"after={level_screen.screen if level_screen is not None else 'timeout'}."
            ),
        )

    def _wait_for_screen(
        self,
        expected_screen: str,
        *,
        timeout_seconds: float,
        poll_interval_seconds: float = 0.25,
    ) -> ScreenClassificationResult | None:
        deadline = time.monotonic() + max(0.5, float(timeout_seconds))
        while time.monotonic() < deadline:
            result = self.classifier.classify()
            if result.screen == expected_screen:
                return result
            time.sleep(max(0.05, float(poll_interval_seconds)))
        return None

    def _tap_point(self, target_name: str) -> None:
        point = self.calibration.get_point(target_name)
        self.adb.tap(point.x, point.y)

    def _safe_irrelevant_tap(self) -> None:
        if self.calibration.has_point("recovery_safe_tap"):
            point = self.calibration.get_point("recovery_safe_tap")
            self.adb.tap(point.x, point.y)
            return

        # Fallback: a top-left tap that normally does not interact with CIC UI.
        # Calibrate recovery_safe_tap if this is not irrelevant for your layout.
        self.adb.tap(8, 8)

    def _choose_take_reward_point(self, before: ScreenClassificationResult, current_level: int | None) -> str:
        matched = before.matched_target or ""
        if current_level is not None and current_level <= 5 and self.calibration.has_point("early_reward_button"):
            return "early_reward_button"
        if matched.startswith("early_") and self.calibration.has_point("early_reward_button"):
            return "early_reward_button"
        if self.calibration.has_point("reward_button"):
            return "reward_button"
        return "early_reward_button"

    def _choose_free_point(self, before: ScreenClassificationResult, current_level: int | None) -> str:
        matched = before.matched_target or ""

        if "early_free_button_alt" in matched and self.calibration.has_point("early_free_button_alt"):
            return "early_free_button_alt"
        if "free_button_alt" in matched and self.calibration.has_point("free_button_alt"):
            return "free_button_alt"

        if current_level == 1 and self.calibration.has_point("early_free_button"):
            return "early_free_button"
        if "early_free" in matched and self.calibration.has_point("early_free_button"):
            return "early_free_button"
        if self.calibration.has_point("free_button"):
            return "free_button"
        if self.calibration.has_point("free_button_alt"):
            return "free_button_alt"
        return "early_free_button"

    def _latest_screenshot_hash(self) -> str:
        path = paths.LATEST_SCREENSHOT_PATH
        try:
            return hashlib.sha1(path.read_bytes()).hexdigest()
        except Exception:
            return ""

    def _copy_latest_screenshot(self, recovery_id: str, label: str) -> Path | None:
        source = paths.LATEST_SCREENSHOT_PATH
        if not source.exists():
            return None

        recovery_dir = paths.LOG_DIR / "recovery"
        recovery_dir.mkdir(parents=True, exist_ok=True)
        destination = recovery_dir / f"{recovery_id}_{label}.png"
        try:
            shutil.copy2(source, destination)
            return destination
        except Exception:
            return None

    def _write_report(
        self,
        recovery_id: str,
        result: RecoveryRunResult,
        before_snapshot: Path | None,
        after_snapshot: Path | None,
    ) -> Path | None:
        recovery_dir = paths.LOG_DIR / "recovery"
        recovery_dir.mkdir(parents=True, exist_ok=True)
        report_path = recovery_dir / f"{recovery_id}_report.txt"

        execution = result.execution
        after = result.after

        text = [
            f"recovery_id: {recovery_id}",
            f"ok: {result.ok}",
            f"before_screen: {result.before.screen}",
            f"before_confidence: {result.before.confidence}",
            f"before_target: {result.before.matched_target}",
            f"before_score: {result.before.score}",
            f"decision_action: {result.decision.action}",
            f"decision_risk: {result.decision.risk}",
            f"decision_reason: {result.decision.reason}",
            f"expected_after_action: {result.decision.expected_after_action}",
            f"execution_action: {execution.action_executed if execution else None}",
            f"execution_ok: {execution.ok if execution else None}",
            f"execution_message: {execution.message if execution else None}",
            f"after_screen: {after.screen if after else None}",
            f"after_confidence: {after.confidence if after else None}",
            f"after_target: {after.matched_target if after else None}",
            f"after_score: {after.score if after else None}",
            f"before_snapshot: {before_snapshot}",
            f"after_snapshot: {after_snapshot}",
            f"message: {result.message}",
            "",
        ]

        try:
            report_path.write_text("\n".join(text), encoding="utf-8")
            return report_path
        except Exception:
            return None
