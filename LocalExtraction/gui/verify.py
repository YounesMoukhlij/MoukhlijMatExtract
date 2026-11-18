# LocalExtraction/gui/verify.py
"""The Verify tab: a person checks the extracted activation energies, one by one, against the page of the PDF they
were read from.

    ┌ values to check ───────────────────┐ ┌ the value ────────────────────────────────┐
    │ ! Li3PS4      0.05 eV  page 4  …   │ │ Li3PS4 — 0.05 eV, page 4 of "…"            │
    │   Li6PS5Cl    0.22 eV  page 3  …   │ │ Arrhenius: inconsistent, the paper gives …  │
    │ ✓ LLZO        0.30 eV  page 6  …   │ │ [✓ Correct] [✗ Wrong] [✎ Correct it…] [↺]  │
    └────────────────────────────────────┘ │ ┌ the page, the sentence marked ─────────┐ │
                                           │ └───────────────────────────────────────┘ │

The values most worth checking come first: those the Arrhenius cross-check disputes, those the extraction flagged
(needs_check), then the lowest energies — the ones that would lead a ranking. Keys: c correct, w wrong, e correct it,
u undo, arrows to move. The checks are kept in ~/MoukhlijMatExtract/Verification/ (LocalExtraction.verification);
the ranking reads them: a value marked wrong takes no part, a corrected one takes part as corrected, and
"Verified values only" ranks the checked ones alone."""

from __future__ import annotations

import base64
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable, Dict, Optional, Sequence

from .. import database
from ..arrhenius import INCONSISTENT, NOT_CHECKABLE, cross_check
from ..verification import CORRECT, CORRECTED, WRONG, Verifications, row_id
from . import theme
from .widgets import Table, WrapLabel, open_path

SHOW = ("To check — the most worth it first", "Not checked", "Checked", "Marked wrong", "All")
_COLUMNS = (("mark", "", 26), ("material", "material", 170), ("ea", "Ea (eV)", 64), ("kind", "kind", 110),
            ("component", "component", 92), ("origin", "origin", 92), ("attribution", "result of", 76),
            ("page", "page", 44), ("check", "checked", 80), ("arrhenius", "Arrhenius", 96), ("title", "article", 240))
_MARK = {CORRECT: "✓", CORRECTED: "✎", WRONG: "✗"}
KINDS = ("", "arrhenius", "migration_barrier", "bvse", "local_hop", "vtf", "unspecified")
COMPONENTS = ("", "bulk", "grain boundary", "total", "surface")
ORIGINS = ("", "experimental", "simulation")
ATTRIBUTIONS = ("", "this work", "cited")


def _number(text: str) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return float("inf")


