from __future__ import annotations

from crafting_bot.domain.cycle_definitions import CYCLE_DEFINITIONS
from crafting_bot.factory import build_calibration_store
from crafting_bot.services.target_status_service import TargetStatusService


def main() -> int:
    store = build_calibration_store()
    status_service = TargetStatusService(store)
    print("Cycle definition report")
    print("=" * 120)
    print("This report does not click anything. It confirms targets and verification checks before run_cycle_once --click.")
    print()

    for cycle in CYCLE_DEFINITIONS:
        print(f"Cycle: {cycle.name}")
        print(f"Levels: {cycle.level_range}")
        print(f"Status: {cycle.status}")
        print(f"Notes: {cycle.notes}")
        print("-" * 120)
        for step in cycle.steps:
            print(f"{step.order}. {step.action}")
            print(f"   mode: {step.mode}")
            print(f"   target: {step.target_name}")
            print(f"   target_status: {status_service.describe(step.target_name)}")
            if step.verification_target:
                print(f"   verify: {step.verification_target}")
                print(f"   verify_status: {status_service.describe(step.verification_target)}")
            if step.notes:
                print(f"   notes: {step.notes}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
