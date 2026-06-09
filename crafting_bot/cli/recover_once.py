from __future__ import annotations

import argparse

from crafting_bot.factory import build_adb_client, build_calibration_store, build_level_scanner
from crafting_bot.services.recovery_policy import RecoveryPolicy
from crafting_bot.services.recovery_runner import RecoveryRunner
from crafting_bot.services.screen_classifier import ScreenClassifier


VALID_CONTEXTS = ("general", "rebuild", "hire", "reincarnation", "waiting_for_level", "unknown")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one bounded recovery action from the current screen.")
    parser.add_argument("--context", choices=VALID_CONTEXTS, default="general")
    parser.add_argument(
        "--click",
        action="store_true",
        help="Execute the recommended recovery action. Without this, it is dry-run only.",
    )
    parser.add_argument(
        "--allow-forward-clicks",
        action="store_true",
        help="Allow Take Reward / Free forward-click recovery. ESC/BACK actions do not need this.",
    )
    args = parser.parse_args()

    calibration = build_calibration_store()
    classifier = ScreenClassifier(
        calibration=calibration,
        scanner=build_level_scanner(),
    )
    runner = RecoveryRunner(
        classifier=classifier,
        adb=build_adb_client(),
        calibration=calibration,
        policy=RecoveryPolicy(),
    )

    result = runner.run(
        context=args.context,
        execute=args.click,
        allow_forward_clicks=args.allow_forward_clicks,
    )

    before = result.before
    decision = result.decision
    after = result.after
    execution = result.execution

    print(f"ok: {result.ok}")
    print(f"mode: {'click' if args.click else 'dry_run'}")
    print(f"context: {args.context}")
    print(f"before_screen: {before.screen}")
    print(f"before_confidence: {before.confidence}")
    print(f"before_matched_target: {before.matched_target}")
    print(f"before_score: {before.score}")
    print(f"suggested_action: {decision.action}")
    print(f"risk: {decision.risk}")
    print(f"expected_after_action: {decision.expected_after_action}")
    print(f"esc_presses: {decision.esc_presses}")
    print(f"never_use_esc: {'yes' if decision.never_use_esc else 'no'}")
    print(f"reason: {decision.reason}")

    if execution is not None:
        print(f"action_executed: {execution.action_executed}")
        print(f"execution_ok: {execution.ok}")
        print(f"execution_message: {execution.message}")

    if after is not None:
        print(f"after_screen: {after.screen}")
        print(f"after_confidence: {after.confidence}")
        print(f"after_matched_target: {after.matched_target}")
        print(f"after_score: {after.score}")

    print(f"message: {result.message}")


if __name__ == "__main__":
    main()
