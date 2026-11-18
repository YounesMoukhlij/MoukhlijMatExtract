# LocalExtraction/gui/widgets.py
"""The few building blocks the windows are made of: a read-only log, a sortable table, a folder row."""

import os
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Callable, List, Optional, Sequence, Tuple

# One row of a table: (its identifier, the cell texts in column order, the tags that colour it).
Row = Tuple[str, Sequence[str], Sequence[str]]
_MAX_LOG_LINES = 5000
_FLUSH_MS = 50  # how often the log shows the lines written since (in one go)


class Stopped(Exception):
    """Stop was pressed while a task was still waiting for its turn."""


def open_path(path: str) -> None:
    """Shows a file or a folder with the program the system uses for it."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
    elif os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", path])


class Pausable:
    """Pause / Resume, and the "no internet" notice, for a panel whose step runs with `self.stop_event`
    (a runcontrol.RunControl) and says where it is in `self.status`. Progress lines go through
    `show_status`, so that they do not hide the notice while it stands."""

    PAUSED = "Paused — what was under way finishes, then it waits. Press Resume to go on."

    def pause_button(self, parent: tk.Misc) -> ttk.Button:
        self._pause = ttk.Button(parent, text="Pause", command=self.toggle_pause, state="disabled")
        self._held, self._offline = "", False
        return self._pause

    def set_pause_button(self, busy: bool) -> None:
        from .theme import CURRENT
        paused = busy and self.stop_event.paused
        self._pause.configure(text="Resume" if paused else "Pause", state="normal" if busy else "disabled",
                              style=CURRENT if paused else "TButton")  # blue while paused
        if not busy:
            self._offline = False

    def toggle_pause(self) -> None:
        if not self.running() or self.stop_event.is_set():
            return
        if self.stop_event.paused:
            self.stop_event.resume()
            self.activity.write("--- Resumed.")
            self.on_resume()
        else:
            self._held = self._held if self._notice() else self.status.get()
            self.stop_event.pause()
            self.activity.write("--- Paused: what was under way finishes, then it waits. Press Resume to go on.")
            self.on_pause()
        self.set_pause_button(True)
        self._refresh_status()

    def on_pause(self) -> None:
        """What else pausing takes (a step that runs as its own program is told)."""

    def on_resume(self) -> None:
        """What else resuming takes."""

    def show_status(self, text: str) -> None:
        self._held = text
        if not self._notice():
            self.status.set(text)

    def connection_changed(self, online: bool) -> None:
        if not self.running() or online != self._offline:
            return
        if not online and not self._notice():
            self._held = self.status.get()
        self._offline = not online
        self._refresh_status()

    def _notice(self) -> str:
        from ..runcontrol import WAITING
        if self.stop_event.paused:
            return self.PAUSED
        return WAITING if self._offline else ""

    def _refresh_status(self) -> None:
        self.status.set(self._notice() or self._held or self.status.get())


class WrapLabel(ttk.Label):
    """A label for a sentence: it wraps at the width it is given, however the window is resized,
    instead of asking for the width of its whole text. Pack or grid it so that it fills its row."""

    def __init__(self, parent: tk.Misc, **options: object):
        options.setdefault("wraplength", 420)
        options.setdefault("justify", "left")
        super().__init__(parent, **options)
        self.bind("<Configure>", self._fit)

    def _fit(self, event: "tk.Event") -> None:
        width = max(event.width - 6, 120)
        if abs(width - int(self.cget("wraplength"))) > 4:
            self.configure(wraplength=width)


class LogPane(ttk.Frame):
    """Lines of text that only the program writes; it keeps to the end unless the reader scrolled up."""

    def __init__(self, parent: tk.Misc, height: int = 8, clearable: bool = False,
                 also_clear: Optional[Callable[[], None]] = None):
        """`clearable`: a "Clear the log" button above the lines; `also_clear`: what else it empties (the
        window's own log strip)."""
        super().__init__(parent)
        self._also_clear = also_clear
        row = 0
        if clearable:
            tools = ttk.Frame(self)
            tools.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(4, 2))
            self.clear_button = ttk.Button(tools, text="Clear the log", command=self.reset)
            self.clear_button.pack(side="right")
            row = 1
        self.text = tk.Text(self, height=height, wrap="word", state="disabled", relief="flat",
                            font=("TkFixedFont", 10), padx=6, pady=4)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=bar.set)
        self.text.grid(row=row, column=0, sticky="nsew")
        bar.grid(row=row, column=1, sticky="ns")
        self.rowconfigure(row, weight=1)
        self.columnconfigure(0, weight=1)
        self._pending: List[str] = []
        self._flush_at: Optional[str] = None

    def write(self, message: str) -> None:
        """Adds a line. Lines are put in the text in batches, every _FLUSH_MS at most: a step that writes
        thousands of lines (a long search) must not keep the window busy writing them one by one — the
        buttons, Stop among them, would wait behind them."""
        self._pending.append(message.rstrip("\n") + "\n")
        if self._flush_at is None:
            self._flush_at = self.after(_FLUSH_MS, self._flush)

    def _flush(self) -> None:
        self._flush_at = None
        if not self._pending or not self.winfo_exists():
            return
        lines_in, self._pending = self._pending[-_MAX_LOG_LINES:], []
        at_end = self.text.yview()[1] >= 0.999
        self.text.configure(state="normal")
        self.text.insert("end", "".join(lines_in))
        lines = int(self.text.index("end-1c").split(".")[0])
        if lines > _MAX_LOG_LINES:
            self.text.delete("1.0", f"{lines - _MAX_LOG_LINES}.0")
        self.text.configure(state="disabled")
        if at_end:
            self.text.see("end")

    def contents(self) -> str:
        """Everything written so far, the lines not shown yet included."""
        return self.text.get("1.0", "end") + "".join(self._pending)

    def reset(self) -> None:
        """The "Clear the log" button: this log, and what `also_clear` names, emptied. Only what is shown:
        no result, ledger or file is touched; what a step writes next is shown as before."""
        self.clear()
        if self._also_clear is not None:
            self._also_clear()

    def clear(self) -> None:
        self._pending = []
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")


