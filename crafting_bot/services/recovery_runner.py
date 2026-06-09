from __future__ import annotations

import time
from dataclasses import dataclass

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


class RecoveryRunner:
    """Executes one bounded recovery action from the current screen.

    This runner is intentionally conservative:
    - ESC/BACK recovery is enabled.
    - Take Reward / Free forward-click recovery is blocked unless explicitly
      allowed, because those buttons can have phase-specific positions.
    - It never loops indefinitely.
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
    ) -> RecoveryRunResult:
        before = self.classifier.classify()
        decision = self.policy.decide(RecoveryRequest(screen=before.screen, context=context))

        if not execute:
            return RecoveryRunResult(
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

        execution = self._execute_decision(
            decision,
            before=before,
            allow_forward_clicks=allow_forward_clicks,
            reclassify_delay_seconds=reclassify_delay_seconds,
        )
        after = self.classifier.classify()

        ok = execution.ok and (
            decision.expected_after_action is None
            or after.screen == decision.expected_after_action
            or execution.action_executed in {"none", "resume", "blocked"}
        )

        return RecoveryRunResult(
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

    def _execute_decision(
        self,
        decision: RecoveryDecision,
        *,
        before: ScreenClassificationResult,
        allow_forward_clicks: bool,
        reclassify_delay_seconds: float,
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

        if action == "press_esc_once":
            self.adb.press_back()
            time.sleep(max(0.1, float(reclassify_delay_seconds)))
            after = self.classifier.classify()
            return RecoveryExecutionResult(
                ok=True,
                action_executed="press_esc_once",
                decision=decision,
                before_screen=before.screen,
                after_screen=after.screen,
                message=f"Pressed BACK/ESC once. after={after.screen}.",
            )

        if action == "press_esc_twice_slowly":
            self.adb.press_back()
            time.sleep(max(1.0, float(decision.delay_between_esc_seconds)))
            after_first = self.classifier.classify()

            if after_first.screen == "LEVEL_SCREEN":
                return RecoveryExecutionResult(
                    ok=True,
                    action_executed="press_esc_once_of_two",
                    decision=decision,
                    before_screen=before.screen,
                    after_screen=after_first.screen,
                    message="Pressed BACK/ESC once and reached LEVEL_SCREEN; skipped second ESC.",
                )

            if after_first.screen in {"TAKE_REWARD_SCREEN", "FREE_SCREEN"}:
                return RecoveryExecutionResult(
                    ok=False,
                    action_executed="press_esc_once_of_two",
                    decision=decision,
                    before_screen=before.screen,
                    after_screen=after_first.screen,
                    message=(
                        f"Pressed one ESC but landed on {after_first.screen}; refusing second ESC "
                        "because Take Reward and Free screens should not be closed with ESC."
                    ),
                )

            self.adb.press_back()
            time.sleep(max(1.0, float(decision.delay_between_esc_seconds)))
            after_second = self.classifier.classify()
            return RecoveryExecutionResult(
                ok=True,
                action_executed="press_esc_twice_slowly",
                decision=decision,
                before_screen=before.screen,
                after_screen=after_second.screen,
                message=f"Pressed BACK/ESC twice slowly. after={after_second.screen}.",
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
                        "Forward-click recovery for Take Reward is blocked unless "
                        "allow_forward_clicks is enabled."
                    ),
                )
            target = self._choose_take_reward_point(before)
            self._tap_point(target)
            time.sleep(max(0.1, float(reclassify_delay_seconds)))
            after = self.classifier.classify()
            return RecoveryExecutionResult(
                ok=True,
                action_executed=f"click:{target}",
                decision=decision,
                before_screen=before.screen,
                after_screen=after.screen,
                message=f"Clicked {target}. after={after.screen}.",
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
                        "Forward-click recovery for Free is blocked unless "
                        "allow_forward_clicks is enabled."
                    ),
                )
            target = self._choose_free_point(before)
            self._tap_point(target)
            time.sleep(max(0.1, float(reclassify_delay_seconds)))
            after = self.classifier.classify()
            return RecoveryExecutionResult(
                ok=True,
                action_executed=f"click:{target}",
                decision=decision,
                before_screen=before.screen,
                after_screen=after.screen,
                message=f"Clicked {target}. after={after.screen}.",
            )

        return RecoveryExecutionResult(
            ok=False,
            action_executed="unsupported",
            decision=decision,
            before_screen=before.screen,
            after_screen=before.screen,
            message=f"Recovery action {action!r} is not executable by RecoveryRunner yet.",
        )

    def _tap_point(self, target_name: str) -> None:
        point = self.calibration.get_point(target_name)
        self.adb.tap(point.x, point.y)

    def _choose_take_reward_point(self, before: ScreenClassificationResult) -> str:
        matched = before.matched_target or ""
        if matched.startswith("early_") and self.calibration.has_point("early_reward_button"):
            return "early_reward_button"
        if self.calibration.has_point("reward_button"):
            return "reward_button"
        return "early_reward_button"

    def _choose_free_point(self, before: ScreenClassificationResult) -> str:
        matched = before.matched_target or ""
        if "early_free" in matched and self.calibration.has_point("early_free_button"):
            return "early_free_button"
        if "free_button_alt" in matched and self.calibration.has_point("free_button_alt"):
            return "free_button_alt"
        if self.calibration.has_point("free_button"):
            return "free_button"
        return "early_free_button"
