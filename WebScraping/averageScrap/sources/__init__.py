# WebScraping/sources/__init__.py
"""Where candidates come from. Each source turns a query (or a DOI) into `Candidate` records and
nothing more — deciding what is worth fetching is screening's job, getting the file is fetch's.

`make` builds a source from its name in the job file (`search.sources`, `search.abstract_sources`)."""

from typing import Dict, List, Optional, Type

from WebScraping.averageScrap.http import PoliteClient
from WebScraping.averageScrap.sources.ads import ADS
from WebScraping.averageScrap.sources.arxiv import ArXiv
from WebScraping.averageScrap.sources.core import Core
from WebScraping.averageScrap.sources.crossref import Crossref
from WebScraping.averageScrap.sources.doaj import DOAJ
from WebScraping.averageScrap.sources.europepmc import EuropePMC
from WebScraping.averageScrap.sources.ieee import IEEE
from WebScraping.averageScrap.sources.jstage import JStage
from WebScraping.averageScrap.sources.openaire import OpenAIRE
from WebScraping.averageScrap.sources.openalex import OpenAlex
from WebScraping.averageScrap.sources.scopus import Scopus
from WebScraping.averageScrap.sources.semanticscholar import SemanticScholar
from WebScraping.averageScrap.sources.springernature import SpringerNature
from WebScraping.averageScrap.sources.wos import WebOfScience

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
