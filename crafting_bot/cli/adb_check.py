from __future__ import annotations

from crafting_bot.factory import build_adb_client


def main() -> int:
    adb = build_adb_client()
    print(f"adb_path: {adb.adb_path}")
    print("devices_before:")
    before = adb.list_devices()
    if before:
        for serial, state in before:
            print(f"  {serial}\t{state}")
    else:
        print("  none")

    try:
        selected = adb.ensure_device()
    except Exception as exc:
        print("ok: False")
        print(f"message: {exc}")
        return 1

    print("devices_after:")
    after = adb.list_devices()
    if after:
        for serial, state in after:
            print(f"  {serial}\t{state}")
    else:
        print("  none")
    print("ok: True")
    print(f"selected_device: {selected}")
    print(f"message: {adb.last_connection_message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
