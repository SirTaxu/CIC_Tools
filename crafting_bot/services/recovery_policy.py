from __future__ import annotations

from crafting_bot.domain.recovery import RecoveryDecision, RecoveryRequest


class RecoveryPolicy:
    """Decides what recovery action would be safe from a classified screen.

    This policy is dry-run/decision-only. It does not click, press ESC, or
    resume the bot. Recovery execution should be added only after these
    decisions are validated from real screenshots.
    """

    def decide(self, request: RecoveryRequest) -> RecoveryDecision:
        screen = request.screen
        context = request.context

        if screen == "LEVEL_SCREEN":
            return RecoveryDecision(
                action="resume",
                risk="safe",
                reason="Already back on the playable level screen.",
                expected_after_action="LEVEL_SCREEN",
            )

        if screen == "TAKE_REWARD_SCREEN":
            return RecoveryDecision(
                action="click_take_reward",
                risk="guarded",
                reason="Take Reward does not close with ESC. Recovery should move forward by clicking the calibrated Take Reward button.",
                expected_after_action="FREE_SCREEN",
                never_use_esc=True,
            )

        if screen == "FREE_SCREEN":
            return RecoveryDecision(
                action="click_free",
                risk="guarded",
                reason="Free screen does not close with ESC. Recovery should move forward by clicking the calibrated Free button.",
                expected_after_action="LEVEL_SCREEN",
                never_use_esc=True,
            )

        if screen == "REBUILD_WORKSHOP":
            if context == "rebuild":
                return RecoveryDecision(
                    action="continue_rebuild",
                    risk="guarded",
                    reason="Still in the rebuild flow. Recovery can continue by finding/clicking the dynamic Rebuild now button.",
                    expected_after_action="TAKE_REWARD_SCREEN",
                )

            return RecoveryDecision(
                action="press_esc_twice_slowly",
                risk="guarded",
                reason=(
                    "Unexpected Rebuild Workshop outside rebuild context. The first ESC/BACK returns to MAP_SCREEN, "
                    "and a second slow ESC/BACK returns to LEVEL_SCREEN."
                ),
                expected_after_action="LEVEL_SCREEN",
                esc_presses=2,
                delay_between_esc_seconds=1.0,
            )

        if screen == "MAP_SCREEN":
            return RecoveryDecision(
                action="press_esc_once",
                risk="safe",
                reason="Map screen likely came from a missed/open-level click. One ESC should return to the level screen.",
                expected_after_action="LEVEL_SCREEN",
                esc_presses=1,
            )

        if screen in {"HEADQUARTERS_SCREEN", "DYNASTY_SCREEN"}:
            return RecoveryDecision(
                action="press_esc_once",
                risk="safe",
                reason=f"{screen} is a regular menu. One ESC should return toward the level screen.",
                expected_after_action="LEVEL_SCREEN",
                esc_presses=1,
            )

        if screen == "REINCARNATION_CONFIRM_SCREEN":
            if context == "reincarnation":
                return RecoveryDecision(
                    action="continue_reincarnation",
                    risk="guarded",
                    reason="The bot is intentionally in the reincarnation flow. Continue with the calibrated Default button.",
                    expected_after_action="LEVEL_SCREEN",
                )

            return RecoveryDecision(
                action="press_esc_twice_slowly",
                risk="guarded",
                reason="Unexpected reincarnation confirmation screen. It may require two ESC presses, with a 1-second delay, to avoid closing the game accidentally.",
                expected_after_action="LEVEL_SCREEN",
                esc_presses=2,
                delay_between_esc_seconds=1.0,
            )

        return RecoveryDecision(
            action="press_esc_once",
            risk="guarded",
            reason=(
                "Current screen is UNKNOWN. Dry-run recommendation is one ESC, then reclassify. "
                "A second ESC should only be considered if the new screenshot is still UNKNOWN and different from the previous screenshot."
            ),
            expected_after_action="LEVEL_SCREEN",
            esc_presses=1,
        )
