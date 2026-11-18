# SelectingTopMaterial/materials_project.py
"""The ranked materials beside their Materials Project entries: what computation says of each composition —
its stability (energy above the convex hull), band gap and space group — with a link to its page.

    mme-rank --materials-project        # writes materials_project.csv beside the ranking

A free API key is needed (MP_API_KEY in ~/MoukhlijMatExtract/.env, or the "API keys…" window):
https://next-gen.materialsproject.org/api. One request per composition, through the polite client (spaced,
retried, never more than the site allows).

A composition is matched by its reduced formula (Li12P2S10Cl2 is Li6PS5Cl); among several entries of it, the most
stable one is kept. A doped or non-stoichiometric composition (Li6.4La3Zr1.4Ta0.6O12) has no entry of its own: its
row says so. The ICSD, which needs a paid licence, is not asked."""

from __future__ import annotations

import csv
import logging
import os
import re
from pathlib import Path
from typing import Dict, Iterable, Optional

BASE = "https://api.materialsproject.org/materials/summary/"
PAGE = "https://next-gen.materialsproject.org/materials/"
FIELDS = "material_id,formula_pretty,energy_above_hull,band_gap,symmetry,theoretical"
KEY = "MP_API_KEY"
COLUMNS = ("component", "rank", "material", "energy_eV", "reduced_formula", "mp_id", "mp_url", "energy_above_hull_eV",
           "band_gap_eV", "space_group", "theoretical", "note")
FILE = "materials_project.csv"
_FORMULA = re.compile(r"(?:[A-Z][a-z]?(?:\d+(?:\.\d+)?)?|[()\[\]](?:\d+(?:\.\d+)?)?)+")


def reduced(formula: str) -> Optional[str]:
    """The reduced formula of a composition (pymatgen), None when it is no plain composition (a name, an x)."""
    text = "".join(str(formula or "").split())
    if not _FORMULA.fullmatch(text):  # only element symbols, numbers and brackets: no x, no name
        return None
    try:
        from pymatgen.core import Composition, Element
        if not all(Element.is_valid_symbol(symbol) for symbol in re.findall(r"[A-Z][a-z]?", text)):
            return None  # "LLZO" is a name, not L2ZO
        composition = Composition(text)
        return composition.reduced_formula if composition.num_atoms > 0 else None
    except Exception:  # pymatgen raises several kinds for a text that is not a formula
        return None


def lookup(formulas: Iterable[str], client, key: str) -> Dict[str, Optional[dict]]:
    """The most stable Materials Project entry of each formula's composition (None: no entry), by reduced formula;
    one request per composition."""
    from WebScraping.averageScrap.http import HttpError
    found: Dict[str, Optional[dict]] = {}
    for formula in formulas:
        name = reduced(formula)
        if name is None or name in found:
            continue
        try:
            data = client.get_json(BASE, params={"formula": name, "_fields": FIELDS, "_limit": 50},
                                   headers={"X-API-KEY": key})
        except HttpError as error:
            if error.status in (401, 403):
                raise
            logging.warning(f"Materials Project: {name} could not be asked ({error}).")
            found[name] = None
            continue
        entries = [e for e in (data or {}).get("data") or [] if e.get("material_id")]
        found[name] = min(entries, key=lambda e: (e.get("energy_above_hull") is None,
                                                  e.get("energy_above_hull") or 0.0)) if entries else None
    return found


def link(selections, out_dir: Path, client=None, key: Optional[str] = None) -> Optional[Path]:
    """materials_project.csv in `out_dir`: every ranked material of every component beside its entry. None (and
    nothing asked) without a key."""
    key = os.environ.get(KEY, "") if key is None else key
    if not key:
        logging.warning(f"Materials Project: no {KEY} — set one (free: https://next-gen.materialsproject.org/api) in "
                        "the API keys window or ~/MoukhlijMatExtract/.env; nothing was asked.")
        return None
    if client is None:
        from WebScraping.averageScrap.http import PoliteClient
        client = PoliteClient(os.environ.get("MME_EMAIL", ""))
    materials = [(component, m) for component, selection in selections.items() for m in selection.materials]
    try:
        entries = lookup((m.material for _, m in materials), client, key)
    except Exception as error:  # the key refused: said once, nothing written
        logging.warning(f"Materials Project refused the key ({error}); nothing was written.")
        return None
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / FILE
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for component, m in materials:
            name = reduced(m.material)
            entry = entries.get(name) if name else None
            row = {"component": component, "rank": m.rank, "material": m.material, "energy_eV": m.energy_eV,
                   "reduced_formula": name or ""}
            if entry:
                row.update(mp_id=entry["material_id"], mp_url=PAGE + entry["material_id"],
                           energy_above_hull_eV=entry.get("energy_above_hull"), band_gap_eV=entry.get("band_gap"),
                           space_group=(entry.get("symmetry") or {}).get("symbol", ""),
                           theoretical=entry.get("theoretical"))
            else:
                row["note"] = ("no entry for this composition (doped or non-stoichiometric compositions seldom have "
                               "one)" if name else "not a plain composition: not asked")
            writer.writerow(row)
    matched = sum(1 for _, m in materials if entries.get(reduced(m.material) or ""))
    logging.info(f"Materials Project: {matched} of {len(materials)} ranked materials have an entry — {path}")
    return path
