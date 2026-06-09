from __future__ import annotations

import argparse

from crafting_bot.factory import build_calibration_store, build_level_scanner
from crafting_bot.services.recovery_dry_run_service import RecoveryDryRunService
from crafting_bot.services.screen_classifier import ScreenClassifier


VALID_CONTEXTS = ("general", "rebuild", "hire", "reincarnation", "waiting_for_level", "unknown")


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify current screen and show recovery recommendation. No clicks.")
    parser.add_argument(
        "--context",
        choices=VALID_CONTEXTS,
        default="general",
        help="What the bot was trying to do when recovery is requested.",
    )
    args = parser.parse_args()

    classifier = ScreenClassifier(
        calibration=build_calibration_store(),
        scanner=build_level_scanner(),
    )
    service = RecoveryDryRunService(classifier=classifier)
    result = service.run(context=args.context)

    classification = result.classification
    decision = result.decision

    print(f"ok: {result.ok}")
    print(f"classified_screen: {classification.screen}")
    print(f"classification_confidence: {classification.confidence}")
    print(f"matched_target: {classification.matched_target}")
    print(f"classification_score: {classification.score}")
    print(f"classification_threshold: {classification.threshold}")
    print(f"level_text: {classification.level_text}")
    print(f"level: {classification.level}")
    print(f"ready: {classification.ready}")
    print(f"screenshot_path: {classification.screenshot_path}")
    print(f"context: {args.context}")
    print(f"suggested_action: {decision.action}")
    print(f"risk: {decision.risk}")
    print(f"expected_after_action: {decision.expected_after_action}")
    print(f"esc_presses: {decision.esc_presses}")
    print(f"delay_between_esc_seconds: {decision.delay_between_esc_seconds}")
    print(f"never_use_esc: {'yes' if decision.never_use_esc else 'no'}")
    print(f"dry_run_only: {'yes' if decision.dry_run_only else 'no'}")
    print(f"reason: {decision.reason}")
    print(f"message: {result.message}")

    print("\nClassifier candidates")
    print("-" * 80)
    for candidate in sorted(classification.candidates, key=lambda item: (not item.passed, item.screen, item.target_name)):
        score = "none" if candidate.score is None else f"{candidate.score:.4f}"
        threshold = "none" if candidate.threshold is None else f"{candidate.threshold:.4f}"
        attempted = "yes" if candidate.attempted else "no"
        passed = "yes" if candidate.passed else "no"
        print(
            f"{candidate.screen:30} {candidate.target_name:40} "
            f"attempted={attempted:3} passed={passed:3} score={score:>7} threshold={threshold:>7}"
        )
        if candidate.message:
            print(f"    {candidate.message}")


if __name__ == "__main__":
    main()
