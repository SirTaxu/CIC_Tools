from __future__ import annotations

import argparse

from crafting_bot.factory import build_cycle_dry_run_service


def main() -> int:
    parser = argparse.ArgumentParser(description="Dry-run the rebuild cycle decision without clicking anything.")
    parser.add_argument(
        "--level",
        type=int,
        default=None,
        help="Override the scanned level for cycle-selection testing. The live scan still runs first.",
    )
    parser.add_argument(
        "--try-search-targets",
        action="store_true",
        help="Attempt search-target detection on the current screen. Use this only when the searched button is visible.",
    )
    args = parser.parse_args()

    service = build_cycle_dry_run_service()
    try:
        result = service.run(level_override=args.level, try_search_targets=args.try_search_targets)
    except Exception as exc:
        print("ok: False")
        print(f"message: {exc}")
        return 1

    scan = result.scan
    print("ok: True")
    print("Cycle dry run")
    print("=" * 120)
    print("No clicks were sent.")
    print(f"scan_ok: {scan.ok}")
    print(f"scan_screen: {scan.screen}")
    print(f"scan_level_text: {scan.level_text}")
    print(f"scan_level: {scan.level}")
    print(f"scan_ready: {scan.ready}")
    print(f"scan_ready_score: {scan.ready_score}")
    print(f"scan_digit_score: {scan.digit_score}")
    if args.level is not None:
        print(f"level_override: {args.level}")
    print(f"trigger_reason: {result.trigger_reason}")

    if result.cycle is None:
        print(f"message: {result.message}")
        return 1

    print(f"selected_cycle: {result.cycle.name}")
    print(f"levels: {result.cycle.level_range}")
    print(f"cycle_status: {result.cycle.status}")
    print(f"cycle_notes: {result.cycle.notes}")
    print("-" * 120)

    for step in result.steps:
        definition = step.definition
        print(f"{definition.order}. {definition.action}")
        print(f"   mode: {definition.mode}")
        print(f"   target: {definition.target_name}")
        print(f"   target_status: {step.target_status}")
        if definition.verification_target:
            print(f"   verify: {definition.verification_target}")
            print(f"   verify_status: {step.verification_status}")
        if step.click_x is not None and step.click_y is not None:
            print(f"   would_click: x={step.click_x}, y={step.click_y}")
        if step.search_score is not None:
            print(f"   search_score: {step.search_score}")
            print(f"   search_accepted: {step.search_accepted}")
        if step.preview_path is not None:
            print(f"   preview_path: {step.preview_path}")
        print(f"   dry_run: {step.message}")
        if definition.notes:
            print(f"   notes: {definition.notes}")

    print("-" * 120)
    print(f"message: {result.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
