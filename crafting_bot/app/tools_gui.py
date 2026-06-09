from __future__ import annotations

import subprocess
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from crafting_bot.domain.target_catalog import SEARCH_TARGETS, TARGETS


@dataclass(frozen=True)
class ToolDefinition:
    title: str
    module: str
    needs_target: bool = False
    needs_digit: bool = False
    needs_level: bool = False
    target_kind: str = "any"
    default_target: str | None = None
    description: str = ""
    extra_args: tuple[str, ...] = ()


TOOLS: tuple[ToolDefinition, ...] = (
    ToolDefinition("ADB check", "crafting_bot.cli.adb_check", description="Check and auto-connect BlueStacks ADB."),
    ToolDefinition("Scan once", "crafting_bot.cli.scan_once", description="Run one level/ready scan."),
    ToolDefinition("Classify screen", "crafting_bot.cli.classify_screen", description="Classify the current screen without clicking. No bag/anvil classifier is used."),
    ToolDefinition("Recovery dry-run", "crafting_bot.cli.recovery_dry_run", description="Classify current screen and show suggested recovery. No clicks."),
    ToolDefinition(
        "Recover once",
        "crafting_bot.cli.recover_once",
        extra_args=("--click",),
        description="Execute one safe recovery action. ESC/BACK actions only unless run manually with --allow-forward-clicks.",
    ),
    ToolDefinition("List targets", "crafting_bot.cli.list_targets", description="Show configured, missing, and mismatched calibration targets."),
    ToolDefinition("Cycle report", "crafting_bot.cli.cycle_report", description="Show the draft level 1, levels 2-5, and level 6+ flow definitions."),
    ToolDefinition("Dry-run cycle decision", "crafting_bot.cli.dry_run_cycle", description="Scan current level and show which rebuild flow would run. No clicks."),
    ToolDefinition("Run cycle once dry-run", "crafting_bot.cli.run_cycle_once", description="Build the guarded one-cycle execution plan. No clicks unless CLI --click is used manually."),
    ToolDefinition("Run loop dry-run", "crafting_bot.cli.run_loop", description="Plan the small unattended loop. No clicks unless CLI --click is used manually."),
    ToolDefinition("Train digit template", "crafting_bot.cli.train_digit_template", needs_digit=True, description="Select a digit crop from the current level_area and save it as a normalized template."),
    ToolDefinition("Auto-train visible level digits", "crafting_bot.cli.train_level_digits", needs_level=True, description="Enter the visible level number and automatically extract/save its digit templates."),
    ToolDefinition(
        "Calibrate target",
        "crafting_bot.cli.calibrate_target",
        needs_target=True,
        description="Select a point or area from a live screenshot and save it.",
    ),
    ToolDefinition(
        "Capture target crop",
        "crafting_bot.cli.capture_target",
        needs_target=True,
        target_kind="area",
        description="Refresh the saved crop for an already-calibrated area target.",
    ),
    ToolDefinition(
        "Find dynamic rebuild button",
        "crafting_bot.cli.find_search_target",
        needs_target=True,
        target_kind="search",
        default_target="rebuild_button_dynamic",
        description="Search for the level 6+ rebuild button without clicking it.",
    ),
)