class VerifyView(ttk.Frame):
    """The tab. `output_dir()` gives the database folder; `pdf_folders()` the folders its PDFs are in."""

    def __init__(self, parent: tk.Misc, output_dir: Callable[[], str], pdf_folders: Callable[[], Sequence[str]],
                 verifications: Optional[Path] = None):
        super().__init__(parent, padding=(0, 6, 0, 0))
        self._output_dir, self._pdf_folders, self._home = output_dir, pdf_folders, verifications
        self.rows: Dict[str, Dict[str, str]] = {}
        self.store: Optional[Verifications] = None
        self.checks = {}
        self._page_image = None
        colours = theme.palette(self)

        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 4))
        ttk.Label(bar, text="Show").pack(side="left")
        self.show_var = tk.StringVar(value=SHOW[0])
        shown = ttk.Combobox(bar, values=SHOW, textvariable=self.show_var, state="readonly", width=32)
        shown.pack(side="left", padx=4)
        shown.bind("<<ComboboxSelected>>", lambda event: self.fill())
        ttk.Label(bar, text="containing").pack(side="left", padx=(8, 0))
        self.search_var = tk.StringVar()
        search = ttk.Entry(bar, textvariable=self.search_var, width=18)
        search.pack(side="left", padx=4)
        search.bind("<KeyRelease>", lambda event: self.fill())
        ttk.Button(bar, text="Refresh", command=self.show).pack(side="right")
        self.progress = tk.StringVar(value="")
        # On its own line, across the tab: beside the filters it wrapped into a column that pushed the list out.
        WrapLabel(self, textvariable=self.progress, foreground=colours["muted"]).pack(fill="x", pady=(0, 4))

        panes = ttk.PanedWindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True)

        def share(event) -> None:  # the list asks for all its columns: the page and the buttons get their part
            if event.width > 1:
                panes.sashpos(0, int(event.width * 0.42))
                panes.unbind("<Configure>")
        panes.bind("<Configure>", share)
        left = ttk.Frame(panes)
        panes.add(left, weight=3)
        self.table = Table(left, _COLUMNS, stretch="title", height=14)
        self.table.pack(fill="both", expand=True)
        self.table.tag("wrong", foreground="#b3261e")
        self.table.tag("checked", foreground="#1a7f37")
        self.table.tag("disputed", foreground="#d97706")
        self.table.tree.bind("<<TreeviewSelect>>", lambda event: self._selected())
        for key, action in (("c", lambda: self.mark(CORRECT)), ("w", lambda: self.mark(WRONG)),
                            ("e", self.correct_it), ("u", self.undo)):
            self.table.tree.bind(f"<KeyPress-{key}>", lambda event, a=action: a())

        right = ttk.Frame(panes, padding=(10, 0, 0, 0))
        panes.add(right, weight=4)
        # The details above, the buttons and the page below, with a line to drag between them; the buttons head the
        # lower part, so they stay in view wherever the line is.
        stack = ttk.PanedWindow(right, orient="vertical")
        stack.pack(fill="both", expand=True)
        about = ttk.Frame(stack)
        stack.add(about, weight=1)
        lower = ttk.Frame(stack)
        stack.add(lower, weight=3)
        lower.columnconfigure(0, weight=1)
        lower.rowconfigure(2, weight=1)
        self.details = tk.Text(about, height=12, wrap="word", relief="flat", padx=8, pady=6, state="disabled",
                               font=("TkDefaultFont", 11))
        scroll = ttk.Scrollbar(about, orient="vertical", command=self.details.yview)
        self.details.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.details.tag_configure("head", font=("TkDefaultFont", 13, "bold"), foreground=colours["accent"])
        self.details.tag_configure("muted", foreground=colours["muted"])
        self.details.tag_configure("warn", foreground="#d97706")
        self.details.tag_configure("number", background="#fff2a8", foreground="#1f2328")
        self.details.pack(side="left", fill="both", expand=True)
        buttons = ttk.Frame(lower)
        buttons.grid(row=0, column=0, sticky="ew", pady=(6, 6))
        # The verdicts on one line, undoing and the PDF on the next: every button stays in view in a narrow pane.
        self.buttons = [ttk.Button(buttons, text="✓ Correct (c)", command=lambda: self.mark(CORRECT)),
                        ttk.Button(buttons, text="✗ Wrong (w)", command=lambda: self.mark(WRONG)),
                        ttk.Button(buttons, text="✎ Correct it… (e)", command=self.correct_it)]
        for index, button in enumerate(self.buttons):
            button.pack(side="left", padx=(0 if index == 0 else 4, 0))
        more = ttk.Frame(lower)
        more.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        self.buttons += [ttk.Button(more, text="↺ Undo (u)", command=self.undo),
                         ttk.Button(more, text="Open the PDF", command=self.open_pdf)]
        self.buttons[-2].pack(side="left")
        self.buttons[-1].pack(side="left", padx=(4, 0))
        ttk.Label(more, text="keys: c, w, e, u · arrows to move", foreground=colours["muted"]).pack(side="left", padx=10)
        page = ttk.Frame(lower)
        page.grid(row=2, column=0, sticky="nsew")
        dragged = {"by_hand": False}

        def place_line(event=None) -> None:
            """The details as tall as they ask, but the buttons always whole with some of the page under them; once
            the line is dragged, it stays where it was put."""
            height = stack.winfo_height()
            if dragged["by_hand"] or height <= 1:
                return
            room_below = buttons.winfo_reqheight() + more.winfo_reqheight() + 12 + 80
            wanted = max(60, min(about.winfo_reqheight(), height - room_below))
            if abs(stack.sashpos(0) - wanted) > 1:
                stack.sashpos(0, wanted)
        stack.bind("<Configure>", place_line, add="+")
        stack.bind("<ButtonRelease-1>", lambda event: dragged.update(by_hand=True), add="+")
        self.canvas = tk.Canvas(page, highlightthickness=0, background="#e8e8e8")
        down = ttk.Scrollbar(page, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=down.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        down.pack(side="right", fill="y")
        self._buttons(False)

    # ------------------------------------------------------------------
    def folder(self) -> Path:
        return Path(self._output_dir() or ".")

    def show(self) -> None:
        """Reads the database and its checks again."""
        folder = self.folder()
        energies = database.table(str(folder), "activation_energy")
        papers = database.table(str(folder), "papers")
        about = {}
        if "paper_id" in papers:
            for paper in papers.fillna("").to_dict("records"):
                about[str(paper.get("paper_id", ""))] = paper
        self.rows = {}
        for row in energies.fillna("").astype(str).to_dict("records") if len(energies) else []:
            paper = about.get(row.get("paper_id", ""), {})
            row["title"] = str(paper.get("title", "") or row.get("title", ""))
            row["doi"] = str(paper.get("doi", ""))
            row["filename"] = str(paper.get("filename", "") or row.get("paper_id", ""))
            self.rows[row_id(row)] = row
        self.store = Verifications.of(folder, self._home)
        self.checks = cross_check(folder)
        self.fill()

    def _state(self, key: str) -> str:
        verdict = self.store.get(key) if self.store is not None else None
        return verdict.verdict if verdict else ""

    def fill(self) -> None:
        wanted, text = self.show_var.get(), self.search_var.get().strip().lower()
        chosen = []
        for key, row in self.rows.items():
            state = self._state(key)
            if wanted == SHOW[0] and state or wanted == SHOW[1] and state or wanted == SHOW[2] and not state \
                    or wanted == SHOW[3] and state != WRONG:
                continue
            if text and text not in f"{row.get('material_formula')} {row.get('title')} {row.get('sentence')}".lower():
                continue
            chosen.append(key)
        if wanted == SHOW[0]:  # the most worth checking first
            def priority(key: str):
                row, check = self.rows[key], self.checks.get(key)
                return (0 if check is not None and check.status == INCONSISTENT else 1,
                        0 if str(row.get("needs_check", "")).lower().startswith("yes") else 1,
                        _number(row.get("activation_energy_eV")), row.get("paper_id", ""), row.get("page", ""))
            chosen.sort(key=priority)
        self.table.fill([self._row(key) for key in chosen])
        counts = self.store.counts() if self.store is not None else {}
        done = sum(counts.values()) if counts else 0
        total = len(self.rows)
        share = f" ({100 * done / total:.1f} %)" if total else ""
        self.progress.set(f"{done:,} of {total:,} values checked{share} · {counts.get(CORRECT, 0)} correct, "
                          f"{counts.get(CORRECTED, 0)} corrected, {counts.get(WRONG, 0)} wrong · {len(chosen):,} shown"
                          if total else f"No activation energy in {self.folder()} yet.")
        if chosen and not self.table.selected():
            self.table.tree.selection_set(chosen[0])
            self.table.tree.focus(chosen[0])
        self._selected()

    def _row(self, key: str):
        row, check, state = self.rows[key], self.checks.get(key), self._state(key)
        tags = ("wrong",) if state == WRONG else ("checked",) if state else \
            ("disputed",) if check is not None and check.status == INCONSISTENT else ()
        arrhenius = "" if check is None or check.status == NOT_CHECKABLE else check.status
        flag = "!" if str(row.get("needs_check", "")).lower().startswith("yes") else ""
        return (key, [_MARK.get(state, flag), row.get("material_formula", ""), row.get("activation_energy_eV", ""),
                      row.get("energy_kind", ""), row.get("transport_component", ""), row.get("data_origin", ""),
                      row.get("attribution", ""), row.get("page", ""), state or "–", arrhenius, row.get("title", "")],
                tags)

    def current(self) -> Optional[str]:
        chosen = self.table.tree.focus() or next(iter(self.table.selected()), "")
        return chosen if chosen in self.rows else None

    def _buttons(self, on: bool) -> None:
        for button in self.buttons:
            button.configure(state="normal" if on else "disabled")

    def _selected(self) -> None:
        key = self.current()
        self._buttons(key is not None)
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        if key is None:
            self.details.configure(state="disabled")
            self._draw_page(None)
            return
        row, check = self.rows[key], self.checks.get(key)
        verdict = self.store.get(key) if self.store is not None else None
        self.details.insert("end", f"{row.get('material_formula')} — {row.get('activation_energy_eV')} eV\n", "head")
        self.details.insert("end", f"page {row.get('page')} of “{row.get('title') or row.get('paper_id')}”"
                                   + (f" · doi {row['doi']}" if row.get("doi") else "") + "\n", "muted")
        self.details.insert("end", f"{row.get('energy_kind') or 'kind not given'} · {row.get('transport_component')} · "
                                   f"{row.get('data_origin')} · {row.get('attribution')} · confidence "
                                   f"{row.get('confidence')}\n", "muted")
        if str(row.get("needs_check", "")).lower().startswith("yes"):
            self.details.insert("end", f"The extraction asks for a look: {row['needs_check'][5:]}\n", "warn")
        if check is not None and check.status != NOT_CHECKABLE:
            self.details.insert("end", f"Arrhenius: {check.text}\n", "warn" if check.status == INCONSISTENT else "muted")
        if verdict is not None:
            fixed = ", ".join(f"{f} → {v}" for f, v in verdict.corrections.items())
            self.details.insert("end", f"Checked: {verdict.verdict}{' (' + fixed + ')' if fixed else ''}"
                                       f"{' — ' + verdict.note if verdict.note else ''}\n", "muted")
        sentence = row.get("sentence", "")
        number = row.get("activation_energy_eV", "")
        self.details.insert("end", "“")
        start = self.details.index("end-1c")
        self.details.insert("end", sentence)
        self.details.insert("end", "”\n")
        for form in {number, number.rstrip("0").rstrip(".") if "." in number else number}:
            if form:
                at = self.details.search(form, start, "end")
                if at:
                    self.details.tag_add("number", at, f"{at}+{len(form)}c")
                    break
        self.details.configure(state="disabled")
        self._draw_page(key)

    # ------------------------------------------------------------------
    def pdf(self, key: str) -> Optional[Path]:
        row = self.rows.get(key, {})
        names = [n for n in (row.get("filename"), row.get("paper_id")) if n]
        for folder in self._pdf_folders() or ():
            for name in names:
                path = Path(folder) / name
                if path.is_file():
                    return path
        return None

    def _draw_page(self, key: Optional[str]) -> None:
        self.canvas.delete("all")
        self._page_image = None
        if key is None:
            return
        path = self.pdf(key)
        row = self.rows[key]
        if path is None:
            self.canvas.create_text(12, 12, anchor="nw", text="The PDF of this paper is not in its folder: the page "
                                                              "cannot be shown.", fill="#555555")
            return
        try:
            import pymupdf as fitz
            with fitz.open(str(path)) as document:
                number = int(float(row.get("page") or 1))
                page = document[max(0, min(number - 1, len(document) - 1))]
                width = max(self.canvas.winfo_width(), 420)
                zoom = (width - 20) / page.rect.width
                picture = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
                marks = self._marks(page, row)
                self._page_image = tk.PhotoImage(data=base64.b64encode(picture.tobytes("png")).decode("ascii"))
        except Exception as error:  # a damaged PDF must not stop the checking
            self.canvas.create_text(12, 12, anchor="nw", text=f"The page cannot be shown: {error}", fill="#555555")
            return
        self.canvas.create_image(10, 10, anchor="nw", image=self._page_image)
        for rect in marks:
            x0, y0, x1, y1 = (c * zoom + 10 for c in (rect.x0, rect.y0, rect.x1, rect.y1))
            self.canvas.create_rectangle(x0 - 2, y0 - 2, x1 + 2, y1 + 2, outline="#d97706", width=2)
        self.canvas.configure(scrollregion=(0, 0, self._page_image.width() + 20, self._page_image.height() + 20))
        if marks:  # the sentence in view
            top = max(0.0, (marks[0].y0 * zoom - 80) / max(self._page_image.height(), 1))
            self.canvas.yview_moveto(top)

    @staticmethod
    def _marks(page, row: Dict[str, str]) -> list:
        """Where the value's sentence is on the page: its first words, else the number."""
        words = row.get("sentence", "").split()
        for length in (8, 5):
            if len(words) >= length:
                found = page.search_for(" ".join(words[:length]))
                if found:
                    return found
        number = row.get("activation_energy_eV", "")
        return page.search_for(number) if number else []

    # ------------------------------------------------------------------
    def _after_change(self, key: str) -> None:
        """The table again, the next value to check selected."""
        order = list(self.table.tree.get_children())
        following = order[order.index(key) + 1] if key in order and order.index(key) + 1 < len(order) else None
        self.fill()
        if following and self.table.tree.exists(following):
            self.table.tree.selection_set(following)
            self.table.tree.focus(following)
            self.table.tree.see(following)
        elif self.table.tree.exists(key):
            self.table.tree.selection_set(key)
            self.table.tree.focus(key)
        self._selected()

    def mark(self, verdict: str) -> None:
        key = self.current()
        if key is None or self.store is None:
            return
        self.store.set(self.rows[key], verdict)
        self._after_change(key)

    def undo(self) -> None:
        key = self.current()
        if key is None or self.store is None:
            return
        self.store.clear(key)
        self._after_change(key)

    def correct_it(self) -> None:
        key = self.current()
        if key is None or self.store is None:
            return
        CorrectionDialog(self, self.rows[key], lambda fields, note: self._corrected(key, fields, note))

    def _corrected(self, key: str, fields: Dict[str, str], note: str) -> bool:
        try:
            self.store.set(self.rows[key], CORRECTED, fields, note)
        except ValueError:
            messagebox.showerror("Verify", "The activation energy must be a number in eV (for example 0.31).",
                                 parent=self)
            return False
        self._after_change(key)
        return True

    def open_pdf(self) -> None:
        key = self.current()
        path = self.pdf(key) if key else None
        if path is None:
            messagebox.showinfo("Verify", "The PDF of this paper is not in its folder.", parent=self)
            return
        open_path(str(path))


class CorrectionDialog(tk.Toplevel):
    """What the value really is: its material, number, kind, component, origin and attribution, and a note."""

    def __init__(self, parent: tk.Misc, row: Dict[str, str], on_save: Callable[[Dict[str, str], str], bool]):
        super().__init__(parent)
        self.title("Correct the value")
        self.transient(parent.winfo_toplevel())
        self.bind("<Escape>", lambda event: self.destroy())
        self.on_save = on_save
        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        from .design import website_line
        website_line(self)
        ttk.Label(body, text="Put right what the extraction read wrong; leave the rest as it is.",
                  foreground="#8c8c8c").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self.vars: Dict[str, tk.StringVar] = {}
        fields = (("material_formula", "Material (formula)", None), ("activation_energy_eV", "Activation energy (eV)", None),
                  ("energy_kind", "Kind of energy", KINDS), ("transport_component", "Component", COMPONENTS),
                  ("data_origin", "Origin", ORIGINS), ("attribution", "Result of", ATTRIBUTIONS))
        for line, (name, label, choices) in enumerate(fields, start=1):
            ttk.Label(body, text=label).grid(row=line, column=0, sticky="w", pady=2, padx=(0, 10))
            var = tk.StringVar(value=row.get(name, ""))
            self.vars[name] = var
            widget = ttk.Combobox(body, values=choices, textvariable=var, width=30) if choices else \
                ttk.Entry(body, textvariable=var, width=33)
            widget.grid(row=line, column=1, sticky="w", pady=2)
        ttk.Label(body, text="Note").grid(row=len(fields) + 1, column=0, sticky="nw", pady=2)
        self.note = tk.Text(body, width=40, height=3, wrap="word")
        self.note.grid(row=len(fields) + 1, column=1, sticky="w", pady=2)
        buttons = ttk.Frame(body)
        buttons.grid(row=len(fields) + 2, column=0, columnspan=2, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Save", command=self.save).pack(side="right", padx=6)

    def save(self) -> None:
        if self.on_save({name: var.get() for name, var in self.vars.items()}, self.note.get("1.0", "end").strip()):
            self.destroy()


def verify_tab(book: ttk.Notebook, output_dir: Callable[[], str], pdf_folders: Callable[[], Sequence[str]]) -> VerifyView:
    """Adds the Verify tab to a window's notebook; it reads the database when it is first shown, and again each time."""
    view = VerifyView(book, output_dir, pdf_folders)
    book.add(view, text="Verify")
    book.bind("<<NotebookTabChanged>>", lambda event: view.show() if book.select() == str(view) else None, add="+")
    return view


__all__ = ["VerifyView", "CorrectionDialog", "verify_tab"]
