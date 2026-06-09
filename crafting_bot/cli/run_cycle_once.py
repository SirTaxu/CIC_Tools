from __future__ import annotations

import argparse

from crafting_bot.factory import build_cycle_runner


def main() -> int:
    parser = argparse.ArgumentParser(description="Run exactly one selected rebuild cycle, dry-run by default.")
    parser.add_argument("--click", action="store_true", help="Actually send ADB taps. Omit this for dry-run mode.")
    parser.add_argument("--force", action="store_true", help="Run even if the scanned level is not ready. Use only for manual testing.")
    parser.add_argument("--level", type=int, default=None, help="Override the scanned level for cycle-selection testing.")
    parser.add_argument("--step-delay", type=float, default=0.20, help="Small delay after each click before polling starts.")
    parser.add_argument("--wait-timeout", type=float, default=8.0, help="Maximum seconds to wait for the expected next screen/target.")
    parser.add_argument("--poll", type=float, default=0.25, help="Seconds between verification/search attempts while waiting.")
    parser.add_argument("--continue-on-failure", action="store_true", help="Do not stop after the first failed step. Not recommended in click mode.")
    parser.add_argument("--min-digit-score", type=float, default=0.50, help="Minimum digit confidence required before click mode is allowed without --level.")
    parser.add_argument("--allow-low-confidence-level", action="store_true", help="Allow click mode even when digit confidence is low. Use only for manual debugging.")
    args = parser.parse_args()

    mode = "click" if args.click else "dry_run"
    service = build_cycle_runner()
    try:
        result = service.run_once(
            mode=mode,
            force=args.force,
            level_override=args.level,
            step_delay_seconds=args.step_delay,
            wait_timeout_seconds=args.wait_timeout,
            poll_interval_seconds=args.poll,
            stop_on_failure=not args.continue_on_failure,
            min_digit_score_for_click=args.min_digit_score,
            allow_low_confidence_level=args.allow_low_confidence_level,
        )
    except Exception as exc:
        print("ok: False")
        print(f"message: {exc}")
        return 1

    print("ok: True")
    print("Run cycle once")
    print("=" * 120)
    print(f"mode: {result.mode}")
    print("clicks_sent: " + ("yes" if result.mode == "click" else "no"))
    print(f"scan_ok: {result.scan.ok}")
    print(f"scan_screen: {result.scan.screen}")
    print(f"scan_level_text: {result.scan.level_text}")
    print(f"scan_level: {result.scan.level}")
    print(f"scan_ready: {result.scan.ready}")
    print(f"scan_ready_score: {result.scan.ready_score}")
    print(f"scan_digit_score: {result.scan.digit_score}")
    print(f"scan_digit_diagnostics: {result.scan.digit_diagnostics}")
    print(f"scan_message: {result.scan.message}")
    if args.level is not None:
        print(f"level_override: {args.level}")
    print(f"eligible: {result.eligible}")
    print(f"trigger_reason: {result.trigger_reason}")
    print(f"step_delay_seconds: {args.step_delay}")
    print(f"wait_timeout_seconds: {args.wait_timeout}")
    print(f"poll_interval_seconds: {args.poll}")
    print(f"min_digit_score_for_click: {args.min_digit_score}")
    print("allow_low_confidence_level: " + ("yes" if args.allow_low_confidence_level else "no"))

    if result.cycle is None:
        print(f"message: {result.message}")
        return 1

    print(f"selected_cycle: {result.cycle.name}")
    print(f"levels: {result.cycle.level_range}")
    print(f"cycle_status: {result.cycle.status}")
    print("-" * 120)

    for step in result.steps:
        definition = step.definition
        print(f"{definition.order}. {definition.action}")
        print(f"   outcome: {step.outcome}")
        print(f"   mode: {definition.mode}")
        print(f"   target: {definition.target_name}")
        if step.click_x is not None and step.click_y is not None:
            print(f"   click: x={step.click_x}, y={step.click_y}")
        if step.search_score is not None:
            print(f"   search_score: {step.search_score}")
            print(f"   search_accepted: {step.search_accepted}")
        if step.preview_path is not None:
            print(f"   preview_path: {step.preview_path}")
        if definition.verification_target:
            print(f"   verify: {definition.verification_target}")
        if step.verification is not None:
            verification = step.verification
            print(f"   verification_attempted: {verification.attempted}")
            print(f"   verification_passed: {verification.passed}")
            if verification.score is not None:
                print(f"   verification_score: {verification.score}")
            if verification.threshold is not None:
                print(f"   verification_threshold: {verification.threshold}")
            if verification.preview_path is not None:
                print(f"   verification_preview: {verification.preview_path}")
            print(f"   verification_message: {verification.message}")
        print(f"   message: {step.message}")
        if definition.notes:
            print(f"   notes: {definition.notes}")

    print("-" * 120)
    print(f"message: {result.message}")
    if result.mode == "click":
        print("safety: This command runs one cycle only. It does not start the unattended loop.")
    else:
        print("safety: Dry-run mode did not send clicks. Add --click only after reviewing the plan.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
