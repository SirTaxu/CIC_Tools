from __future__ import annotations

from crafting_bot.factory import build_calibration_store, build_level_scanner
from crafting_bot.services.screen_classifier import ScreenClassifier


def main() -> None:
    classifier = ScreenClassifier(
        calibration=build_calibration_store(),
        scanner=build_level_scanner(),
    )
    result = classifier.classify()

    print(f"ok: {result.ok}")
    print(f"screen: {result.screen}")
    print(f"confidence: {result.confidence}")
    print(f"matched_target: {result.matched_target}")
    print(f"score: {result.score}")
    print(f"threshold: {result.threshold}")
    print(f"level_text: {result.level_text}")
    print(f"level: {result.level}")
    print(f"ready: {result.ready}")
    print(f"ready_score: {result.ready_score}")
    print(f"digit_score: {result.digit_score}")
    print(f"screenshot_path: {result.screenshot_path}")
    print(f"message: {result.message}")

    print("\nCandidates")
    print("-" * 80)
    for candidate in sorted(result.candidates, key=lambda item: (not item.passed, item.screen, item.target_name)):
        score = "none" if candidate.score is None else f"{candidate.score:.4f}"
        threshold = "none" if candidate.threshold is None else f"{candidate.threshold:.4f}"
        attempted = "yes" if candidate.attempted else "no"
        passed = "yes" if candidate.passed else "no"
        print(
            f"{candidate.screen:30} {candidate.target_name:35} "
            f"attempted={attempted:3} passed={passed:3} score={score:>7} threshold={threshold:>7}"
        )
        if candidate.message:
            print(f"    {candidate.message}")


if __name__ == "__main__":
    main()
