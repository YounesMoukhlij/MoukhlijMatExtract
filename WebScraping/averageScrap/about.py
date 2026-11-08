# WebScraping/about.py
"""What Project 2 says of itself, and where it reads and writes unless told otherwise."""

import logging
import os
import shutil
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
# A ready-made job (the solid-state-electrolyte queries) ships with the package: when the working
# folder has no configs/sse.yaml, a starter copy is made from it, so an installed copy searches out
# of the box. Edit the copy to change the search.
SHIPPED_JOB = "default_job.yaml"


def ensure_default_job(path: str = DEFAULT_JOB) -> str:
    """Return the working job file. If it is missing, create a starter copy from the one shipped with
    the package (so a fresh install works at once). Returns `path` either way; never raises."""
    target = Path(path)
    if target.exists():
        return path
    try:
        from importlib import resources
        source = resources.files("WebScraping.averageScrap").joinpath(SHIPPED_JOB)
        if source.is_file():
            with resources.as_file(source) as real:
                if Path(real).resolve() != target.resolve():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(real, target)
                    logging.info(f"Created a starter job file at {target} (copied from the one shipped with "
                                 "MoukhlijMatExtract). Edit it to change what the web search looks for.")
    except (ModuleNotFoundError, FileNotFoundError, OSError) as error:
        logging.debug(f"Could not create a starter job file at {target}: {error}")
    return path