class ToolsGui(tk.Tk):
    """Small external launcher for maintenance tools, separate from the bot GUI."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Crafting Idle Bot Tools")
        self.geometry("860x560")
        self.minsize(760, 460)

        self.target_var = tk.StringVar(value="")
        self.digit_var = tk.StringVar(value="1")
        self.level_var = tk.StringVar(value="1")
        self.status_var = tk.StringVar(value="Ready")
        self._target_names_by_kind = self._build_target_names_by_kind()
        self._tool_rows: list[tuple[ToolDefinition, tk.Button]] = []

        self._build_ui()
        self._select_default_target()

    def _build_ui(self) -> None:
        root = tk.Frame(self, padx=12, pady=12)
        root.pack(fill=tk.BOTH, expand=True)

        target_box = tk.LabelFrame(root, text="Target selection", padx=8, pady=8)
        target_box.pack(fill=tk.X)

        tk.Label(target_box, text="Target").pack(side=tk.LEFT)
        self.target_combo = ttk.Combobox(target_box, textvariable=self.target_var, values=self._target_names_by_kind["any"], width=46)
        self.target_combo.pack(side=tk.LEFT, padx=(8, 8))

        tk.Button(target_box, text="All", width=10, command=lambda: self._set_target_filter("any")).pack(side=tk.LEFT)
        tk.Button(target_box, text="Areas", width=10, command=lambda: self._set_target_filter("area")).pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(target_box, text="Search", width=10, command=lambda: self._set_target_filter("search")).pack(side=tk.LEFT, padx=(6, 0))

        tk.Label(target_box, text="Digit", anchor="e").pack(side=tk.LEFT, padx=(18, 4))
        self.digit_combo = ttk.Combobox(target_box, textvariable=self.digit_var, values=[str(i) for i in range(10)], width=4, state="readonly")
        self.digit_combo.pack(side=tk.LEFT)

        tk.Label(target_box, text="Level", anchor="e").pack(side=tk.LEFT, padx=(18, 4))
        self.level_entry = tk.Entry(target_box, textvariable=self.level_var, width=6)
        self.level_entry.pack(side=tk.LEFT)

        tools_box = tk.LabelFrame(root, text="Tools", padx=8, pady=8)
        tools_box.pack(fill=tk.X, pady=(10, 8))

        for row, tool in enumerate(TOOLS):
            title = tk.Label(tools_box, text=tool.title, width=28, anchor="w")
            title.grid(row=row, column=0, sticky="w", pady=3)

            description = tk.Label(tools_box, text=tool.description, anchor="w")
            description.grid(row=row, column=1, sticky="w", padx=(8, 8), pady=3)

            button = tk.Button(tools_box, text="Run", width=10, command=lambda selected_tool=tool: self._run_tool(selected_tool))
            button.grid(row=row, column=2, sticky="e", pady=3)
            self._tool_rows.append((tool, button))

        tools_box.grid_columnconfigure(1, weight=1)

        output_box = tk.LabelFrame(root, text="Output", padx=8, pady=8)
        output_box.pack(fill=tk.BOTH, expand=True)

        self.output = ScrolledText(output_box, height=14, state=tk.DISABLED)
        self.output.pack(fill=tk.BOTH, expand=True)

        status = tk.Label(root, textvariable=self.status_var, anchor="w")
        status.pack(fill=tk.X, pady=(6, 0))

    def _build_target_names_by_kind(self) -> dict[str, list[str]]:
        point_names = [target.name for target in TARGETS if target.kind == "point"]
        area_names = [target.name for target in TARGETS if target.kind == "area"]
        search_names = [target.name for target in SEARCH_TARGETS]
        return {
            "point": point_names,
            "area": area_names,
            "search": search_names,
            "any": point_names + area_names + search_names,
        }

    def _select_default_target(self) -> None:
        if "rebuild_button_check_area" in self._target_names_by_kind["any"]:
            self.target_var.set("rebuild_button_check_area")
        elif self._target_names_by_kind["any"]:
            self.target_var.set(self._target_names_by_kind["any"][0])

    def _set_target_filter(self, kind: str) -> None:
        values = self._target_names_by_kind[kind]
        self.target_combo.configure(values=values)
        if values and self.target_var.get() not in values:
            self.target_var.set(values[0])

    def _run_tool(self, tool: ToolDefinition) -> None:
        target = self.target_var.get().strip()
        if tool.needs_target:
            if tool.default_target and tool.target_kind == "search":
                target = tool.default_target if not target or target not in self._target_names_by_kind["search"] else target
            elif not target:
                self._append_output("No target selected.\n")
                return

            valid_targets = self._target_names_by_kind.get(tool.target_kind, self._target_names_by_kind["any"])
            if target not in valid_targets:
                self._append_output(f"Selected target {target!r} is not valid for {tool.title}.\n")
                return

        args = [sys.executable, "-B", "-m", tool.module]
        args.extend(tool.extra_args)
        if tool.needs_target:
            args.append(target)
        if tool.needs_digit:
            digit = self.digit_var.get().strip()
            if digit not in {str(i) for i in range(10)}:
                self._append_output(f"Selected digit {digit!r} is invalid. Use 0-9.\n")
                return
            args.append(digit)
            args.extend(["--source-label", "manual_gui"])

        if tool.needs_level:
            level = self.level_var.get().strip()
            if not level.isdigit():
                self._append_output(f"Selected level {level!r} is invalid. Use digits only, e.g. 9.\n")
                return
            args.append(level)
            args.extend(["--state", "ready"])

        self._set_running(True)
        self._append_output(f"\n[{time.strftime('%H:%M:%S')}] Running: {' '.join(args)}\n")

        thread = threading.Thread(target=self._run_subprocess, args=(args,), daemon=True)
        thread.start()

    def _run_subprocess(self, args: list[str]) -> None:
        try:
            completed = subprocess.run(args, check=False, capture_output=True, text=True)
            text = completed.stdout
            if completed.stderr:
                text += "\n[stderr]\n" + completed.stderr
            text += f"\nexit_code: {completed.returncode}\n"
        except Exception as exc:
            text = f"Tool failed to start: {exc}\n"
        self.after(0, lambda: self._finish_tool(text))

    def _finish_tool(self, text: str) -> None:
        self._append_output(text)
        self._set_running(False)

    def _set_running(self, running: bool) -> None:
        state = tk.DISABLED if running else tk.NORMAL
        for _tool, button in self._tool_rows:
            button.configure(state=state)
        self.status_var.set("Running tool..." if running else "Ready")

    def _append_output(self, text: str) -> None:
        self.output.config(state=tk.NORMAL)
        self.output.insert(tk.END, text)
        self.output.see(tk.END)
        self.output.config(state=tk.DISABLED)


if __name__ == "__main__":
    app = ToolsGui()
    app.mainloop()
