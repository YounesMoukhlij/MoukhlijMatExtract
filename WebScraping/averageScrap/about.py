# WebScraping/about.py
"""What Project 2 says of itself, and where it reads and writes unless told otherwise."""

import logging
import os
from pathlib import Path

DESCRIPTION = (
    "Searches the literature online (OpenAlex, arXiv, Crossref and twenty-two more), keeps the papers worth reading, fetches a legal "
    "copy of each and extracts materials and their activation energies, conductivities and diffusion "
    "coefficients from it."
)

# Relative to ~/MoukhlijMatExtract, where every command works. (The fetched PDFs go where the job
# file says: WebScraping/papers unless it says otherwise.) The job file is in its configs/.
DEFAULT_JOB = os.path.join("configs", "sse.yaml")
DEFAULT_OUTPUT = os.path.join("WebScraping", "web_output")
_PAPERS, _OUTPUT = "papers", "web_output"


def output_for(job) -> str:
    """The results folder of a job, beside its PDF folder: WebScraping/web_output for WebScraping/papers, and
    WebScraping/web_output_<name> for WebScraping/papers_<name>. Each job its own database: the papers of one job
    extracted into another job's database would mix two corpora."""
    folder = os.path.normpath(job.fetch.folder)
    if folder == os.path.normpath(os.path.join("WebScraping", _PAPERS)):
        return DEFAULT_OUTPUT
    parent, name = os.path.split(folder)
    suffix = name[len(_PAPERS) + 1:] if name.startswith(_PAPERS + "_") and len(name) > len(_PAPERS) + 1 else name
    return os.path.join(parent, f"{_OUTPUT}_{suffix}")


def output_of(job_path: str) -> str:
    """output_for the job in this file; DEFAULT_OUTPUT when it cannot be read (the step then says why)."""
    from .job import load_job
    try:
        return output_for(load_job(job_path)) if job_path else DEFAULT_OUTPUT
    except (OSError, ValueError, TypeError):
        return DEFAULT_OUTPUT


# The job files ship with the package (the repository's configs/: sse, cathode, anode and one per family of solid
# electrolytes) and are copied into ~/MoukhlijMatExtract/configs/ when missing (mme_home.populate, at the start of
# every command): an installed copy searches out of the box. Edit the copies to change a search.
SHIPPED_JOB = "sse.yaml"
FAMILY_JOBS = ("garnet_nasicon", "garnet", "nasicon", "lisicon", "lgps", "argyrodite", "sulfide_glass", "perovskite",
               "antiperovskite", "halide", "complex_hydride", "beta_alumina", "lipon", "nitride", "fluoride",
               "mixed_anion", "oxide_chemistry", "oxide_structure", "polymer", "hybrid", "multivalent")


def _shipped_jobs() -> tuple:
    from mme_home import CONFIGS, shipped
    return tuple(shipped(CONFIGS))


SHIPPED_JOBS = _shipped_jobs()


def ensure_default_job(path: str = DEFAULT_JOB) -> str:
    """Return the working job file. When it is one of the shipped jobs (sse.yaml, a family's), its folder gets every
    shipped job that is missing, and the file itself is made from the one shipped; another missing name is made from
    sse.yaml. Returns `path` either way; never raises."""
    target = Path(path)
    if target.name in SHIPPED_JOBS:
        for name in SHIPPED_JOBS:
            _copy_starter(target.with_name(name), name)
    if not target.exists():
        _copy_starter(target, target.name if target.name in SHIPPED_JOBS else SHIPPED_JOB)
    return path


def starter_job(path: str) -> str:
    """A job file named before it exists — a fresh install's configs/halide.yaml, say — made from the one the package
    ships (with the others, ensure_default_job). A path that is not a shipped job is left as it is: the step then
    says the file is missing. Returns `path`."""
    if path and (path == DEFAULT_JOB or (not os.path.exists(path) and os.path.basename(path) in SHIPPED_JOBS)):
        ensure_default_job(path)
    return path


def _copy_starter(target: Path, shipped: str) -> None:
    """Copies the job file `shipped` with the package to `target`, unless `target` exists; never raises."""
    from mme_home import CONFIGS, copy
    if copy(CONFIGS, shipped, target):
        logging.info(f"Created a starter job file at {target} (copied from the one shipped with MoukhlijMatExtract). "
                     "Edit it to change what the web search looks for.")
