from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox
from tkinter.scrolledtext import ScrolledText

from crafting_bot import paths
from crafting_bot.application.settings import RebuildLoopSettings
from crafting_bot.domain.bot_session import BotSessionStatus
from crafting_bot.services.bot_command_store import BotCommandStore
from crafting_bot.services.bot_status_store import BotStatusStore


class Tooltip:
    """Small hover tooltip for compact GUI help."""

    def __init__(self, widget: tk.Widget, text: str, *, delay_ms: int = 450) -> None:
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after_id: str | None = None
        self._window: tk.Toplevel | None = None

        widget.bind("<Enter>", self._schedule)
        widget.bind("<Leave>", self._hide)
        widget.bind("<ButtonPress>", self._hide)

    def _schedule(self, _event: object | None = None) -> None:
        self._cancel()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _show(self) -> None:
        self._after_id = None
        if self._window is not None or not self.text:
            return

        x = self.widget.winfo_rootx() + 18
        y = self.widget.winfo_rooty() + 22

        window = tk.Toplevel(self.widget)
        window.wm_overrideredirect(True)
        window.wm_geometry(f"+{x}+{y}")

        label = tk.Label(
            window,
            text=self.text,
            justify=tk.LEFT,
            background="#ffffe0",
            relief=tk.SOLID,
            borderwidth=1,
            padx=8,
            pady=5,
            wraplength=360,
        )
        label.pack()
        self._window = window

    def _hide(self, _event: object | None = None) -> None:
        self._cancel()
        if self._window is not None:
            self._window.destroy()
            self._window = None

    def _cancel(self) -> None:
        if self._after_id is not None:
            self.widget.after_cancel(self._after_id)
            self._after_id = None


class ToolOutputDialog(tk.Toplevel):
    """Small output window for running CLI tools from the GUI."""

    def __init__(self, parent: tk.Widget, *, title: str, command: list[str]) -> None:
        super().__init__(parent)
        self.title(title)
        self.geometry("900x560")
        self.minsize(700, 420)
        self.command = command

        frame = tk.Frame(self, padx=10, pady=10)
        frame.pack(fill=tk.BOTH, expand=True)

        header = tk.Label(frame, text=" ".join(command), anchor="w", justify=tk.LEFT)
        header.pack(fill=tk.X)

        self.output = ScrolledText(frame, wrap=tk.WORD, height=25)
        self.output.pack(fill=tk.BOTH, expand=True, pady=(8, 8))
        self.output.insert(tk.END, "Running...\n")
        self.output.config(state=tk.DISABLED)

        buttons = tk.Frame(frame)
        buttons.pack(fill=tk.X)
        tk.Button(buttons, text="Close", width=12, command=self.destroy).pack(side=tk.RIGHT)

        self._thread = threading.Thread(target=self._run_command, daemon=True)
        self._thread.start()

    def _run_command(self) -> None:
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"

        try:
            completed = subprocess.run(
                self.command,
                cwd=paths.PROJECT_ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=120,
            )
            output = completed.stdout
            if completed.stderr:
                output += ("\n" if output else "") + "STDERR:\n" + completed.stderr
            output += f"\n\nExit code: {completed.returncode}\n"
        except subprocess.TimeoutExpired as exc:
            output = f"Command timed out after {exc.timeout} seconds.\n"
            if exc.stdout:
                output += f"\nSTDOUT:\n{exc.stdout}\n"
            if exc.stderr:
                output += f"\nSTDERR:\n{exc.stderr}\n"
        except Exception as exc:
            output = f"Could not run command:\n{exc}\n"

        self.after(0, self._set_output, output)

    def _set_output(self, output: str) -> None:
        self.output.config(state=tk.NORMAL)
        self.output.delete("1.0", tk.END)
        self.output.insert(tk.END, output)
        self.output.config(state=tk.DISABLED)


