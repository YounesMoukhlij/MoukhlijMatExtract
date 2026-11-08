# Evaluation/about.py
"""The name of the part, what it reads and where it writes."""


from LocalExtraction.about import PROJECT_HOME

NAME = "Evaluation"
PROJECT_ROOT = PROJECT_HOME

# The databases of parts 1 and 2, the most trusted first (as Ranking and Classification read them).
DEFAULT_SOURCES = (PROJECT_ROOT / "LocalExtraction" / "local_output", PROJECT_ROOT / "WebScraping" / "web_output")
DEFAULT_DIR = PROJECT_ROOT / "Evaluation"
DEFAULT_SHEET = DEFAULT_DIR / "annotation.xlsx"
DEFAULT_SCORES = DEFAULT_DIR / "scores"

# The properties scored: table of the database -> (its value column, the unit of that column, compared
# on a log scale?). Conductivities and diffusion coefficients span decades, so 1.16e-3 and 1.17e-3 are
# compared as ratios; activation energies as differences.
PROPERTIES = {
    "activation_energy": ("activation_energy_eV", "eV", False),
    "ionic_conductivity": ("ionic_conductivity_S_cm", "S/cm", True),
    "electronic_conductivity": ("electronic_conductivity_S_cm", "S/cm", True),
    "diffusion_coefficient": ("diffusion_coefficient_cm2_s", "cm2/s", True),
}

# Two values are the same value when they differ by no more than this.
LINEAR_TOLERANCE = (0.01, 0.002)   # 1 % of the value, or 0.002 eV, whichever is larger
LOG_TOLERANCE = 0.0086             # in log10: a ratio of 2 %

VERDICTS = ("correct", "partly", "wrong")
COMPONENTS = ("bulk", "grain_boundary", "total", "surface")
ORIGINS = ("experimental", "simulation")
ERROR_TYPES = (
    "wrong material",            # the value is real but belongs to another material
    "wrong value or unit",       # a digit, a sign, an exponent or the unit was misread
    "wrong property",            # e.g. a band gap or a formation energy read as an activation energy
    "wrong ion or species",      # e.g. Co diffusion, electron transfer — not the conducting ion
    "not a result of a material",  # a cited value, a target, a comparison, a fit parameter
    "wrong component",           # bulk / grain boundary / total mixed up
    "wrong origin",              # experimental / simulation mixed up
    "duplicate",                 # the same value of the same material listed twice
    "other",
)