def _sort_key(text: str) -> Tuple[int, float, str]:
    """Numbers before words, and as numbers; an empty answer last."""
    if text in ("", "NONE"):
        return 2, 0.0, ""
    try:
        return 0, float(text), ""
    except ValueError:
        return 1, 0.0, text.lower()


class Table(ttk.Frame):
    """A table of text rows. Click a heading to sort by that column (numbers as numbers), click
    again to reverse; double-click or press Return on a row to open it."""

    def __init__(self, parent: tk.Misc, columns: Sequence[Tuple[str, str, int]],
                 on_open: Optional[Callable[[str], None]] = None, stretch: str = "", height: int = 10):
        super().__init__(parent)
        self.columns = [name for name, _, _ in columns]
        self._headings = {name: heading for name, heading, _ in columns}
        self.tree = ttk.Treeview(self, columns=self.columns, show="headings", selectmode="extended", height=height)
        for name, heading, width in columns:
            self.tree.heading(name, text=heading, anchor="w", command=lambda n=name: self.sort_by(n))
            self.tree.column(name, width=width, minwidth=36, anchor="w", stretch=(name == stretch))
        vertical = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self._rows: List[Row] = []
        self._sorted: Optional[Tuple[str, bool]] = None  # (column, reversed)
        self._on_open = on_open
        from .design import stripes
        stripes(self.tree)  # every other row shaded
        if on_open is not None:
            self.tree.bind("<Double-1>", self._opened)
            self.tree.bind("<Return>", self._opened)

    def tag(self, name: str, **look: str) -> None:
        self.tree.tag_configure(name, **look)

    def _opened(self, event: "tk.Event") -> None:
        # A double click on a heading sorts twice; it does not open the row that happens to have the focus.
        if event.type == tk.EventType.ButtonPress and self.tree.identify_region(event.x, event.y) != "cell":
            return
        row = self.tree.focus()
        if row and self._on_open is not None:
            self._on_open(row)

    def fill(self, rows: Sequence[Row]) -> None:
        """Shows these rows, in the order chosen by the last click on a heading, and keeps the
        selection on the rows that are still there."""
        self._rows = list(rows)
        self._show()

    def _show(self) -> None:
        rows = self._rows
        if self._sorted is not None:
            column, reverse = self._sorted
            index = self.columns.index(column)
            rows = sorted(rows, key=lambda row: _sort_key(str(row[1][index])), reverse=reverse)
        selected, top = set(self.tree.selection()), self.tree.yview()[0]
        self.tree.delete(*self.tree.get_children())
        for index, (identifier, values, tags) in enumerate(rows):
            self.tree.insert("", "end", iid=identifier, values=list(values),
                             tags=[*tags, "stripe"] if index % 2 else list(tags))
        kept = [identifier for identifier, _, _ in rows if identifier in selected]
        if kept:
            self.tree.selection_set(kept)
        self.tree.yview_moveto(top)

    def update_row(self, row: Row) -> None:
        """Changes one row where it stands, without redrawing the others."""
        identifier, values, tags = row
        for index, (known, _, _) in enumerate(self._rows):
            if known == identifier:
                self._rows[index] = row
                break
        if self.tree.exists(identifier):
            striped = "stripe" in self.tree.item(identifier, "tags")
            self.tree.item(identifier, values=list(values), tags=[*tags, "stripe"] if striped else list(tags))

    def sort_by(self, column: str) -> None:
        reverse = self._sorted is not None and self._sorted[0] == column and not self._sorted[1]
        self._sorted = (column, reverse)
        for name in self.columns:
            mark = (" ▼" if reverse else " ▲") if name == column else ""
            self.tree.heading(name, text=self._headings[name] + mark)
        self._show()

    def selected(self) -> List[str]:
        return list(self.tree.selection())

    def __len__(self) -> int:
        return len(self._rows)


