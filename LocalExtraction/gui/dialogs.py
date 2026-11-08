# LocalExtraction/gui/dialogs.py
"""The windows that open on top of the main one: the frame of every dialog, and the details of a
row. (The dialogs of the web project — its keys, its job, the check of its setup — are in
WebScraping/gui/dialogs.py.)"""

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional, Sequence, Tuple


class Dialog(tk.Toplevel):
    """A window that belongs to the main one and closes with Escape."""

    def __init__(self, parent: tk.Misc, title: str, size: str = ""):
        super().__init__(parent)
        self.title(title)
        if size:
            self.geometry(size)
        self.transient(parent.winfo_toplevel())
        self.bind("<Escape>", lambda event: self.destroy())
        self.body = ttk.Frame(self, padding=12)
        self.body.pack(fill="both", expand=True)


class DetailsDialog(Dialog):
    """Everything known about one row, as "name / value" lines that can be selected and copied."""

    def __init__(self, parent: tk.Misc, title: str, pairs: Sequence[Tuple[str, str]],
                 actions: Sequence[Tuple[str, Callable[[], None]]] = ()):
        super().__init__(parent, title, "760x520")
        text = tk.Text(self.body, wrap="word", relief="flat", padx=8, pady=6, font=("TkDefaultFont", 11))
        bar = ttk.Scrollbar(self.body, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=bar.set)
        text.tag_configure("name", font=("TkDefaultFont", 10, "bold"), foreground="#8c8c8c", spacing1=8)
        for name, value in pairs:
            text.insert("end", f"{name}\n", "name")
            text.insert("end", f"{value}\n")
        text.configure(state="disabled")
        text.grid(row=0, column=0, sticky="nsew")
        bar.grid(row=0, column=1, sticky="ns")
        buttons = ttk.Frame(self.body)
        buttons.grid(row=1, column=0, columnspan=2, sticky="e", pady=(10, 0))
        for label, action in actions:
            ttk.Button(buttons, text=label, command=lambda act=action: (act(), self.destroy())).pack(side="left", padx=4)
        ttk.Button(buttons, text="Close", command=self.destroy).pack(side="left", padx=4)
        self.body.rowconfigure(0, weight=1)
        self.body.columnconfigure(0, weight=1)


def ask_choice(parent: tk.Misc, title: str, message: str,
               choices: Sequence[Tuple[str, str, str]]) -> "Optional[str]":
    """A question with one button per answer, a line beside each saying what it does, and Cancel.
    `choices`: (key, button text, what it does). Returns the key chosen; None for Cancel, Escape or
    the window closed. It waits for the answer (the main window stays drawn meanwhile)."""
    dialog = Dialog(parent, title)
    dialog.resizable(False, False)
    chosen: list = [None]

    def choose(key: str) -> None:
        chosen[0] = key
        dialog.destroy()

    ttk.Label(dialog.body, text=message, wraplength=560, justify="left").pack(anchor="w", pady=(0, 12))
    first = None
    for key, label, detail in choices:
        row = ttk.Frame(dialog.body)
        row.pack(fill="x", pady=5)
        button = ttk.Button(row, text=label, width=30, command=lambda k=key: choose(k))
        button.pack(side="left", anchor="n")
        first = first or button
        ttk.Label(row, text=detail, wraplength=360, justify="left", foreground="#8c8c8c").pack(
            side="left", padx=(12, 0), fill="x", expand=True)
    ttk.Button(dialog.body, text="Cancel", command=dialog.destroy).pack(anchor="e", pady=(12, 0))
    dialog.update_idletasks()
    try:
        dialog.grab_set()  # answered before anything else of the program
    except tk.TclError:
        pass
    if first is not None:
        first.focus_set()
    dialog.wait_window()
    return chosen[0]
