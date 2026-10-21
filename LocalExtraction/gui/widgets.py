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

    def __init__(self, parent: tk.Misc, height: int = 8):
        super().__init__(parent)
        self.text = tk.Text(self, height=height, wrap="word", state="disabled", relief="flat",
                            font=("TkFixedFont", 10), padx=6, pady=4)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=bar.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        bar.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

    def write(self, message: str) -> None:
        at_end = self.text.yview()[1] >= 0.999
        self.text.configure(state="normal")
        self.text.insert("end", message.rstrip("\n") + "\n")
        lines = int(self.text.index("end-1c").split(".")[0])
        if lines > _MAX_LOG_LINES:
            self.text.delete("1.0", f"{lines - _MAX_LOG_LINES}.0")
        self.text.configure(state="disabled")
        if at_end:
            self.text.see("end")

    def clear(self) -> None:
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
        for identifier, values, tags in rows:
            self.tree.insert("", "end", iid=identifier, values=list(values), tags=list(tags))
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
            self.tree.item(identifier, values=list(values), tags=list(tags))

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
