# SelectingTopMaterial/__init__.py
"""Selecting the top materials: reads the activation energies MoukhlijMatExtract extracted and ranks
the materials by them.

    Ea < 0.25 eV    Superionic
    Ea < 0.30 eV    Performant
    Ea < 0.40 eV    Acceptable
    otherwise       Rejected

    python -m SelectingTopMaterial            (from the project folder; the window: python -m SelectingTopMaterial gui)

It reads the results folders (LocalExtraction/local_output/, WebScraping/web_output/) and writes its own tables into
SelectingTopMaterial/results/; it changes nothing of the project. From Python:

    from SelectingTopMaterial import PROJECT_ROOT, Criteria, discover, select_from
    ranking = select_from(discover(PROJECT_ROOT), Criteria.load())
    for material in ranking.top:
        print(material.rank, material.material, material.energy_class.name, material.energy_eV)
"""

from .about import PACKAGE_DIR, PROJECT_ROOT, VERSION as __version__
from .criteria import POLICIES, Criteria, CriteriaError, EnergyClass
from .loader import discover, load
from .models import DatabaseReport, Filters, Measurement, RankedMaterial, Selection
from .selection import select, select_from

__all__ = ["Criteria", "CriteriaError", "DatabaseReport", "EnergyClass", "Filters", "Measurement", "POLICIES",
           "PACKAGE_DIR", "PROJECT_ROOT", "RankedMaterial", "Selection", "discover", "load", "select",
           "select_from", "__version__"]
