# database.py
"""Reading the database back, as tables: what the window previews, and where anything that compares
or ranks materials later should start. Every cell is text as it was written — an answer the paper
does not give is the word NONE, never a blank."""

import os
from typing import Dict, Optional

import pandas as pd


def table(output_dir: str, name: str) -> pd.DataFrame:
    """One table of the database ("papers", "activation_energy", ...); empty when the database
    does not have it (yet)."""
    try:
        return pd.read_csv(os.path.join(output_dir, f"{name}.csv"), dtype=str, keep_default_na=False)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def activation_energies(output_dir: str, origin: Optional[str] = None) -> pd.DataFrame:
    """The activation energies, each with where its paper came from (`origin`: local or web) and
    the paper's title; only those of one origin when asked."""
    energies, papers = table(output_dir, "activation_energy"), table(output_dir, "papers")
    if energies.empty or "paper_id" not in energies:
        return pd.DataFrame()
    about = papers.drop_duplicates("paper_id").set_index("paper_id") if "paper_id" in papers else pd.DataFrame()
    energies["origin"] = _origins(energies["paper_id"].map(about["origin"])) if "origin" in about else "local"
    energies["title"] = energies["paper_id"].map(about["title"]).fillna("NONE") if "title" in about else "NONE"
    return energies[energies["origin"] == origin].reset_index(drop=True) if origin else energies


def _origins(column: pd.Series) -> pd.Series:
    """A paper came from the web or from a folder of this computer: whatever is not marked "web"
    (a database of an earlier version marks nothing for its local papers) is local."""
    return column.where(column == "web", "local")


def overview(output_dir: str) -> Dict[str, Dict[str, int]]:
    """How much the database holds, by origin of the paper:
    {"papers": {"local": 23, "web": 185}, "activation_energies": {"local": 61, "web": 315}}."""
    papers, energies = table(output_dir, "papers"), activation_energies(output_dir)
    origins = _origins(papers["origin"]) if "origin" in papers else pd.Series(["local"] * len(papers), dtype=str)
    return {"papers": {origin: int(count) for origin, count in origins.value_counts().items()},
            "activation_energies": {origin: int(count) for origin, count in energies["origin"].value_counts().items()}
            if len(energies) else {}}
