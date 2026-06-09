from __future__ import annotations

from crafting_bot.factory import build_level_scanner


def main() -> int:
    scanner = build_level_scanner()
    result = scanner.scan()

    print(f"ok: {result.ok}")
    print(f"screen: {result.screen}")
    print(f"level_text: {result.level_text}")
    print(f"level: {result.level}")
    print(f"ready: {result.ready}")
    print(f"ready_score: {result.ready_score}")
    print(f"ready_template: {result.ready_template}")
    print(f"digit_score: {result.digit_score}")
    print(f"digit_diagnostics: {result.digit_diagnostics}")
    print(f"level_crop_path: {result.level_crop_path}")
    print(f"message: {result.message}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
