from __future__ import annotations

import argparse

from crafting_bot import paths
from crafting_bot.factory import build_reincarnation_runner
from crafting_bot.infra.calibration_store import CalibrationStore
from crafting_bot.services.reincarnation_dry_run_service import ReincarnationDryRunService
from crafting_bot.services.target_status_service import TargetStatusService


def build_dry_run_service() -> ReincarnationDryRunService:
    calibration = CalibrationStore(paths.CALIBRATION_PATH)
    calibration.load()
    return ReincarnationDryRunService(
        calibration=calibration,
        target_status=TargetStatusService(calibration),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run or dry-run the reincarnation flow.")
    parser.add_argument("--click", action="store_true", help="Actually send ADB taps. Omit for dry-run mode.")
    parser.add_argument("--after-level", type=int, default=None, help="Documentation value. Example: --after-level 82 triggers once visible level is 83.")
    parser.add_argument("--step-delay", type=float, default=0.20)
    parser.add_argument("--wait-timeout", type=float, default=8.0)
    parser.add_argument("--poll", type=float, default=0.25)
    args = parser.parse_args()

    mode = "click" if args.click else "dry_run"
    try:
        if args.click:
            result = build_reincarnation_runner().run_once(
                mode="click",
                step_delay_seconds=args.step_delay,
                wait_timeout_seconds=args.wait_timeout,
                poll_interval_seconds=args.poll,
            )
            ready = result.eligible and bool(result.steps) and all(step.outcome == "success" for step in result.steps)
        else:
            dry = build_dry_run_service().plan()
            result = dry
            ready = dry.ready
    except Exception as exc:
        print("ok: False")
        print(f"message: {exc}")
        return 1

    print("ok: True")
    print("Run reincarnation once")
    print("=" * 120)
    print(f"mode: {mode}")
    print("clicks_sent: " + ("yes" if args.click else "no"))
    if args.after_level is not None:
        print(f"reincarnate_after_level: {args.after_level}")
        print(f"trigger_visible_level: {args.after_level + 1}")
    print(f"ready: {ready}")
    print("-" * 120)

    if args.click:
        for step in result.steps:
            definition = step.definition
            print(f"{definition.order}. {definition.action}")
            print(f"   target: {definition.target_name}")
            if definition.fallback_point_names:
                print(f"   fallback_targets: {', '.join(definition.fallback_point_names)}")
            if step.target_used:
                print(f"   target_used: {step.target_used}")
            if step.click_x is not None and step.click_y is not None:
                print(f"   click: x={step.click_x}, y={step.click_y}")
            print(f"   outcome: {step.outcome}")
            if definition.verification_target:
                print(f"   verify: {definition.verification_target}")
                if step.verification is not None:
                    print(f"   verification_passed: {step.verification.passed}")
                    if step.verification.score is not None:
                        print(f"   verification_score: {step.verification.score}")
                    print(f"   verification_message: {step.verification.message}")
            print(f"   message: {step.message}")
    else:
        for step in result.steps:
            definition = step.definition
            print(f"{definition.order}. {definition.action}")
            print(f"   target: {definition.target_name}")
            if definition.fallback_point_names:
                print(f"   fallback_targets: {', '.join(definition.fallback_point_names)}")
            if step.target_used:
                print(f"   target_used: {step.target_used}")
            if step.click_x is not None and step.click_y is not None:
                print(f"   planned_click: x={step.click_x}, y={step.click_y}")
            print(f"   target_status: {step.target_status}")
            if definition.verification_target:
                print(f"   verify: {definition.verification_target}")
                print(f"   verification_status: {step.verification_status}")
            print(f"   ready: {step.ready}")
            print(f"   message: {step.message}")
            if definition.notes:
                print(f"   notes: {definition.notes}")

    print("-" * 120)
    print(f"message: {result.message}")
    if args.click:
        print("safety: This command runs one reincarnation sequence only.")
    else:
        print("safety: Dry-run only. It does not send ADB taps.")
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
