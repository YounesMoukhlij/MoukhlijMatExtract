# LocalExtraction/gui/dialogs.py
"""The windows that open on top of the main one: the frame of every dialog, and the details of a
row. (The dialogs of the web project — its keys, its job, the check of its setup — are in
WebScraping/gui/dialogs.py.)"""

import tkinter as tk
from tkinter import ttk
from typing import Callable, Sequence, Tuple


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
        text.tag_configure("name", font=("TkDefaultFont", 10, "bold"), foreground="#555555", spacing1=8)
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
