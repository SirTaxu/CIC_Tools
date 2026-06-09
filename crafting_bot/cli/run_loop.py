from __future__ import annotations

import argparse

from crafting_bot.application.settings import RebuildLoopSettings
from crafting_bot.factory import build_bot_controller


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a small unattended rebuild loop. Dry-run by default.")
    parser.add_argument("--click", action="store_true", help="Actually send ADB taps. Omit this for dry-run mode.")
    parser.add_argument("--max-cycles", type=int, default=3, help="Safety cap on successful rebuild cycles before stopping.")
    parser.add_argument("--desired-level", type=int, default=None, help="Visible level to stop at, or completed level before reincarnation when --reincarnate is used.")
    parser.add_argument("--reincarnate", action="store_true", help="When --desired-level is set, reincarnate after completing that level and continue looping.")
    parser.add_argument("--hire", action="store_true", help="Run the hire/setup cycle once per climb after the setup level is reached.")
    parser.add_argument("--hire-level", type=int, default=45, help="Visible level where the hire/setup cycle may run once per climb. Default: 45.")
    parser.add_argument("--hire-drag-duration-ms", type=int, default=750, help="ADB swipe duration for hire/setup drags. Default: 750.")
    parser.add_argument("--stuck-seconds", type=float, default=20.0, help="Force a rebuild if the same visible level remains this long.")
    parser.add_argument("--scan-interval", type=float, default=1.0, help="Seconds between scans while waiting.")
    parser.add_argument("--max-runtime", type=float, default=None, help="Optional maximum runtime in seconds.")
    parser.add_argument("--stop-at-level", type=int, default=None, help="Stop before cycling if the scanned level is at least this value.")
    parser.add_argument("--step-delay", type=float, default=0.20, help="Small delay after each click before polling starts.")
    parser.add_argument("--wait-timeout", type=float, default=8.0, help="Maximum seconds to wait for each expected screen/target.")
    parser.add_argument("--poll", type=float, default=0.25, help="Seconds between verification/search attempts while waiting.")
    parser.add_argument("--min-digit-score", type=float, default=0.50, help="Minimum digit confidence required before click mode is allowed.")
    parser.add_argument("--allow-low-confidence-level", action="store_true", help="Allow click mode even when digit confidence is low. Not recommended.")
    parser.add_argument("--continue-on-scan-failure", action="store_true", help="Keep trying after a scan failure instead of stopping.")
    parser.add_argument("--continue-on-cycle-failure", action="store_true", help="Keep trying after a cycle failure instead of stopping. Not recommended.")
    parser.add_argument("--max-iterations", type=int, default=500, help="Safety cap on total scan/decision iterations.")
    parser.add_argument(
        "--assist-digit-training",
        action="store_true",
        help=(
            "When level digits are unknown, ask before training from the saved failed crop if the previous two "
            "confirmed levels and ready template identify the next level."
        ),
    )
    parser.add_argument(
        "--auto-train-missing-digits",
        action="store_true",
        help=(
            "Like --assist-digit-training, but trains without asking. Use only after the assisted behavior is proven."
        ),
    )
    parser.add_argument(
        "--auto-train-template-score",
        type=float,
        default=0.16,
        help="Maximum ready-template score allowed for loop-assisted digit training. Lower is stricter. Default: 0.16.",
    )
    args = parser.parse_args()

    mode = "click" if args.click else "dry_run"
    try:
        controller = build_bot_controller()
        settings = RebuildLoopSettings(
            mode=mode,
            max_cycles=args.max_cycles,
            desired_level=args.desired_level,
            reincarnation_enabled=args.reincarnate,
            hire_enabled=args.hire,
            hire_setup_level=args.hire_level,
            hire_drag_duration_ms=args.hire_drag_duration_ms,
            stuck_seconds=args.stuck_seconds,
            scan_interval_seconds=args.scan_interval,
            max_runtime_seconds=args.max_runtime,
            stop_at_level=args.stop_at_level,
            step_delay_seconds=args.step_delay,
            wait_timeout_seconds=args.wait_timeout,
            poll_interval_seconds=args.poll,
            min_digit_score_for_click=args.min_digit_score,
            allow_low_confidence_level=args.allow_low_confidence_level,
            stop_on_scan_failure=not args.continue_on_scan_failure,
            stop_on_cycle_failure=not args.continue_on_cycle_failure,
            max_iterations=args.max_iterations,
            assist_digit_training=args.assist_digit_training,
            auto_train_missing_digits=args.auto_train_missing_digits,
            auto_train_ready_template_max_score=args.auto_train_template_score,
        )
        result = controller.run_rebuild_loop(settings)
    except Exception as exc:
        print("ok: False")
        print(f"message: {exc}")
        return 1

    print("ok: True")
    print("Run rebuild loop")
    print("=" * 120)
    print(f"mode: {result.mode}")
    print("clicks_sent: " + ("yes" if result.mode == "click" else "no"))
    print(f"max_cycles: {result.max_cycles}")
    print(f"cycles_completed: {result.cycles_completed}")
    if args.desired_level is not None:
        print(f"desired_level: {args.desired_level}")
        print(f"reincarnation_enabled: {'yes' if args.reincarnate else 'no'}")
        if args.reincarnate:
            print(f"reincarnation_trigger_visible_level: {args.desired_level + 1}")
    print(f"hire_enabled: {'yes' if args.hire else 'no'}")
    if args.hire:
        print(f"hire_setup_level: {args.hire_level}")
        print(f"hire_drag_duration_ms: {args.hire_drag_duration_ms}")
    print(f"runtime_seconds: {result.runtime_seconds:.2f}")
    print(f"stopped_reason: {result.stopped_reason}")
    print(f"stuck_seconds: {args.stuck_seconds}")
    print(f"scan_interval_seconds: {args.scan_interval}")
    print(f"wait_timeout_seconds: {args.wait_timeout}")
    print(f"poll_interval_seconds: {args.poll}")
    print(f"min_digit_score_for_click: {args.min_digit_score}")
    print(f"assist_digit_training: {'yes' if args.assist_digit_training else 'no'}")
    print(f"auto_train_missing_digits: {'yes' if args.auto_train_missing_digits else 'no'}")
    print(f"auto_train_template_score: {args.auto_train_template_score}")
    if args.stop_at_level is not None:
        print(f"stop_at_level: {args.stop_at_level}")
    print("-" * 120)

    for iteration in result.iterations:
        scan = iteration.scan
        print(f"iteration {iteration.index}")
        print(f"   action: {iteration.action}")
        print(f"   trigger_reason: {iteration.trigger_reason}")
        print(f"   same_level_seconds: {iteration.same_level_seconds:.2f}")
        print(f"   scan_ok: {scan.ok}")
        print(f"   scan_level_text: {scan.level_text}")
        print(f"   scan_level: {scan.level}")
        print(f"   scan_ready: {scan.ready}")
        print(f"   scan_ready_score: {scan.ready_score}")
        print(f"   scan_ready_template: {scan.ready_template}")
        print(f"   scan_digit_score: {scan.digit_score}")
        diagnostics = getattr(scan, "digit_diagnostics", None)
        if diagnostics:
            print(f"   scan_digit_diagnostics: {diagnostics}")
        print(f"   message: {iteration.message}")

        cycle = iteration.cycle_result
        if cycle is not None:
            print(f"   selected_cycle: {cycle.cycle.name if cycle.cycle else None}")
            print(f"   cycle_eligible: {cycle.eligible}")
            print(f"   cycle_trigger_reason: {cycle.trigger_reason}")
            print(f"   cycle_message: {cycle.message}")
            for step in cycle.steps:
                print(f"      step {step.definition.order}: {step.definition.action} -> {step.outcome}")
                if step.click_x is not None and step.click_y is not None:
                    print(f"         click: x={step.click_x}, y={step.click_y}")
                if step.search_score is not None:
                    print(f"         search_score: {step.search_score}")
                    print(f"         search_accepted: {step.search_accepted}")
                if step.verification is not None:
                    print(f"         verification_passed: {step.verification.passed}")
                    if step.verification.score is not None:
                        print(f"         verification_score: {step.verification.score}")
                    print(f"         verification_message: {step.verification.message}")
                print(f"         step_message: {step.message}")
        print("-" * 120)

    print(f"message: {result.message}")
    if result.mode == "click":
        print("safety: This loop stops at --max-cycles or another stop condition. Start with --max-cycles 3.")
    else:
        print("safety: Dry-run does not send clicks and stops after one planned cycle because the game cannot advance.")
    return 0 if result.stopped_reason in {"max_cycles_reached", "dry_run_planned_one_cycle", "stop_at_level_reached", "desired_level_reached"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
