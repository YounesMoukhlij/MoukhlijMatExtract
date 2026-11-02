# LocalExtraction/gui/delete_outputs.py
"""The "Delete outputs…" dialog: what a part wrote, a box to tick for each kind of output, and a
Delete button. Shared by the windows of the four parts and the hub (mme-gui)."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from pathlib import Path
from typing import Callable, Dict, Optional

from .. import outputs
from ..about import PROJECT_HOME

TITLE = "MoukhlijMatExtract"


class DeleteOutputsDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, part: str, home: Path = PROJECT_HOME,
                 on_close: Optional[Callable[[bool], None]] = None):
        """`on_close(deleted)` is called when the dialog closes, `deleted` true if anything was deleted."""
        super().__init__(parent)
        name, groups = outputs.PARTS[part]
        self.part, self.home, self.groups, self.on_close = part, Path(home), groups, on_close
        self.deleted = False
        self.title(f"Delete outputs — {name}")
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=f"Delete the outputs of {name}", font=("TkDefaultFont", 13, "bold")).pack(anchor="w")
        where = ("They are moved to the Trash, so they can be got back." if outputs.TO_TRASH else
                 "There is no Trash to move them to here: they are deleted for good.")
        ttk.Label(body, wraplength=520, justify="left",
                  text=f"Tick what to delete. {where} Your own PDFs, the job file and the API keys are never "
                       "touched.").pack(anchor="w", pady=(4, 12))

        self.ticks: Dict[str, tk.BooleanVar] = {}
        for group in groups:
            items = group.items(self.home)
            files, size = outputs.size_of(items)
            busy = outputs.in_use(part, group.key)
            var = tk.BooleanVar(value=False)
            self.ticks[group.key] = var
            row = ttk.Frame(body)
            row.pack(fill="x", pady=3)
            box = ttk.Checkbutton(row, text=group.label, variable=var, command=self._update)
            box.pack(anchor="w")
            if busy:
                state, note = "disabled", f"In use — {busy}."
            elif not items:
                state, note = "disabled", "Nothing there."
            else:
                state, note = "normal", f"{files} file{'s' if files != 1 else ''}, {outputs.readable_size(size)}"
            box.configure(state=state)
            ttk.Label(row, foreground="#888888", text=f"    {group.path(self.home)}  ·  {note}",
                      wraplength=520, justify="left").pack(anchor="w")

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(14, 0))
        self.delete_button = ttk.Button(buttons, text="Delete", command=self.delete, state="disabled")
        self.delete_button.pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.close).pack(side="right", padx=6)
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.grab_set()

    def chosen(self):
        return [group for group in self.groups if self.ticks[group.key].get()]

    def _update(self) -> None:
        self.delete_button.configure(state="normal" if self.chosen() else "disabled")

    def delete(self, confirm: bool = True) -> bool:
        groups = self.chosen()
        if not groups:
            return False
        busy = [(g, outputs.in_use(self.part, g.key)) for g in groups]
        busy = [(g, why) for g, why in busy if why]
        if busy:  # it started meanwhile
            messagebox.showinfo(TITLE, "\n".join(f"{g.label}: in use — {why}." for g, why in busy), parent=self)
            return False
        items = [item for group in groups for item in group.items(self.home)]
        files, size = outputs.size_of(items)
        where = "moved to the Trash" if outputs.TO_TRASH else "deleted for good (no Trash here)"
        listed = "\n".join(f"• {g.label}\n   {g.path(self.home)}" for g in groups)
        if confirm and not messagebox.askyesno(
                TITLE, f"Delete these outputs?\n\n{listed}\n\n{files} file{'s' if files != 1 else ''} "
                       f"({outputs.readable_size(size)}) will be {where}.", icon="warning", parent=self):
            return False
        failed = outputs.delete(items)
        self.deleted = True
        if failed:
            messagebox.showwarning(TITLE, "Some files could not be deleted:\n\n"
                                   + "\n".join(f"{path}: {why}" for path, why in failed[:10]), parent=self)
        elif confirm:
            messagebox.showinfo(TITLE, f"Done: {files} file{'s' if files != 1 else ''} {where}.", parent=self)
        self.close()
        return True

    def close(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        if self.on_close is not None:
            self.on_close(self.deleted)


def delete_outputs_button(parent: tk.Misc, part: str, before: Optional[Callable[[], None]] = None,
                          after: Optional[Callable[[bool], None]] = None) -> ttk.Button:
    """A "Delete outputs…" button that opens the dialog for `part`. `before()` is called before it
    opens (e.g. to let go of a file the window holds), `after(deleted)` once it is closed."""
    def open_dialog() -> None:
        if before is not None:
            before()
        DeleteOutputsDialog(parent, part, on_close=after)
    return ttk.Button(parent, text="Delete outputs…", command=open_dialog)
