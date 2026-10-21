# WebScraping/sources/__init__.py
"""Where candidates come from. Each source turns a query (or a DOI) into `Candidate` records and
nothing more — deciding what is worth fetching is screening's job, getting the file is fetch's.

`make` builds a source from its name in the job file (`search.sources`, `search.abstract_sources`)."""

from typing import Dict, List, Optional, Type

from WebScraping.http import PoliteClient
from WebScraping.sources.ads import ADS
from WebScraping.sources.arxiv import ArXiv
from WebScraping.sources.core import Core
from WebScraping.sources.crossref import Crossref
from WebScraping.sources.doaj import DOAJ
from WebScraping.sources.europepmc import EuropePMC
from WebScraping.sources.ieee import IEEE
from WebScraping.sources.jstage import JStage
from WebScraping.sources.openaire import OpenAIRE
from WebScraping.sources.openalex import OpenAlex
from WebScraping.sources.scopus import Scopus
from WebScraping.sources.semanticscholar import SemanticScholar
from WebScraping.sources.springernature import SpringerNature
from WebScraping.sources.wos import WebOfScience

CLASSES: Dict[str, Type] = {cls.name: cls for cls in (
    OpenAlex, ArXiv, Crossref, SemanticScholar, EuropePMC, OpenAIRE, Core, DOAJ, JStage, SpringerNature, Scopus,
    ADS, IEEE, WebOfScience)}


def make(name: str, client: PoliteClient, contact: str = "", arxiv_categories: Optional[List[str]] = None):
    """The source of that name, ready to search."""
    if name == "openalex":
        return OpenAlex(client, contact)
    if name == "arxiv":
        return ArXiv(client, arxiv_categories)
    return CLASSES[name](client, contact)
