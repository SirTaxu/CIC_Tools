from __future__ import annotations

from crafting_bot.domain.recovery import RecoveryDecision, RecoveryRequest


class RecoveryPolicy:
    """Decides the safest bounded recovery action from a classified screen.

    The policy is context-aware. It allows forward recovery from Take Reward /
    Free only because those screens cannot be escaped safely; the bot must finish
    the rebuild cycle from there. Other unexpected screens are returned to the
    level screen with slow BACK/ESC recovery.
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
                reason=(
                    "Take Reward does not close with ESC. The only safe recovery is to finish "
                    "the rebuild phase: click Take Reward, then Free, then return to LEVEL_SCREEN."
                ),
                expected_after_action="LEVEL_SCREEN",
                never_use_esc=True,
            )

        if screen == "FREE_SCREEN":
            return RecoveryDecision(
                action="click_free",
                risk="guarded",
                reason=(
                    "Free screen does not close with ESC. The only safe recovery is to click "
                    "Free and return to LEVEL_SCREEN."
                ),
                expected_after_action="LEVEL_SCREEN",
                never_use_esc=True,
            )

        if screen == "REINCARNATION_CONFIRM_SCREEN" and context == "reincarnation":
            return RecoveryDecision(
                action="continue_reincarnation",
                risk="guarded",
                reason=(
                    "The bot is intentionally in the reincarnation flow. Continue by clicking "
                    "the calibrated Default button and verify LEVEL_SCREEN."
                ),
                expected_after_action="LEVEL_SCREEN",
                never_use_esc=True,
            )

        if screen == "REINCARNATION_CONFIRM_SCREEN":
            return RecoveryDecision(
                action="safe_return_to_level",
                risk="guarded",
                reason=(
                    "Unexpected reincarnation confirmation screen. Return with slow BACK/ESC "
                    "recovery. This can require two presses, so use safe taps and delays."
                ),
                expected_after_action="LEVEL_SCREEN",
                esc_presses=3,
                delay_between_esc_seconds=1.0,
            )

        if screen == "REBUILD_WORKSHOP":
            return RecoveryDecision(
                action="safe_return_to_level",
                risk="guarded",
                reason=(
                    "Unexpected Rebuild Workshop. Return to LEVEL_SCREEN instead of continuing "
                    "with possibly tainted cycle state. This may pass through MAP_SCREEN."
                ),
                expected_after_action="LEVEL_SCREEN",
                esc_presses=3,
                delay_between_esc_seconds=1.0,
            )

        if screen == "MAP_SCREEN":
            return RecoveryDecision(
                action="safe_return_to_level",
                risk="safe",
                reason="Map screen likely came from a missed/open-level click. Return to LEVEL_SCREEN with BACK/ESC.",
                expected_after_action="LEVEL_SCREEN",
                esc_presses=3,
                delay_between_esc_seconds=1.0,
            )

        if screen in {"HEADQUARTERS_SCREEN", "DYNASTY_SCREEN"}:
            return RecoveryDecision(
                action="safe_return_to_level",
                risk="safe",
                reason=f"{screen} is a regular menu. Return to LEVEL_SCREEN with slow BACK/ESC recovery.",
                expected_after_action="LEVEL_SCREEN",
                esc_presses=3,
                delay_between_esc_seconds=1.0,
            )

        return RecoveryDecision(
            action="safe_return_to_level",
            risk="guarded",
            reason=(
                "Current screen is UNKNOWN. Try slow BACK/ESC recovery up to three presses. "
                "Stop if the screenshot stays UNKNOWN and unchanged."
            ),
            expected_after_action="LEVEL_SCREEN",
            esc_presses=3,
            delay_between_esc_seconds=1.0,
        )
