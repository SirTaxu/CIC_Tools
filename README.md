# CIC Tools

Crafting Idle Clicker automation tools for BlueStacks using ADB.

This repository contains a Windows/Python bot that reads the game screen through ADB screenshots, detects the current level/ready state from calibrated templates, and runs guarded rebuild loops.

## Current stable version

**v1.3** is the current recommended version.

Main v1.3 capabilities:

- BlueStacks + ADB backend.
- Tkinter bot GUI and tools GUI.
- No-console VBS launcher.
- Level recognition using ready templates and digit templates.
- Rebuild loops for:
  - level 1,
  - levels 2-5,
  - dynamic level 6+ rebuild screens.
- Expected-level tracking and timeout-forced rebuilds.
- Optional hire/setup cycle.
- Optional reincarnation cycle.
- Screen classification and safe recovery tools.
- Reward selection for level 6+:
  - clicks gems when detected,
  - otherwise uses a calibrated default reward slider position,
  - adjusts the default slider point relative to the live Rebuild button position.

## Requirements

- Windows.
- Python installed and available as `python`.
- BlueStacks with ADB enabled.
- Crafting Idle Clicker running in BlueStacks.
- The same emulator/game layout used for calibration, or recalibrate targets before running unattended.

Install Python dependencies from the project root:

```powershell
$env:PYTHONDONTWRITEBYTECODE="1"; python -B -m pip install -r requirements.txt
```

## Running the bot

Preferred GUI launcher:

```text
Double-click Start_CIC_Bot.vbs
```

Command-line GUI launch:

```powershell
$env:PYTHONDONTWRITEBYTECODE="1"; python -B run_bot.py
```

Tools GUI:

```powershell
$env:PYTHONDONTWRITEBYTECODE="1"; python -B run_tools.py
```

## Useful CLI checks

Check ADB connection:

```powershell
$env:PYTHONDONTWRITEBYTECODE="1"; python -B -m crafting_bot.cli.adb_check
```

Run one scan:

```powershell
$env:PYTHONDONTWRITEBYTECODE="1"; python -B -m crafting_bot.cli.scan_once
```

List calibration targets:

```powershell
$env:PYTHONDONTWRITEBYTECODE="1"; python -B -m crafting_bot.cli.list_targets
```

Dry-run one cycle decision:

```powershell
$env:PYTHONDONTWRITEBYTECODE="1"; python -B -m crafting_bot.cli.run_cycle_once
```

Run one cycle with clicks:

```powershell
$env:PYTHONDONTWRITEBYTECODE="1"; python -B -m crafting_bot.cli.run_cycle_once --click
```

Analyze reward selection on a Rebuild Workshop screen:

```powershell
$env:PYTHONDONTWRITEBYTECODE="1"; python -B -m crafting_bot.cli.analyze_rewards
```

Run reward selection click manually:

```powershell
$env:PYTHONDONTWRITEBYTECODE="1"; python -B -m crafting_bot.cli.analyze_rewards --click
```

## Portability notes

The bot code stores project paths relative to the project root through `crafting_bot/paths.py`, so the folder can be renamed, moved to another drive, or run from a USB drive.

For portable releases:

- Use the portable `Start_CIC_Bot.vbs` included in this repository.
- Keep `adb_path` blank in `data/calibration/adb_bot_config.json` unless a specific machine needs a custom ADB path.
- Do not commit or release runtime logs.
- Do not commit calibration backup history unless it is intentionally needed.

The current `.gitignore` excludes logs, Python caches, and calibration backups while keeping active calibration data/templates.

## Calibration

Most users can start with the included calibration data if their BlueStacks resolution/layout matches.

If the layout differs, recalibrate through:

```powershell
$env:PYTHONDONTWRITEBYTECODE="1"; python -B run_tools.py
```

Important v1.3 reward targets:

```text
reward_slider_default_point
reward_gems_template
reward_gems_search_area
```

The default reward slider point is a reference point. At runtime, the bot adjusts it vertically relative to the live `rebuild_button_dynamic` position.

## Safety

Start with dry-runs and single-cycle tests before running unattended:

```powershell
$env:PYTHONDONTWRITEBYTECODE="1"; python -B -m crafting_bot.cli.run_cycle_once
$env:PYTHONDONTWRITEBYTECODE="1"; python -B -m crafting_bot.cli.run_cycle_once --click
```

Unsolved manual case:

```text
You have too many Blueprints!
```

That inventory-full state should be reset manually for now.
