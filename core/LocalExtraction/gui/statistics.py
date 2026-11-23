# LocalExtraction/gui/statistics.py
"""The “📊 Statistics…” button of a part's window, and the window it opens: the charts of the work done (each one's
finding in its title), read from the part's own files on a working thread, drawn one under the other.

    statistics_button(bar, part, source)   source() → (name in the file names, function giving the charts)

“Save the charts” writes every chart as a 300 dpi PNG into ~/MoukhlijMatExtract/Statistics/PNG/ and as an SVG into
~/MoukhlijMatExtract/Statistics/SVG/, named <source>_<chart>_<date and time> (LocalExtraction/charts.py). Nothing the
part wrote is changed. One window per part: asked again, the open one comes to the front."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, List, Optional, Tuple

from .. import charts as drawing
from ..stats import Chart
from . import design, layout, theme
from .widgets import Scrolled, WrapLabel, open_path

BUTTON_TEXT = "📊 Statistics…"
Source = Callable[[], Tuple[str, Callable[[], List[Chart]]]]
_POLL_MS = 100


def statistics_button(bar: tk.Misc, part: str, source: Source, side: str = "right") -> ttk.Button:
    """The button, packed in `bar`. `source` is asked when it is pressed: the window may have another job or folder by
    then."""
    def open_it() -> None:
        open_statistics(bar.winfo_toplevel(), part, source)
    button = ttk.Button(bar, text=BUTTON_TEXT, command=open_it)
    button.pack(side=side, padx=(6, 0))
    return button


def open_statistics(parent: tk.Misc, part: str, source: Source) -> Optional[tk.Misc]:
    from .single import open_once
    return open_once(f"statistics:{part}", f"The statistics of {part}", parent,
                     lambda: StatisticsWindow(parent, part, source))


class StatisticsWindow(tk.Toplevel):
    def __init__(self, parent: tk.Misc, part: str, source: Source):
        super().__init__(parent)
        self.part, self.source = part, source
        self.title(f"MoukhlijMatExtract · Statistics — {part}")
        layout.place(self, (900, 820), (720, 520), parent=parent)
        theme.apply(self)
        self.dark = theme.is_dark(self)
        design.header(self, "Statistics", part, compact=True, flow=False)
        # The buttons first, at the bottom: a short window shrinks the charts' area, never cuts them off.
        buttons = ttk.Frame(self, padding=(16, 6, 16, 10))
        buttons.pack(side="bottom", fill="x")
        self.refresh_button = ttk.Button(buttons, text="Refresh", command=self.refresh)
        self.refresh_button.pack(side="left")
        self.save_button = ttk.Button(buttons, text="Save the charts (PNG 300 dpi + SVG)", command=self.save,
                                      style="Current.TButton")
        self.save_button.pack(side="left", padx=(6, 0))
        self.folder_button = ttk.Button(buttons, text="Open the Statistics folder", command=self.open_folder)
        self.folder_button.pack(side="left", padx=(6, 0))
        ttk.Button(buttons, text="Close", command=self.destroy).pack(side="right")
        self.status = tk.StringVar(value="Reading the results …")
        WrapLabel(self, textvariable=self.status, padding=(16, 8, 16, 4)).pack(side="top", fill="x")
        self.area = Scrolled(self)
        self.area.pack(side="top", fill="both", expand=True, padx=(16, 4))
        self.charts: List[Chart] = []
        self.name = ""
        self._canvases: List[object] = []
        self._result: Optional[Tuple[str, object]] = None
        self._busy = False
        self.refresh()

    # ------------------------------------------------------------------------------------------- reading
    def refresh(self) -> None:
        """The charts read again from the part's files (on a working thread), then drawn."""
        if self._busy:
            return
        try:
            self.name, provider = self.source()
        except Exception as error:  # the window has no job or folder to read
            self.status.set(f"Nothing to show: {error}")
            return
        self._work("read", provider, "Reading the results …")

    def _work(self, kind: str, function: Callable[[], object], said: str) -> None:
        self._busy = True
        self.status.set(said)
        for button in (self.refresh_button, self.save_button):
            button.state(["disabled"])

        def run() -> None:
            try:
                self._result = (kind, function())
            except Exception as error:  # a file that cannot be read: said, the window stays
                self._result = ("error", error)
        threading.Thread(target=run, daemon=True, name=f"statistics-{kind}").start()
        self.after(_POLL_MS, self._poll)

    def _poll(self) -> None:
        if not self.winfo_exists():
            return
        if self._result is None:
            self.after(_POLL_MS, self._poll)
            return
        kind, value = self._result
        self._result, self._busy = None, False
        for button in (self.refresh_button, self.save_button):
            button.state(["!disabled"])
        if kind == "read":
            self._show(value)
        elif kind == "save":
            files = value
            self.status.set(f"✓ {len(self.charts)} charts saved: {len(files)} files in {drawing.folder()} "
                            "(PNG/ at 300 dpi, SVG/).")
        else:
            self.status.set(f"Something went wrong: {value}")

    def _show(self, found: List[Chart]) -> None:
        self.charts = list(found)
        for canvas in self._canvases:
            try:
                canvas.figure.clear()
                canvas.get_tk_widget().destroy()
            except tk.TclError:
                pass
        self._canvases = []
        for child in self.area.inner.winfo_children():
            child.destroy()
        if not self.charts:
            self.status.set(f"No statistics yet: run {self.part} first, then press Refresh.")
            self.save_button.state(["disabled"])
            return
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        self.update_idletasks()
        # As wide as the area (at 100 pixels an inch): a narrow screen shows whole charts, never cut at the right.
        inches = max(self.area.winfo_width() - 28, 520) / 100
        for chart in self.charts:
            figure = drawing.figure(chart, dark=self.dark, width=inches)
            figure.set_dpi(100)
            canvas = FigureCanvasTkAgg(figure, master=self.area.inner)
            canvas.draw()
            canvas.get_tk_widget().pack(side="top", anchor="w", pady=(0, 14))
            self._canvases.append(canvas)
        self.status.set(f"{len(self.charts)} charts from the files of {self.part}. Save them for an article: "
                        "300 dpi PNG and SVG, in ~/MoukhlijMatExtract/Statistics/.")

    # ------------------------------------------------------------------------------------------- saving
    def save(self) -> None:
        if not self.charts or self._busy:
            return
        charts, name = list(self.charts), self.name
        self._work("save", lambda: drawing.save(charts, name), "Saving the charts …")

    def open_folder(self) -> None:
        folder = drawing.folder()
        if not folder.is_dir():
            messagebox.showinfo("MoukhlijMatExtract", f"Nothing saved yet: press “Save the charts” first ({folder}).",
                                parent=self)
            return
        open_path(str(folder))
