from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from typing import Literal

from PIL import Image, ImageTk

from crafting_bot.domain.models import AreaTarget, PointTarget

SelectionKind = Literal["point", "area"]


@dataclass(frozen=True)
class SelectionResult:
    kind: SelectionKind
    x: int
    y: int
    width: int | None = None
    height: int | None = None


class CalibrationSelectionWindow(tk.Tk):
    """Tiny Tk adapter for selecting one point or one rectangle on a screenshot."""

    def __init__(self, image: Image.Image, target_name: str, kind: SelectionKind, max_width: int = 1280, max_height: int = 820) -> None:
        super().__init__()
        self.title(f"Calibrate {kind}: {target_name}")
        self.kind = kind
        self.target_name = target_name
        self.source_image = image.convert("RGB")
        self.scale = min(max_width / self.source_image.width, max_height / self.source_image.height, 1.0)
        self.display_image = self.source_image.resize(
            (int(self.source_image.width * self.scale), int(self.source_image.height * self.scale)),
            getattr(Image, "Resampling", Image).LANCZOS,
        )
        self.photo = ImageTk.PhotoImage(self.display_image)
        self.result: SelectionResult | None = None
        self._start_x: int | None = None
        self._start_y: int | None = None
        self._current_item: int | None = None
        self._point_item: int | None = None

        self._build_ui()
        self.bind("<Return>", self._confirm)
        self.bind("<Escape>", self._cancel)
        self.bind("<BackSpace>", self._reset)

    def _build_ui(self) -> None:
        instructions = (
            "Left click to mark the point. Press Enter to save, Backspace to reset, Escape to cancel."
            if self.kind == "point"
            else "Drag the rectangle. Press Enter to save, Backspace to reset, Escape to cancel."
        )
        tk.Label(self, text=f"{self.target_name}: {instructions}", anchor="w").pack(fill=tk.X, padx=8, pady=(8, 4))
        self.canvas = tk.Canvas(self, width=self.display_image.width, height=self.display_image.height, cursor="crosshair")
        self.canvas.pack(padx=8, pady=(0, 8))
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)

        if self.kind == "point":
            self.canvas.bind("<Button-1>", self._mark_point)
        else:
            self.canvas.bind("<ButtonPress-1>", self._start_rect)
            self.canvas.bind("<B1-Motion>", self._drag_rect)
            self.canvas.bind("<ButtonRelease-1>", self._end_rect)

    def _to_original(self, value: int | float) -> int:
        return int(round(float(value) / self.scale))

    def _mark_point(self, event: tk.Event) -> None:
        x = max(0, min(self.display_image.width - 1, int(event.x)))
        y = max(0, min(self.display_image.height - 1, int(event.y)))
        if self._point_item is not None:
            self.canvas.delete(self._point_item)
        r = 5
        self._point_item = self.canvas.create_oval(x - r, y - r, x + r, y + r, outline="red", width=2)
        self.result = SelectionResult(kind="point", x=self._to_original(x), y=self._to_original(y))

    def _start_rect(self, event: tk.Event) -> None:
        self._start_x = max(0, min(self.display_image.width - 1, int(event.x)))
        self._start_y = max(0, min(self.display_image.height - 1, int(event.y)))
        if self._current_item is not None:
            self.canvas.delete(self._current_item)
        self._current_item = self.canvas.create_rectangle(
            self._start_x,
            self._start_y,
            self._start_x,
            self._start_y,
            outline="red",
            width=2,
        )

    def _drag_rect(self, event: tk.Event) -> None:
        if self._start_x is None or self._start_y is None or self._current_item is None:
            return
        x = max(0, min(self.display_image.width - 1, int(event.x)))
        y = max(0, min(self.display_image.height - 1, int(event.y)))
        self.canvas.coords(self._current_item, self._start_x, self._start_y, x, y)

    def _end_rect(self, event: tk.Event) -> None:
        if self._start_x is None or self._start_y is None:
            return
        x2 = max(0, min(self.display_image.width - 1, int(event.x)))
        y2 = max(0, min(self.display_image.height - 1, int(event.y)))
        x1 = min(self._start_x, x2)
        y1 = min(self._start_y, y2)
        x2 = max(self._start_x, x2)
        y2 = max(self._start_y, y2)
        width = max(1, self._to_original(x2) - self._to_original(x1))
        height = max(1, self._to_original(y2) - self._to_original(y1))
        self.result = SelectionResult(
            kind="area",
            x=self._to_original(x1),
            y=self._to_original(y1),
            width=width,
            height=height,
        )

    def _confirm(self, _event: tk.Event | None = None) -> None:
        if self.result is None:
            return
        self.destroy()

    def _cancel(self, _event: tk.Event | None = None) -> None:
        self.result = None
        self.destroy()

    def _reset(self, _event: tk.Event | None = None) -> None:
        self.result = None
        if self._current_item is not None:
            self.canvas.delete(self._current_item)
            self._current_item = None
        if self._point_item is not None:
            self.canvas.delete(self._point_item)
            self._point_item = None


def select_target(image: Image.Image, target_name: str, kind: SelectionKind) -> PointTarget | AreaTarget | None:
    window = CalibrationSelectionWindow(image=image, target_name=target_name, kind=kind)
    window.mainloop()
    result = window.result
    if result is None:
        return None
    if result.kind == "point":
        return PointTarget(name=target_name, x=result.x, y=result.y)
    if result.width is None or result.height is None:
        return None
    return AreaTarget(name=target_name, x=result.x, y=result.y, width=result.width, height=result.height)
