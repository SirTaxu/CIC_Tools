from __future__ import annotations

import argparse

from crafting_bot.factory import build_adb_client, build_calibration_store, build_screen_waiter
from crafting_bot.services.hire_dry_run_service import HireDryRunService
from crafting_bot.services.hire_runner import HireRunner


def build_hire_runner() -> HireRunner:
    return HireRunner(
        adb=build_adb_client(),
        calibration=build_calibration_store(),
        waiter=build_screen_waiter(),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run or dry-run the hire/setup cycle.")
    parser.add_argument("--click", action="store_true", help="Actually send ADB taps/drags. Omit for dry-run mode.")
    parser.add_argument(
        "--setup-level",
        type=int,
        default=45,
        help="Documentation value: level threshold where hire/setup should run. This command still runs only once.",
    )
    parser.add_argument("--drag-duration-ms", type=int, default=750, help="ADB swipe duration for Research and Auto-Sale drags.")
    parser.add_argument("--step-delay", type=float, default=0.20, help="Small delay after each action before polling starts.")
    parser.add_argument("--wait-timeout", type=float, default=8.0, help="Maximum seconds to wait for each expected screen.")
    parser.add_argument("--poll", type=float, default=0.25, help="Seconds between verification attempts.")
    args = parser.parse_args()

    mode = "click" if args.click else "dry_run"

    try:
        if args.click:
            result = build_hire_runner().run_once(
                mode="click",
                setup_level=args.setup_level,
                drag_duration_ms=args.drag_duration_ms,
                step_delay_seconds=args.step_delay,
                wait_timeout_seconds=args.wait_timeout,
                poll_interval_seconds=args.poll,
            )
            ready = result.eligible and bool(result.steps) and all(step.outcome == "success" for step in result.steps)
        else:
            store = build_calibration_store()
            result = HireDryRunService(store).inspect(setup_level=args.setup_level)
            ready = result.ready
    except Exception as exc:
        print("ok: False")
        print(f"message: {exc}")
        return 1

    print("ok: True")
    print("Run hire/setup once")
    print("=" * 120)
    print(f"mode: {mode}")
    print("inputs_sent: " + ("yes" if args.click else "no"))
    print(f"setup_level: {args.setup_level}")
    print(f"ready: {'yes' if ready else 'no'}")
    if args.click:
        print(f"drag_duration_ms: {args.drag_duration_ms}")
        print(f"step_delay_seconds: {args.step_delay}")
        print(f"wait_timeout_seconds: {args.wait_timeout}")
        print(f"poll_interval_seconds: {args.poll}")
    print("-" * 120)

    if args.click:
        for step in result.steps:
            definition = step.definition
            print(f"{definition.order}. {definition.action}")
            print(f"   mode: {definition.mode}")
            print(f"   target: {definition.target_name}")
            print(f"   outcome: {step.outcome}")
            if step.click_x is not None and step.click_y is not None:
                if definition.mode == "drag":
                    print(f"   drag_start: x={step.click_x}, y={step.click_y}")
                else:
                    print(f"   click: x={step.click_x}, y={step.click_y}")
            if definition.mode == "drag":
                print(f"   drag_end: {step.drag_end_used}")
                if step.drag_end_x is not None and step.drag_end_y is not None:
                    print(f"   drag_end_point: x={step.drag_end_x}, y={step.drag_end_y}")
                print(f"   drag_duration_ms: {step.drag_duration_ms}")
            if definition.verification_target:
                print(f"   verify: {definition.verification_target}")
                if step.verification is not None:
                    print(f"   verification_passed: {step.verification.passed}")
                    if step.verification.score is not None:
                        print(f"   verification_score: {step.verification.score}")
                    print(f"   verification_message: {step.verification.message}")
            print(f"   message: {step.message}")
            if definition.notes:
                print(f"   notes: {definition.notes}")
            print()
    else:
        for step in result.steps:
            print(f"{step.order}. {step.action}")
            print(f"   mode: {step.mode}")
            print(f"   target: {step.target_name}")
            print(f"   target_status: {step.target_status}")
            if step.drag_end_target_name:
                print(f"   drag_end: {step.drag_end_target_name}")
                print(f"   drag_end_status: {step.drag_end_status}")
            if step.verification_target:
                print(f"   verify: {step.verification_target}")
                print(f"   verification_status: {step.verification_status}")
            print(f"   ready: {'yes' if step.ready else 'no'}")
            if step.notes:
                print(f"   notes: {step.notes}")
            print()

    print("-" * 120)
    print(f"message: {result.message}")
    if args.click:
        print("safety: This command runs one hire/setup sequence only. It is not integrated into the rebuild loop yet.")
    else:
        print("safety: Dry-run only. It does not send ADB taps or drags.")
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
