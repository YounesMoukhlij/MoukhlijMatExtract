# WebScraping/about.py
"""What Project 2 says of itself, and where it reads and writes unless told otherwise."""

import os

DESCRIPTION = (
    "Searches the literature online (OpenAlex, arXiv, Crossref and eleven more), keeps the papers worth reading, fetches a legal "
    "copy of each and extracts materials and their activation energies, conductivities and diffusion "
    "coefficients from it."
)

# Relative to the project root, where the commands are run from. (The fetched PDFs go where the
# job file says: WebScraping/papers unless it says otherwise.)
DEFAULT_JOB = os.path.join("WebScraping", "configs", "sse.yaml")
DEFAULT_OUTPUT = os.path.join("WebScraping", "web_output")