class FolderRow(ttk.Frame):
    """A label, the path, and a button to pick it: a folder, or a file of one kind."""

    def __init__(self, parent: tk.Misc, label: str, value: str, pick: str = "folder",
                 file_types: Sequence[Tuple[str, str]] = (), on_change: Optional[Callable[[], None]] = None,
                 label_width: int = 0):
        super().__init__(parent)
        self.var = tk.StringVar(value=value)
        self._pick, self._file_types, self._on_change = pick, list(file_types), on_change
        ttk.Label(self, text=label, width=label_width or len(label) + 1).grid(row=0, column=0, sticky="w")
        self.entry = ttk.Entry(self, textvariable=self.var)
        self.entry.grid(row=0, column=1, sticky="ew", padx=4)
        self.entry.bind("<Return>", lambda event: self._changed())
        self.entry.bind("<FocusOut>", lambda event: self._changed())
        ttk.Button(self, text="Browse…", command=self._browse, width=9).grid(row=0, column=2)
        self.columnconfigure(1, weight=1)
        self._last = value

    def get(self) -> str:
        return self.var.get().strip()

    def set(self, value: str) -> None:
        self.var.set(value)
        self._last = value

    def _changed(self) -> None:
        if self.get() != self._last:
            self._last = self.get()
            if self._on_change is not None:
                self._on_change()

    def _browse(self) -> None:
        start = self.get() or "."
        if self._pick == "folder":
            path = filedialog.askdirectory(title="Choose a folder", initialdir=start if os.path.isdir(start) else ".")
        else:
            path = filedialog.askopenfilename(title="Choose a file", filetypes=self._file_types or [("All files", "*")],
                                              initialdir=os.path.dirname(start) or ".")
        if path:
            # Inside the project a path is shown the short way, as the terminal commands write it.
            relative = os.path.relpath(path)
            self.var.set(relative if not relative.startswith("..") else path)
            self._changed()


class Scrolled(ttk.Frame):
    """A frame whose content (`inner`) scrolls up and down, with the bar or the mouse wheel. The bar shows only when
    the content is taller than the frame: on a large screen nothing changes; on a small one nothing is cut off."""

    def __init__(self, parent: tk.Misc):
        super().__init__(parent)
        # Its size comes from its window or its pane, never from what it holds: else the bar, shown when the content
        # is taller, asked for height, the window grew, the bar went, the window shrank — a loop that never settled.
        self.pack_propagate(False)
        background = ttk.Style().lookup("TFrame", "background") or None
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0, background=background, height=1)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        # Where the bar goes while it is hidden: an empty strip as wide, so the content keeps its width either way.
        # Else showing the bar narrowed the content, text wrapped onto more lines and the bar stayed; hiding it widened
        # the content, the text took fewer lines and the bar went — without end.
        self.gap = ttk.Frame(self, width=self.bar.winfo_reqwidth())
        self.gap.pack(side="right", fill="y")
        self.inner = ttk.Frame(self.canvas)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda event: self._resized())
        self.canvas.bind("<Configure>", self._canvas_resized)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        # The wheel scrolls this frame only while the pointer is over it. Moving onto one of its widgets is
        # reported to the frame as leaving it: the wheel is let go only when the pointer is really out.
        self.bind("<Enter>", lambda event: self._wheel(True))
        self.bind("<Leave>", self._leave)
        self.bind("<Destroy>", lambda event: self._wheel(False) if event.widget is self else None)

    def scrolls(self) -> bool:
        """Whether the content is taller than the frame (the bar is shown)."""
        return bool(self.bar.winfo_manager())

    def _canvas_resized(self, event: "tk.Event") -> None:
        try:
            self.canvas.itemconfigure(self._window, width=event.width)
        except tk.TclError:  # the window is closing: Tk may still deliver a resize to a canvas already gone
            return
        self._resized()

    def _resized(self) -> None:
        try:
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
            taller = self.inner.winfo_reqheight() > self.canvas.winfo_height() + 1
            if taller and not self.bar.winfo_manager():
                self.gap.pack_forget()
                self.bar.pack(side="right", fill="y", before=self.canvas)
            elif not taller and self.bar.winfo_manager():
                self.bar.pack_forget()
                self.gap.pack(side="right", fill="y", before=self.canvas)
                self.canvas.yview_moveto(0)
        except tk.TclError:  # the window is closing (see _canvas_resized)
            pass

    def _inside(self, x_root: int, y_root: int) -> bool:
        widget = self.winfo_containing(x_root, y_root)
        return widget is not None and str(widget).startswith(str(self))

    def _leave(self, event: "tk.Event") -> None:
        if not self._inside(event.x_root, event.y_root):
            self._wheel(False)

    def _wheel(self, on: bool) -> None:
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            if on:
                self.canvas.bind_all(sequence, self._scroll)
            else:
                self.canvas.unbind_all(sequence)

    def _scroll(self, event: "tk.Event") -> None:
        if not self._inside(event.x_root, event.y_root) or not self.scrolls():
            return
        if getattr(event, "num", 0) in (4, 5):  # Linux
            steps = -1 if event.num == 4 else 1
        else:  # Windows (steps of 120) and macOS (small steps)
            steps = -int(event.delta / 120) if abs(event.delta) >= 120 else -event.delta
        self.canvas.yview_scroll(steps, "units")
