from __future__ import annotations

import queue
import time
import tkinter as tk
from tkinter import messagebox
from tkinter.scrolledtext import ScrolledText

from crafting_bot.workers.rebuild_loop_worker import LoopGuiStatus, RebuildLoopWorker


class BotGui(tk.Tk):
    """Minimal GUI for the rebuild/reincarnation loop.

    The GUI does not implement bot logic. It only gathers loop settings, starts a
    RebuildLoopWorker, and displays loop progress.
    """

    def __init__(self) -> None:
        super().__init__()

        self.title("Crafting Idle Bot")
        self.geometry("760x540")
        self.minsize(700, 480)

        self.event_queue: queue.Queue[LoopGuiStatus] = queue.Queue()
        self.worker: RebuildLoopWorker | None = None

        self.desired_level_var = tk.StringVar(value="82")
        self.stuck_seconds_var = tk.StringVar(value="20")
        self.scan_interval_var = tk.StringVar(value="1.0")
        self.reincarnation_var = tk.BooleanVar(value=False)
        self.auto_train_var = tk.BooleanVar(value=True)
        self.hire_enabled_var = tk.BooleanVar(value=False)
        self.hire_level_var = tk.StringVar(value="45")

        self.running_var = tk.StringVar(value="Stopped")
        self.screen_var = tk.StringVar(value="UNKNOWN")
        self.level_var = tk.StringVar(value="-")
        self.ready_var = tk.StringVar(value="unknown")
        self.cycles_var = tk.StringVar(value="0")
        self.timer_var = tk.StringVar(value="0.0s")
        self.last_action_var = tk.StringVar(value="-")

        self._build_ui()
        self._poll_events()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        root = tk.Frame(self, padx=12, pady=12)
        root.pack(fill=tk.BOTH, expand=True)

        controls = tk.LabelFrame(root, text="Loop controls", padx=10, pady=8)
        controls.pack(fill=tk.X)

        row1 = tk.Frame(controls)
        row1.pack(fill=tk.X)

        tk.Label(row1, text="Desired level").pack(side=tk.LEFT)
        tk.Entry(row1, textvariable=self.desired_level_var, width=8).pack(side=tk.LEFT, padx=(6, 14))

        tk.Label(row1, text="Stuck seconds").pack(side=tk.LEFT)
        tk.Entry(row1, textvariable=self.stuck_seconds_var, width=6).pack(side=tk.LEFT, padx=(6, 14))

        tk.Label(row1, text="Scan interval").pack(side=tk.LEFT)
        tk.Entry(row1, textvariable=self.scan_interval_var, width=6).pack(side=tk.LEFT, padx=(6, 14))

        row2 = tk.Frame(controls)
        row2.pack(fill=tk.X, pady=(8, 0))

        tk.Checkbutton(
            row2,
            text="Reincarnate after completing desired level",
            variable=self.reincarnation_var,
        ).pack(side=tk.LEFT)

        tk.Checkbutton(
            row2,
            text="Auto-train missing digits when expected level is safe",
            variable=self.auto_train_var,
        ).pack(side=tk.LEFT, padx=(18, 0))

        row3 = tk.Frame(controls)
        row3.pack(fill=tk.X, pady=(8, 0))

        tk.Checkbutton(
            row3,
            text="Run hire/setup cycle once per climb",
            variable=self.hire_enabled_var,
        ).pack(side=tk.LEFT)

        tk.Label(row3, text="Hire/setup level").pack(side=tk.LEFT, padx=(18, 0))
        tk.Entry(row3, textvariable=self.hire_level_var, width=8).pack(side=tk.LEFT, padx=(6, 0))

        note = tk.Label(
            controls,
            anchor="w",
            text=(
                "Without reincarnation: stops when the visible level reaches Desired level. "
                "With reincarnation: completes Desired level, reincarnates when the next level is visible, then repeats until stopped."
            ),
        )
        note.pack(fill=tk.X, pady=(8, 0))

        button_row = tk.Frame(root)
        button_row.pack(fill=tk.X, pady=(10, 0))

        self.start_button = tk.Button(button_row, text="Start loop", width=14, command=self._start_bot)
        self.start_button.pack(side=tk.LEFT)

        self.stop_button = tk.Button(
            button_row,
            text="Stop",
            width=14,
            command=self._stop_bot,
            state=tk.DISABLED,
        )
        self.stop_button.pack(side=tk.LEFT, padx=(8, 0))

        status_box = tk.LabelFrame(root, text="Status", padx=10, pady=8)
        status_box.pack(fill=tk.X, pady=(12, 8))

        self._add_status_row(status_box, 0, "Runner", self.running_var)
        self._add_status_row(status_box, 1, "Screen", self.screen_var)
        self._add_status_row(status_box, 2, "Level", self.level_var)
        self._add_status_row(status_box, 3, "Ready", self.ready_var)
        self._add_status_row(status_box, 4, "Progress", self.cycles_var)
        self._add_status_row(status_box, 5, "Same level timer", self.timer_var)
        self._add_status_row(status_box, 6, "Last action", self.last_action_var)

        log_box = tk.LabelFrame(root, text="Log", padx=8, pady=8)
        log_box.pack(fill=tk.BOTH, expand=True)

        self.log = ScrolledText(log_box, height=12, state=tk.DISABLED)
        self.log.pack(fill=tk.BOTH, expand=True)

    def _add_status_row(self, parent: tk.Widget, row: int, label: str, variable: tk.StringVar) -> None:
        tk.Label(parent, text=label, anchor="w", width=18).grid(row=row, column=0, sticky="w", pady=2)
        tk.Label(parent, textvariable=variable, anchor="w").grid(row=row, column=1, sticky="w", pady=2)
        parent.grid_columnconfigure(1, weight=1)

    def _start_bot(self) -> None:
        if self.worker and self.worker.running:
            return

        try:
            desired_level = self._read_positive_int(self.desired_level_var.get(), "Desired level")
            stuck_seconds = self._read_positive_float(self.stuck_seconds_var.get(), "Stuck seconds")
            scan_interval = self._read_positive_float(self.scan_interval_var.get(), "Scan interval")
            hire_level = self._read_positive_int(self.hire_level_var.get(), "Hire/setup level")
        except ValueError as exc:
            messagebox.showerror("Invalid loop setting", str(exc))
            return

        self.worker = RebuildLoopWorker(
            self.event_queue,
            desired_level=desired_level,
            reincarnation_enabled=self.reincarnation_var.get(),
            stuck_seconds=stuck_seconds,
            scan_interval_seconds=scan_interval,
            auto_train_missing_digits=self.auto_train_var.get(),
            hire_enabled=self.hire_enabled_var.get(),
            hire_setup_level=hire_level,
        )
        self.worker.start()
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self._set_inputs_enabled(False)

    def _stop_bot(self) -> None:
        if self.worker:
            self.worker.stop()
        self.stop_button.config(state=tk.DISABLED)

    def _poll_events(self) -> None:
        while True:
            try:
                status = self.event_queue.get_nowait()
            except queue.Empty:
                break

            self._apply_status(status)

        self.after(100, self._poll_events)

    def _apply_status(self, status: LoopGuiStatus) -> None:
        self.running_var.set("Running" if status.running else "Stopped")
        self.screen_var.set(status.screen)
        self.level_var.set(status.level)
        self.ready_var.set(status.ready)
        self.cycles_var.set(status.cycles)
        self.timer_var.set(f"{status.same_level_seconds:.1f}s")
        self.last_action_var.set(status.last_action)

        if status.running:
            self.start_button.config(state=tk.DISABLED)
            self.stop_button.config(state=tk.NORMAL)
        else:
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
            self._set_inputs_enabled(True)

        if status.message:
            self._append_log(status.message)

    def _append_log(self, text: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        line = f"[{timestamp}] {text}\n"

        self.log.config(state=tk.NORMAL)
        self.log.insert(tk.END, line)
        self.log.see(tk.END)
        self.log.config(state=tk.DISABLED)

    def _set_inputs_enabled(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        for child in self.winfo_children():
            self._set_entry_children_state(child, state)

    def _set_entry_children_state(self, widget: tk.Widget, state: str) -> None:
        for child in widget.winfo_children():
            if isinstance(child, (tk.Entry, tk.Checkbutton)):
                child.config(state=state)
            self._set_entry_children_state(child, state)

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

    def _on_close(self) -> None:
        if self.worker:
            self.worker.stop()
        self.destroy()


if __name__ == "__main__":
    app = BotGui()
    app.mainloop()