class BotGui(tk.Tk):
    """GUI control panel for the CIC bot.

    The GUI is now a tool/control panel. It can open without a bot session,
    inspect logs/status, run diagnostics, and start/stop a bot session through
    the BotSessionController boundary.
    """

    # Safety cap for GUI rebuild-cycle counting. The visible stop condition should
    # normally be manual Stop, reincarnation mode, or a failure.
    _GUI_MAX_REBUILD_CYCLES = 10000

    # Used when optional GUI iteration safety is disabled. At one scan per second
    # it is effectively unlimited for normal runs while keeping an integer API.
    _GUI_UNLIMITED_MAX_ITERATIONS = 10_000_000

    def __init__(self) -> None:
        super().__init__()

        self.title("Crafting Idle Bot")
        self.geometry("460x720")
        self.minsize(420, 640)

        self.status_queue: queue.Queue[BotSessionStatus] = queue.Queue()
        self.status_store = BotStatusStore()
        self.command_store = BotCommandStore()
        self.session_controller = None
        self.session_handle = None

        self.desired_level_var = tk.StringVar(value="")
        self.stuck_seconds_var = tk.StringVar(value="20")
        self.scan_interval_var = tk.StringVar(value="1.0")
        self.reincarnation_var = tk.BooleanVar(value=False)
        self.auto_train_var = tk.BooleanVar(value=False)
        self.hire_enabled_var = tk.BooleanVar(value=True)
        self.hire_level_var = tk.StringVar(value="45")
        self.max_iterations_enabled_var = tk.BooleanVar(value=False)
        self.max_iterations_var = tk.StringVar(value="500")

        self.running_var = tk.StringVar(value="Idle")
        self.session_var = tk.StringVar(value="none")
        self.screen_var = tk.StringVar(value="UNKNOWN")
        self.level_var = tk.StringVar(value="-")
        self.ready_var = tk.StringVar(value="unknown")
        self.cycles_var = tk.StringVar(value="0")
        self.timer_var = tk.StringVar(value="0.0s")
        self.last_action_var = tk.StringVar(value="-")
        self.message_var = tk.StringVar(value="GUI is open. Bot is not required for tools.")

        self._inputs_enabled = True
        self._last_notification_key = ""
        self._last_status_signature: tuple[object, ...] | None = None
        self.log_path = paths.LOG_DIR / "log.txt"

        self._build_ui()
        self._configure_control_dependencies()

        self.reincarnation_var.trace_add("write", lambda *_: self._configure_control_dependencies())
        self.hire_enabled_var.trace_add("write", lambda *_: self._configure_control_dependencies())
        self.max_iterations_enabled_var.trace_add("write", lambda *_: self._configure_control_dependencies())

        self._poll_status()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        root = tk.Frame(self, padx=12, pady=12)
        root.pack(fill=tk.BOTH, expand=True)

        controls = tk.LabelFrame(root, text="Runtime controls", padx=10, pady=8)
        controls.pack(fill=tk.X)

        timing_row = tk.Frame(controls)
        timing_row.pack(fill=tk.X, pady=(0, 10))

        self._add_help_icon(
            timing_row,
            "Wait timer controls how long the bot waits on the same not-ready level before trying a timeout rebuild/progress cycle. "
            "Scan interval controls how often the loop checks the screen.",
        )

        tk.Label(timing_row, text="Wait timer").pack(side=tk.LEFT)
        tk.Entry(timing_row, textvariable=self.stuck_seconds_var, width=5).pack(side=tk.LEFT, padx=(6, 10))

        tk.Label(timing_row, text="Scan interval").pack(side=tk.LEFT)
        tk.Entry(timing_row, textvariable=self.scan_interval_var, width=5).pack(side=tk.LEFT, padx=(6, 6))

        row_reincarnation = tk.Frame(controls)
        row_reincarnation.pack(fill=tk.X, pady=(0, 7))

        self._add_help_icon(
            row_reincarnation,
            "When enabled, Target level means the last level to complete before reincarnating. "
            "When disabled, the bot keeps climbing until stopped manually or by a protected failure.",
        )

        self.reincarnation_check = tk.Checkbutton(
            row_reincarnation,
            text="Reincarnate after level",
            variable=self.reincarnation_var,
            width=22,
            anchor="w",
        )
        self.reincarnation_check.pack(side=tk.LEFT)

        self.desired_level_entry = tk.Entry(row_reincarnation, textvariable=self.desired_level_var, width=5)
        self.desired_level_entry.pack(side=tk.LEFT, padx=(6, 0))

        row_hire = tk.Frame(controls)
        row_hire.pack(fill=tk.X, pady=(0, 7))

        self._add_help_icon(
            row_hire,
            "Runs the hire/setup cycle once per climb, only when the visible level exactly matches Hire/setup level. "
            "It resets after reincarnation.",
        )

        self.hire_check = tk.Checkbutton(
            row_hire,
            text="Hire once at level",
            variable=self.hire_enabled_var,
            width=22,
            anchor="w",
        )
        self.hire_check.pack(side=tk.LEFT)

        self.hire_level_entry = tk.Entry(row_hire, textvariable=self.hire_level_var, width=5)
        self.hire_level_entry.pack(side=tk.LEFT, padx=(6, 0))

        row_autotrain = tk.Frame(controls)
        row_autotrain.pack(fill=tk.X, pady=(0, 7))

        self._add_help_icon(
            row_autotrain,
            "When enabled, the bot may save digit templates only if expected-level tracking proves the visible level. "
            "Keep disabled if you prefer to manually train missing digits.",
        )

        self.auto_train_check = tk.Checkbutton(
            row_autotrain,
            text="Auto-train missing digits",
            variable=self.auto_train_var,
            width=40,
            anchor="w",
        )
        self.auto_train_check.pack(side=tk.LEFT)

        row_iterations = tk.Frame(controls)
        row_iterations.pack(fill=tk.X, pady=(0, 0))

        self._add_help_icon(
            row_iterations,
            "Optional safety cap for loop iterations. Normally leave disabled for long unattended runs.",
        )

        self.max_iterations_check = tk.Checkbutton(
            row_iterations,
            text="Max loop iterations",
            variable=self.max_iterations_enabled_var,
            width=22,
            anchor="w",
        )
        self.max_iterations_check.pack(side=tk.LEFT)

        self.max_iterations_entry = tk.Entry(row_iterations, textvariable=self.max_iterations_var, width=7)
        self.max_iterations_entry.pack(side=tk.LEFT, padx=(6, 0))

        button_row = tk.Frame(root)
        button_row.pack(fill=tk.X, pady=(10, 0))

        self.start_button = tk.Button(button_row, text="Start bot", width=14, command=self._start_bot)
        self.start_button.pack(side=tk.LEFT)

        self.stop_button = tk.Button(
            button_row,
            text="Stop",
            width=14,
            command=self._stop_bot,
            state=tk.DISABLED,
        )
        self.stop_button.pack(side=tk.LEFT, padx=(8, 0))

        self.refresh_button = tk.Button(button_row, text="Refresh status", width=14, command=self._refresh_status)
        self.refresh_button.pack(side=tk.LEFT, padx=(8, 0))

        status_box = tk.LabelFrame(root, text="Status", padx=10, pady=8)
        status_box.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

        self._add_status_row(status_box, 0, "State", self.running_var)
        self._add_status_row(status_box, 1, "Session", self.session_var)
        self._add_status_row(status_box, 2, "Screen", self.screen_var)
        self._add_status_row(status_box, 3, "Level", self.level_var)
        self._add_status_row(status_box, 4, "Ready", self.ready_var)
        self._add_status_row(status_box, 5, "Progress", self.cycles_var)
        self._add_status_row(status_box, 6, "Wait timer", self.timer_var)
        self._add_status_row(status_box, 7, "Last action", self.last_action_var)
        self._add_status_row(status_box, 8, "Message", self.message_var, wraplength=260)

        tools_box = tk.LabelFrame(root, text="Tools", padx=10, pady=8)
        tools_box.pack(fill=tk.X, pady=(12, 0))

        tool_row_1 = tk.Frame(tools_box)
        tool_row_1.pack(fill=tk.X)
        tk.Button(tool_row_1, text="Bot status", width=13, command=self._tool_bot_status).pack(side=tk.LEFT)
        tk.Button(tool_row_1, text="Scan once", width=13, command=self._tool_scan_once).pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(tool_row_1, text="Find errors", width=13, command=self._tool_find_errors).pack(side=tk.LEFT, padx=(6, 0))

        tool_row_2 = tk.Frame(tools_box)
        tool_row_2.pack(fill=tk.X, pady=(6, 0))
        tk.Button(tool_row_2, text="Log report", width=13, command=self._tool_log_report).pack(side=tk.LEFT)
        tk.Button(tool_row_2, text="Template report", width=13, command=self._tool_template_report).pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(tool_row_2, text="Template health", width=13, command=self._tool_template_health).pack(side=tk.LEFT, padx=(6, 0))

        log_button_row = tk.Frame(root)
        log_button_row.pack(fill=tk.X, pady=(8, 0))

        tk.Button(
            log_button_row,
            text="Open log file",
            width=14,
            command=self._open_log_file,
        ).pack(side=tk.LEFT)

        tk.Button(
            log_button_row,
            text="Open logs folder",
            width=16,
            command=self._open_logs_folder,
        ).pack(side=tk.LEFT, padx=(8, 0))

    def _add_help_icon(
        self,
        parent: tk.Widget,
        text: str,
        *,
        grid_row: int | None = None,
        grid_column: int | None = None,
    ) -> tk.Label:
        icon = tk.Label(
            parent,
            text="?",
            width=2,
            cursor="question_arrow",
            relief=tk.GROOVE,
            borderwidth=1,
        )
        if grid_row is None or grid_column is None:
            icon.pack(side=tk.LEFT, padx=(6, 0))
        else:
            icon.grid(row=grid_row, column=grid_column, sticky="w", padx=(0, 0))
        Tooltip(icon, text)
        return icon

    def _add_status_row(
        self,
        parent: tk.Widget,
        row: int,
        label: str,
        variable: tk.StringVar,
        *,
        wraplength: int | None = None,
    ) -> None:
        tk.Label(parent, text=label, anchor="w", width=18).grid(row=row, column=0, sticky="nw", pady=2)
        value_label = tk.Label(parent, textvariable=variable, anchor="w", justify=tk.LEFT)
        if wraplength is not None:
            value_label.config(wraplength=wraplength)
        value_label.grid(row=row, column=1, sticky="w", pady=2)
        parent.grid_columnconfigure(1, weight=1)

    def _start_bot(self) -> None:
        if self._runtime_is_active(self.status_store.read()):
            messagebox.showinfo("Bot already running", "A bot session is already running or stopping.")
            return

        try:
            settings = self._read_settings()
        except ValueError as exc:
            messagebox.showerror("Invalid loop setting", str(exc))
            return

        self._write_log("Starting GUI-controlled bot session.")

        try:
            controller = self._get_session_controller()
            self.session_handle = controller.start_background(
                settings,
                on_status=lambda status: self.status_queue.put(status),
            )
        except Exception as exc:
            messagebox.showerror("Could not start bot", f"The GUI is still usable, but the bot could not start.\n\n{exc}")
            self._write_log(f"Could not start GUI-controlled bot session: {exc}")
            return

        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self._set_inputs_enabled(False)

    def _stop_bot(self) -> None:
        status = self.status_store.read()
        session_id = status.session_id if status.session_id != "none" else None

        if self.session_handle is not None and self.session_handle.running:
            self.session_handle.stop()

        if self.session_controller is not None:
            self.session_controller.request_stop(session_id=session_id, reason="manual_stop")
        else:
            self.command_store.request_stop(session_id=session_id, reason="manual_stop")

        self.stop_button.config(state=tk.DISABLED)
        self._write_log("Stop requested from GUI.")

    def _read_settings(self) -> RebuildLoopSettings:
        reincarnation_enabled = self.reincarnation_var.get()
        desired_level = (
            self._read_positive_int(self.desired_level_var.get(), "Target level")
            if reincarnation_enabled
            else None
        )
        stuck_seconds = self._read_positive_float(self.stuck_seconds_var.get(), "Wait timer")
        scan_interval = self._read_positive_float(self.scan_interval_var.get(), "Scan interval")
        hire_enabled = self.hire_enabled_var.get()
        hire_level = (
            self._read_positive_int(self.hire_level_var.get(), "Hire/setup level")
            if hire_enabled
            else 45
        )
        max_iterations = (
            self._read_positive_int(self.max_iterations_var.get(), "Max iterations")
            if self.max_iterations_enabled_var.get()
            else self._GUI_UNLIMITED_MAX_ITERATIONS
        )

        return RebuildLoopSettings(
            mode="click",
            max_cycles=self._GUI_MAX_REBUILD_CYCLES,
            desired_level=desired_level,
            reincarnation_enabled=reincarnation_enabled,
            stuck_seconds=stuck_seconds,
            scan_interval_seconds=scan_interval,
            assist_digit_training=False,
            auto_train_missing_digits=self.auto_train_var.get(),
            hire_enabled=hire_enabled,
            hire_setup_level=hire_level,
            hire_drag_duration_ms=750,
            max_iterations=max_iterations,
        )

    def _get_session_controller(self):
        if self.session_controller is None:
            from crafting_bot.factory import build_bot_session_controller

            self.session_controller = build_bot_session_controller()
        return self.session_controller

    def _poll_status(self) -> None:
        while True:
            try:
                status = self.status_queue.get_nowait()
            except queue.Empty:
                break
            self._apply_status(status)

        self._refresh_status(silent=True)
        self.after(500, self._poll_status)

    def _refresh_status(self, *, silent: bool = False) -> None:
        status = self.status_store.read()
        signature = (
            status.session_id,
            status.state,
            status.updated_at,
            status.level_text,
            status.cycles_completed,
            status.message,
        )

        if signature != self._last_status_signature:
            self._last_status_signature = signature
            self._apply_status(status)
        elif not silent:
            self._apply_status(status)

    def _apply_status(self, status: BotSessionStatus) -> None:
        self.running_var.set(status.state)
        self.session_var.set(status.session_id)
        self.screen_var.set(status.screen)
        self.level_var.set(status.level_text)
        self.ready_var.set(status.ready)
        self.cycles_var.set(
            f"{status.cycles_completed} rebuilds, "
            f"{status.hire_setups_completed} hire setups, "
            f"{status.reincarnations_completed} reincarnations"
        )
        self.timer_var.set(f"{status.same_level_seconds:.1f}s")

        action = status.last_action
        if status.trigger_reason and status.trigger_reason != "-":
            action = f"{action}: {status.trigger_reason}"
        if status.selected_cycle:
            action = f"{action} / {status.selected_cycle}"
        self.last_action_var.set(action)

        message = status.message or ""
        self.message_var.set(self._shorten(message, 180))

        active = self._runtime_is_active(status)
        if active:
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL if status.state != "stopping" else tk.DISABLED)
            self._set_inputs_enabled(False)
        else:
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
            self._set_inputs_enabled(True)

        if status.state == "failed":
            self._show_once_for_status(
                key=f"{status.session_id}:{status.updated_at}:failed",
                title="Bot failed",
                message=status.message or status.error or "The bot session failed.",
            )
        elif status.state == "stopped" and status.stopped_reason not in {None, "", "stop_requested", "dry_run_planned_one_cycle"}:
            self._show_once_for_status(
                key=f"{status.session_id}:{status.updated_at}:{status.stopped_reason}",
                title="Bot stopped",
                message=status.message or f"Stopped reason: {status.stopped_reason}",
            )

    @staticmethod
    def _runtime_is_active(status: BotSessionStatus) -> bool:
        return status.state in {"starting", "running", "stopping"}

    def _run_tool(self, *, title: str, module: str, extra_args: list[str] | None = None) -> None:
        command = [sys.executable, "-B", "-m", module]
        if extra_args:
            command.extend(extra_args)
        ToolOutputDialog(self, title=title, command=command)

    def _tool_bot_status(self) -> None:
        self._run_tool(title="Bot status", module="crafting_bot.cli.bot_status")

    def _tool_scan_once(self) -> None:
        self._run_tool(title="Scan once", module="crafting_bot.cli.scan_once")

    def _tool_find_errors(self) -> None:
        self._run_tool(title="Find errors", module="crafting_bot.cli.find_errors")

    def _tool_log_report(self) -> None:
        self._run_tool(title="Log report", module="crafting_bot.cli.log_report")

    def _tool_template_report(self) -> None:
        self._run_tool(title="Template report", module="crafting_bot.cli.template_report")

    def _tool_template_health(self) -> None:
        self._run_tool(title="Template health check", module="crafting_bot.cli.template_health_check")

    def _write_log(self, text: str) -> None:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] {text}\n"

        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line)

    def _open_log_file(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_path.exists():
            self.log_path.write_text("", encoding="utf-8")
        self._open_path(self.log_path)

    def _open_logs_folder(self) -> None:
        paths.LOG_DIR.mkdir(parents=True, exist_ok=True)
        self._open_path(paths.LOG_DIR)

    def _open_path(self, path: object) -> None:
        path_text = str(path)
        try:
            if os.name == "nt":
                os.startfile(path_text)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path_text])
            else:
                subprocess.Popen(["xdg-open", path_text])
        except Exception as exc:
            messagebox.showerror("Could not open path", f"Could not open:\n{path_text}\n\n{exc}")

    def _show_once_for_status(self, *, key: str, title: str, message: str) -> None:
        if key == self._last_notification_key:
            return
        self._last_notification_key = key
        self._show_stop_dialog(title, message)

    def _show_stop_dialog(self, title: str, message: str) -> None:
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.geometry("520x260")
        dialog.minsize(460, 220)

        body = tk.Frame(dialog, padx=18, pady=18)
        body.pack(fill=tk.BOTH, expand=True)

        tk.Label(body, text=title, font=("TkDefaultFont", 11, "bold"), anchor="w").pack(fill=tk.X)
        tk.Message(body, text=message, width=470, anchor="w", justify=tk.LEFT).pack(fill=tk.BOTH, expand=True, pady=(12, 12))

        button_row = tk.Frame(body)
        button_row.pack(fill=tk.X)
        tk.Button(button_row, text="OK", width=14, command=dialog.destroy).pack(anchor="center")

        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        dialog.update_idletasks()
        x = self.winfo_x() + max(0, (self.winfo_width() - dialog.winfo_width()) // 2)
        y = self.winfo_y() + max(0, (self.winfo_height() - dialog.winfo_height()) // 2)
        dialog.geometry(f"+{x}+{y}")
        dialog.focus_set()

    def _set_inputs_enabled(self, enabled: bool) -> None:
        self._inputs_enabled = enabled
        state = tk.NORMAL if enabled else tk.DISABLED
        for child in self.winfo_children():
            self._set_entry_children_state(child, state)
        self._configure_control_dependencies()

        # Runtime buttons and tools are not "settings inputs"; restore them based
        # on status after the recursive state change.
        status = self.status_store.read()
        active = self._runtime_is_active(status)
        self.start_button.config(state=tk.DISABLED if active else tk.NORMAL)
        self.stop_button.config(state=tk.NORMAL if active and status.state != "stopping" else tk.DISABLED)
        self.refresh_button.config(state=tk.NORMAL)

    def _set_entry_children_state(self, widget: tk.Widget, state: str) -> None:
        for child in widget.winfo_children():
            if isinstance(child, (tk.Entry, tk.Checkbutton)):
                child.config(state=state)
            self._set_entry_children_state(child, state)

    def _configure_control_dependencies(self) -> None:
        if not self._inputs_enabled:
            return

        desired_state = tk.NORMAL if self.reincarnation_var.get() else tk.DISABLED
        self.desired_level_entry.config(state=desired_state)

        hire_state = tk.NORMAL if self.hire_enabled_var.get() else tk.DISABLED
        self.hire_level_entry.config(state=hire_state)

        max_state = tk.NORMAL if self.max_iterations_enabled_var.get() else tk.DISABLED
        self.max_iterations_entry.config(state=max_state)

    @staticmethod
    def _read_positive_int(raw: str, label: str) -> int:
        try:
            value = int(raw.strip())
        except ValueError as exc:
            raise ValueError(f"{label} must be an integer.") from exc
        if value < 1:
            raise ValueError(f"{label} must be at least 1.")
        return value

    @staticmethod
    def _read_positive_float(raw: str, label: str) -> float:
        try:
            value = float(raw.strip())
        except ValueError as exc:
            raise ValueError(f"{label} must be a number.") from exc
        if value <= 0:
            raise ValueError(f"{label} must be greater than 0.")
        return value

    @staticmethod
    def _shorten(text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 3)] + "..."

    def _on_close(self) -> None:
        # Closing the tool window should not forcibly kill an external headless
        # run. If this GUI started an in-process session, request a safe stop.
        if self.session_handle is not None and self.session_handle.running:
            self.session_handle.stop()
        self.destroy()


if __name__ == "__main__":
    app = BotGui()
    app.mainloop()
