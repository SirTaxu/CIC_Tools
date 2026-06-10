from __future__ import annotations

import argparse

from crafting_bot.factory import build_reward_selection_service


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze/select Rebuild Workshop rewards. Click mode is optional.")
    parser.add_argument("--click", action="store_true", help="Actually apply the reward selection.")
    args = parser.parse_args()

    service = build_reward_selection_service()
    result = service.prepare_reward_selection(mode="click" if args.click else "dry_run")

    print(f"ok: {result.ok}")
    print(f"mode: {'click' if args.click else 'dry_run'}")
    print(f"action: {result.action}")
    print(f"selected_reward: {result.selected_reward}")
    print(f"gems_present: {'yes' if result.gems_present else 'no'}")
    print(f"click_x: {result.click_x}")
    print(f"click_y: {result.click_y}")
    print(f"gems_score: {result.gems_score}")
    print(f"gems_threshold: {result.gems_threshold}")
    print(f"preview_path: {result.preview_path}")
    print(f"message: {result.message}")


if __name__ == "__main__":
    main()
