# LocalExtraction/config.py

import re
from typing import Dict, List, Pattern, Tuple

# Generic numeric fragment: plain decimals, python-style scientific notation ("1.2e-3"),
# and "coefficient x 10^exponent" scientific notation ("1.2x10^-3", "1.2×10−3"), including
# the unicode minus sign (U+2212) and the en dash that PDF text extraction produces for the
# exponent's sign.
# The lookbehind stops a match starting inside a longer number or right after "±" (so "216±31 meV"
# yields 216, not the uncertainty 31); an optional trailing "±err" is consumed and ignored.
#
# A power of ten also stands alone ("10−4 S/cm", "10^-4"). PDF text has no superscripts, so read
# digit by digit "10−4 S/cm" would be 4 S/cm. But a bare "10−N" is written exactly like a range
# ("10–20 mS/cm"). With a caret or a one-digit exponent it can only be a power — nobody writes a
# range downwards — and that is all NUM accepts. NUM_MAGNITUDE also takes a two-digit exponent, for
# the quantities quoted as bare orders of magnitude that small (conductivities, diffusion
# coefficients); there normalizer._readings keeps whichever reading is physically possible. It also
# takes the space a PDF sometimes puts after the lost superscript's sign ("10- 4 S cm-1").
_DECIMAL = r'[-−]?\d+(?:\.\d+)?(?:\s*(?:[eE][-−+]?\d+|[xX×\*]\s*10\^?[-−–]?\d+))?'
_UNCERTAINTY = r'(?:\s*(?:±|\+/-|\+-)\s*\d+(?:\.\d+)?)?'
NUM = rf'(?<![\d.±])(10\^[-−–]?\d+|10[-−–]\d(?!\d)|{_DECIMAL}){_UNCERTAINTY}'
# A conductivity or a diffusion coefficient spans many orders of magnitude, and its power of ten
# comes out of a PDF in many shapes: "10−12", "10- 4", "10 –4", "1.06×10 –4", "5·10−9" and "5.10-9"
# (a point for the multiplication sign).
_TIMES_TEN = r'[xX×\*·⋅]\s*10(?:\^?\s?[-−–]\s?\d{1,2}(?!\d)|\^?\d+)'
_POINT_TIMES_TEN = r'[1-9]\d*(?:\.\d+)?\.10\^?[-−–]\d{1,2}(?!\d)'
NUM_MAGNITUDE = (rf'(?<![\d.±])(10\^[-−–]?\d+|10\s?[-−–]\s?\d{{1,2}}(?!\d)|{_POINT_TIMES_TEN}'
                 rf'|[-−]?\d+(?:\.\d+)?(?:\s*(?:[eE][-−+]?\d+|{_TIMES_TEN}))?){_UNCERTAINTY}')


def _per(numerator: str, denominator: str) -> str:
    """Pattern for a "numerator per denominator" unit the ways papers print it: "S/cm", "S / cm",
    "S cm−1", "S·cm–1", "S.cm-1", "S cm^-1" — and "S cm1", where the PDF dropped the exponent's
    minus sign. normalizer._canonical_unit folds them all back onto "S/cm"."""
    gap = rf'[\s{chr(0xAD)}]*'  # whitespace, or the invisible soft hyphen a PDF leaves at a line break
    return (rf'{numerator}{gap}(?:/{gap}{denominator}(?![\w^])'
            rf'|[·⋅.]?{gap}{denominator}(?:{gap}\^?{gap}[-−–]{gap}1|1)(?!\d))')


_SIEMENS_PER_CM = _per(r'(?:m|μ|µ|u)?S', 'cm')
_AREA_PER_SECOND = _per(r'c?m\^?2', r's(?:ec)?')
# An energy of one hop: per particle (eV, meV) or per mole ("kJ/mol", "kJ mol−1", "kJ per mol").
# Not an energy per atom or per length ("25 meV/atom" is a stability, "0.01 eV/Å" a force).
_ENERGY = (rf'(?:meV|eV|{_per("k(?:J|cal)", "mol")}|k(?:J|cal)\s+per\s+mol)'
           r'(?![A-Za-z])(?!\s*(?:/|per\s)\s*(?:atom|f\.?\s?u|Å|A\b|nm|cell|site)|\s*Å|\s*atom)')

# Bounded, non-greedy "skip up to N characters" used between a keyword and its value. Digits
# are deliberately NOT excluded — a chemical formula routinely sits between the keyword and the
# value ("bulk modulus of Li7La3Zr2O12 was found to be 150 GPa") and formulas contain digits.
# Non-greedy backtracking still prefers the closest number+unit match, since every shorter
# candidate gap is tried first and only advances when the unit fails to match right after it.
GAP = r'.{0,80}?'


# Activation-energy (Ea) properties, and every ion-transport property that can be split into
# bulk / grain-boundary / surface / total; their transport component is typed by transport.py.
EA_PROPERTIES = ("Activation_Energy",)
TRANSPORT_PROPERTIES = EA_PROPERTIES + ("Ionic_Conductivity", "Diffusion_Coefficient")
# Property names of earlier versions, still accepted in a job file.
PROPERTY_ALIASES = {"Migration_Barrier": "Activation_Energy"}

# The names papers give the energy an ion has to overcome to move. They are one quantity and one
# property here; which name a paper used is kept with each value (ExtractedField.reported_as).
#  - "activation energy / barrier / enthalpy", "free energy of activation";
#  - any "... barrier": "migration barrier", "hopping barrier", "diffusion energy barrier",
#    "energy barrier", a bare "barrier" — but not the barriers that are something else (a Schottky
#    or tunnelling barrier, a "barrier layer");
#  - "migration energy", "hopping energy", "jump energy", "migration enthalpy";
#  - the symbols "Ea", "E_a", "E a", "EA", "Eact", "Em", "Emig": case-sensitive and words of their
#    own, since case-insensitively "ea" is also how "area" ends.
_BARRIER_KIND = (r'(?:migration|hopping|diffusion|jump|kinetic|reaction|percolation|intercalation|transport|'
                 r'conduction|charge[\s-]transfer|potential[\s-]energy|rotation(?:al)?|reorientation(?:al)?|'
                 r'activation|energy)')
EA_TERM = (
    rf'(?:(?:apparent\s+)?activation\s+(?:energ(?:y|ies)|enthalp(?:y|ies))(?:\s+barriers?)?'
    rf'|(?:gibbs\s+)?free\s+energy\s+of\s+activation|activation\s+free\s+energy|enthalpy\s+of\s+activation'
    rf'|(?:{_BARRIER_KIND}[\s-]+){{0,2}}'
    rf'(?<!schottky\s)(?<!tunneling\s)(?<!tunnelling\s)(?<!injection\s)(?<!blocking\s)'
    rf'barriers?(?!\s+(?:layers?|coatings?|films?|heights?|widths?|thickness|propert\w+))(?:\s+energ(?:y|ies))?'
    rf'|(?:migration|hopping|jump)\s+(?:energ(?:y|ies)|enthalp(?:y|ies))'
    rf'|desolvation\s+energ(?:y|ies)'
    rf'|(?-i:\bE\s?_?\s?(?:a|A|act)\b|\bE_?(?:m|mig)\b))')
COMPILED_EA_TERM = re.compile(rf'(?i){EA_TERM}')

# What names the other transport quantities. A conductivity that is not called electronic is the
# ionic one; "σ" on its own too, "σe" / "σel" not.
ELECTRONIC_TERM = (r'(?:electronic|electron)\s+(?:\w+\s+)?conductivit(?:y|ies)'
                   r'|σ\s?_?\s?(?:e|el|elec|electronic|electron|eon)(?![A-Za-z])')
CONDUCTIVITY_TERM = (r'(?<!thermal\s)(?<!electronic\s)(?<!electron\s)conductivit(?:y|ies)'
                     r'|σ(?!\s?_?\s?(?:e|el|elec|electronic|electron|eon)(?![A-Za-z]))')
DIFFUSION_TERM = (r'(?<!thermal\s)(?:diffusion\s+coefficients?|diffusivit(?:y|ies))'
                  r'|(?-i:(?<![A-Za-z])D\s?_?(?:Li|Na|K|Mg|Ca|Zn|Al|H|tr|self|σ|\*)?(?![A-Za-z]))')

# The properties read value-first (quantities.py): every number with their unit in a sentence is a
# candidate, and the wording around it decides which quantity it is. Keyed by normalizer category.
QUANTITY_VALUES = {
    "energy": rf'{NUM}\s*({_ENERGY})',
    "conductivity": rf'{NUM_MAGNITUDE}\s*({_SIEMENS_PER_CM})',
    "diffusion": rf'{NUM_MAGNITUDE}\s*({_AREA_PER_SECOND})',
}
QUANTITY_PROPERTIES = EA_PROPERTIES + ("Ionic_Conductivity", "Electronic_Conductivity", "Diffusion_Coefficient")

# Categories whose values are measured or computed for a material, as opposed to the paper-level
# DFT/AIMD/ML/synthesis settings. Only their numeric values get a measurement context (context.py).
MATERIAL_CATEGORIES = ("ELECTROCHEMICAL", "THERMODYNAMIC", "MECHANICAL", "STRUCTURAL", "ELECTRONIC",
                       "THERMAL", "SPECTROSCOPY")


class SchemaConfig:
    # Scientific NLP Cues
    POSITIVE_CUES = ["our", "this work", "calculated", "measured", "achieved", "exhibits", "shows",
                      "observed", "obtained", "found", "demonstrate", "confirmed"]
    NEGATIVE_CUES = ["previous", "literature", "reported", "ref", "et al", "according to",
                      "compared to", "in contrast to"]

    # Canonical section name -> synonyms seen in real papers (schema section 12).
    SECTION_SYNONYMS: Dict[str, List[str]] = {
        "Abstract": ["abstract"],
        "Introduction": ["introduction", "background"],
        "Methods": [
            "methods", "method", "experimental", "materials and methods",
            "simulation details", "computational details", "computational methods",
            "theory", "theoretical methods", "experimental section", "experimental details",
        ],
        "Results": ["results", "results and discussion"],
        "Discussion": ["discussion"],
        "Conclusion": ["conclusion", "conclusions", "summary", "concluding remarks"],
        "Supplementary": [
            "supplementary information", "supplementary materials", "supporting information",
            "supplementary", "appendix", "electronic supplementary material", "esi",
        ],
        "Boilerplate": [
            "author contributions", "conflict of interest", "conflicts of interest",
            "competing interests", "acknowledgements", "acknowledgments", "data availability",
            "funding", "declaration of competing interest",
        ],
        "References": ["references", "bibliography"],
    }

    SCHEMA: Dict[str, Dict[str, Tuple[str, str]]] = {
        "ELECTROCHEMICAL": {
            # The four transport quantities are read value-first (see QUANTITY_VALUES and
            # quantities.py); their entry here is the wording that names them, not a value pattern.
            # One property for the activation energy, whatever the paper calls it (see EA_TERM);
            # always normalized to eV. exporter.py lists its values in activation_energy.csv/sheet.
            "Activation_Energy": (rf'(?i){EA_TERM}', 'energy'),
            "Diffusion_Coefficient": (rf'(?i){DIFFUSION_TERM}', 'diffusion'),
            "Ionic_Conductivity": (rf'(?i){CONDUCTIVITY_TERM}', 'conductivity'),
            "Electronic_Conductivity": (rf'(?i){ELECTRONIC_TERM}', 'conductivity'),
            "Redox_Potential": (rf'(?i)redox potential\b{GAP}{NUM}\s*(V|mV)', 'voltage'),
            "Stability_Window": (rf'(?i)(?:electrochemical stability window|ESW)\b{GAP}{NUM}\s*(V|mV)', 'voltage'),
            "Voltage": (rf'(?i)(?:average voltage|operating voltage|voltage plateau|voltage)\b{GAP}{NUM}\s*(V|mV)', 'voltage'),
            "Overpotential": (rf'(?i)overpotential\b{GAP}{NUM}\s*(V|mV)', 'voltage'),
            "Capacity": (rf'(?i)(?:specific capacity|discharge capacity|charge capacity|capacity)\b{GAP}{NUM}\s*(mAh/?g|Ah/?kg|mAh/?cm2)', 'capacity'),
            "Specific_Capacity": (rf'(?i)specific capacity\b{GAP}{NUM}\s*(mAh/?g|Ah/?kg)', 'capacity'),
            "Initial_Capacity": (rf'(?i)initial (?:discharge |charge )?capacity\b{GAP}{NUM}\s*(mAh/?g|Ah/?kg)', 'capacity'),
            "Energy_Density": (rf'(?i)energy density\b{GAP}{NUM}\s*(Wh/?kg|Wh/?L|kWh/?kg)', 'energy_density'),
            "Power_Density": (rf'(?i)power density\b{GAP}{NUM}\s*(W/?kg|kW/?kg)', 'power_density'),
            "Current_Density": (rf'(?i)current density\b{GAP}{NUM}\s*(mA/?cm2|A/?cm2|mA/?g|A/?g)', 'current_density'),
            "Critical_Current_Density": (rf'(?i)critical current density\b{GAP}{NUM}\s*(mA/?cm2|A/?cm2)', 'current_density'),
            "Cycle_Life": (rf'(?i)cycle life\b{GAP}{NUM}\s*(cycles)', 'count'),
            "Capacity_Retention": (rf'(?i)capacity retention\b{GAP}{NUM}\s*(%|percent)', 'percent'),
            "Coulombic_Efficiency": (rf'(?i)coulombic efficiency\b{GAP}{NUM}\s*(%|percent)', 'percent'),
            "Rate_Capability": (rf'(?i)rate capability\b{GAP}{NUM}\s*(C|c-rate)', 'string'),
            "C_Rate": (rf'(?i)\bat\s{NUM}\s*C\b', 'string'),
            "Interfacial_Resistance": (rf'(?i)interfacial resistance\b{GAP}{NUM}\s*(ohm\s*cm2|Ω\s*cm2|Ω\s*⋅?\s*cm2)', 'area_resistance'),
        },
        "THERMODYNAMIC": {
            "Formation_Energy": (rf'(?i)formation energy\b{GAP}{NUM}\s*(eV(?:/atom)?|eV/f\.u\.|kJ/mol)', 'energy'),
            "Energy_Above_Hull": (rf'(?i)energy above (?:the )?hull\b{GAP}{NUM}\s*(eV(?:/atom)?|meV(?:/atom)?)', 'energy'),
            "Reaction_Energy": (rf'(?i)reaction energy\b{GAP}{NUM}\s*(eV|eV/atom|kJ/mol)', 'energy'),
            "Surface_Energy": (rf'(?i)surface energy\b{GAP}{NUM}\s*(J/?m2|eV/Å2|eV/A2)', 'surface_energy'),
            "Vacancy_Formation_Energy": (rf'(?i)vacancy formation energy\b{GAP}{NUM}\s*(eV)', 'energy'),
            "Binding_Energy": (rf'(?i)binding energy\b{GAP}{NUM}\s*(eV|kJ/mol)', 'energy'),
            "Adsorption_Energy": (rf'(?i)adsorption energy\b{GAP}{NUM}\s*(eV|kJ/mol)', 'energy'),
        },
        "MECHANICAL": {
            "Bulk_Modulus": (rf'(?i)bulk modulus\b{GAP}{NUM}\s*(GPa|MPa)', 'pressure'),
            "Young_Modulus": (rf"(?i)young'?s modulus\b{GAP}{NUM}\s*(GPa|MPa)", 'pressure'),
            "Shear_Modulus": (rf'(?i)shear modulus\b{GAP}{NUM}\s*(GPa|MPa)', 'pressure'),
            "Poisson_Ratio": (rf"(?i)poisson'?s? ratio\b{GAP}{NUM}\s*()", 'dimensionless'),
        },
        "STRUCTURAL": {
            "Lattice_Parameter_a": (rf'(?i)(?:lattice parameter|lattice constant)\s*a\b{GAP}{NUM}\s*(Å|nm|pm|Angstrom)', 'length'),
            "Lattice_Parameter_c": (rf'(?i)(?:lattice parameter|lattice constant)\s*c\b{GAP}{NUM}\s*(Å|nm|pm|Angstrom)', 'length'),
            "Cell_Volume": (rf'(?i)(?:cell|unit cell) volume\b{GAP}{NUM}\s*(Å3|Å\^3|nm3)', 'volume'),
            "Density": (rf'(?i)(?:mass |bulk )?density\b{GAP}{NUM}\s*(g/?cm3|kg/?m3|g/?cc)', 'density'),
            "Space_Group": (r'(?i)space group\b[^\w]{0,10}([A-Za-z0-9/\-]{2,10}(?:\s*\(No\.\s*\d+\))?)', 'string'),
            "Crystal_System": (r'(?i)\b(cubic|tetragonal|orthorhombic|hexagonal|trigonal|rhombohedral|monoclinic|triclinic)\b', 'string'),
            "Grain_Size": (rf'(?i)grain size\b{GAP}{NUM}\s*(nm|μm|um|mm)', 'length'),
            "Particle_Size": (rf'(?i)particle size\b{GAP}{NUM}\s*(nm|μm|um|mm)', 'length'),
            "Porosity": (rf'(?i)porosity\b{GAP}{NUM}\s*(%|percent)', 'percent'),
            "Relative_Density": (rf'(?i)relative density\b{GAP}{NUM}\s*(%|percent)', 'percent'),
            # Radii the paper itself quotes; the Shannon radii of every material's own ions are
            # computed separately (chemistry.ionic_radii).
            "Ionic_Radius": (rf'(?i)ionic radi(?:us|i)\b{GAP}{NUM}\s*(Å|nm|pm|Angstrom)', 'length'),
        },
        "ELECTRONIC": {
            "Band_Gap": (rf'(?i)band\s*gap\b{GAP}{NUM}\s*(eV)', 'energy'),
            "Bader_Charge": (rf'(?i)bader charge\b{GAP}{NUM}\s*(e|electrons)?', 'dimensionless'),
            "DOS_Mentioned": (r'(?i)\b(density of states|DOS)\b', 'string'),
            "PDOS_Mentioned": (r'(?i)\b(projected density of states|PDOS)\b', 'string'),
            "COHP_Mentioned": (r'(?i)\b(crystal orbital hamilton population|COHP)\b', 'string'),
        },
        "THERMAL": {
            "Activation_Temperature": (rf'(?i)activation temperature\b{GAP}{NUM}\s*(K|°C|C)', 'temperature'),
            "Melting_Point": (rf'(?i)melting point\b{GAP}{NUM}\s*(K|°C|C)', 'temperature'),
            "Glass_Transition_Temperature": (rf'(?i)glass transition(?:\s*temperature)?\s*(?:Tg)?\b{GAP}{NUM}\s*(K|°C|C)', 'temperature'),
            "Debye_Temperature": (rf'(?i)Debye temperature\b{GAP}{NUM}\s*(K)', 'temperature'),
            "Thermal_Conductivity": (rf'(?i)thermal conductivity\b{GAP}{NUM}\s*(W/?m/?K|W/?\(m·?K\))', 'thermal_conductivity'),
            "Thermal_Expansion_Coefficient": (rf'(?i)thermal expansion coefficient\b{GAP}{NUM}\s*(ppm/?K|10\^?-6/?K|K-1|K\^?-1)', 'dimensionless'),
        },
        "SPECTROSCOPY": {
            "Raman_Peak": (rf'(?i)Raman(?:\s*shift)?\b{GAP}{NUM}\s*(cm-1|cm\^?-1)', 'wavenumber'),
            "FTIR_Peak": (rf'(?i)FTIR\b{GAP}{NUM}\s*(cm-1|cm\^?-1)', 'wavenumber'),
            "XRD_Peak": (rf'(?i)(?:XRD peak|2\s*θ|2theta)\b{GAP}{NUM}\s*(°|deg|degrees)', 'angle'),
        },
        "DFT": {
            "Software": (r'(?i)\b(VASP|Quantum ESPRESSO|CASTEP|CP2K|ABINIT|Gaussian|CRYSTAL|SIESTA|WIEN2k|GPAW|Materials Studio|FHI-aims|ORCA)\b', 'string'),
            "Version": (r'(?i)\bversion\s*([\d.]+)\b', 'string'),
            "Functional": (r'(?i)\b(PBEsol|PBE0|PBE|SCAN|r2SCAN|HSE06|HSE|LDA|GGA\+U|GGA)\b', 'string'),
            "Hubbard_U": (rf'(?i)(?:Hubbard U|DFT\+U|U\s*value)\b{GAP}{NUM}\s*(eV)', 'energy'),
            "Cutoff_Energy": (rf'(?i)(?:cutoff energy|plane[- ]wave cutoff|ENCUT)\b{GAP}{NUM}\s*(eV|Ry)', 'energy_large'),
            "Ecutwfc": (rf'(?i)ecutwfc\b{GAP}{NUM}\s*(Ry|eV)', 'energy_large'),
            "Ecutrho": (rf'(?i)ecutrho\b{GAP}{NUM}\s*(Ry|eV)', 'energy_large'),
            "Pseudopotential": (r'(?i)\b(PAW|norm-conserving|ultrasoft|projector augmented[- ]wave|USPP|NCPP)\b', 'string'),
            "Kpoint_Mesh": (r'(?i)(?:k-?point mesh|Monkhorst-?Pack|k-?mesh|k-?grid)[^\d]{0,20}?(\d+\s*[×xX]\s*\d+\s*[×xX]\s*\d+)', 'string'),
            "SCF_Convergence": (rf'(?i)SCF convergence\b{GAP}{NUM}\s*(eV|Ry)', 'energy_large'),
            "Relaxation_Type": (r'(?i)\b(VC-relax|variable[- ]cell relaxation|ionic relaxation|full relaxation|geometry optimization)\b', 'string'),
            "NEB": (r'(?i)\b(nudged elastic band|NEB)\b', 'string'),
            "Spin_Polarization": (r'(?i)\b(spin[- ]polariz(?:ed|ation)|collinear spin)\b', 'string'),
            "SOC": (r'(?i)\b(spin-orbit coupling|SOC)\b', 'string'),
            "Dispersion_Correction": (r'(?i)\b(DFT-D3|DFT-D2|Grimme dispersion|van der Waals correction|vdW-DF)\b', 'string'),
            "Hybrid_Functional": (r'(?i)\b(hybrid functional|HSE06|PBE0)\b', 'string'),
            "Meta_GGA": (r'(?i)\b(meta-GGA|SCAN|r2SCAN)\b', 'string'),
            "Supercell_Size": (r'(?i)supercell[^\d]{0,20}?(\d+\s*[×xX]\s*\d+\s*[×xX]\s*\d+)', 'string'),
            "Vacancy_Concentration": (rf'(?i)vacancy concentration\b{GAP}{NUM}\s*(%|percent)', 'percent'),
        },
        "AIMD": {
            "Temperature": (rf'(?i)(?:AIMD|simulation)[^.]{{0,40}}?{NUM}\s*K\b', 'temperature'),
            "Pressure": (rf'(?i)pressure\b{GAP}{NUM}\s*(GPa|MPa|bar|atm)', 'pressure'),
            "Simulation_Time": (rf'(?i)simulation time\b{GAP}{NUM}\s*(ps|ns|fs)', 'time'),
            "Timestep": (rf'(?i)time\s*step\b{GAP}{NUM}\s*(fs|ps)', 'time'),
            "Ensemble": (r'\b(NVT|NPT|NVE)\b', 'string'),
            "Supercell": (r'(?i)supercell[^\d]{0,20}?(\d+\s*[×xX]\s*\d+\s*[×xX]\s*\d+)', 'string'),
            "Trajectory_Length": (rf'(?i)trajector(?:y|ies)\b{GAP}{NUM}\s*(ps|ns|fs)', 'time'),
            "MSD_Mentioned": (r'(?i)\b(mean square(?:d)? displacement|MSD)\b', 'string'),
        },
        "ML": {
            "Algorithm": (r'(?i)\b(Random Forest|Gradient Boosting|XGBoost|LightGBM|CatBoost|SVM|Support Vector Machine|GNN|Graph Neural Network|CGCNN|MEGNet|ALIGNN|Neural Network|Deep Learning|Gaussian Process|Kernel Ridge Regression|Linear Regression)\b', 'string'),
            "Descriptor": (r'(?i)\b(Coulomb matrix|SOAP|symmetry function|Voronoi|Magpie descriptor|structural fingerprint)\b', 'string'),
            "Training_Size": (rf'(?i)(?:training (?:set|data)|trained on)\b{GAP}{NUM}\s*(samples|structures|compounds|data points)?', 'count'),
            "Validation_Size": (rf'(?i)validation (?:set|data)\b{GAP}{NUM}\s*(samples|structures|compounds|data points)?', 'count'),
            "Test_Size": (rf'(?i)test (?:set|data)\b{GAP}{NUM}\s*(samples|structures|compounds|data points)?', 'count'),
            "Cross_Validation": (rf'(?i)(\d+)[- ]fold cross[- ]validation', 'count'),
            "Accuracy": (rf'(?i)accuracy\b{GAP}{NUM}\s*(%|percent)?', 'percent'),
            "Precision": (rf'(?i)precision\b{GAP}{NUM}\s*(%|percent)?', 'percent'),
            "Recall": (rf'(?i)recall\b{GAP}{NUM}\s*(%|percent)?', 'percent'),
            "F1_Score": (rf'(?i)F1[- ]?(?:score)?\b{GAP}{NUM}', 'dimensionless'),
            "MAE": (rf'(?i)MAE\b{GAP}{NUM}', 'dimensionless'),
            "RMSE": (rf'(?i)RMSE\b{GAP}{NUM}', 'dimensionless'),
            "R2": (rf'(?i)R\^?2\b{GAP}{NUM}', 'dimensionless'),
            "ROC_AUC": (rf'(?i)(?:ROC[- ]AUC|AUC)\b{GAP}{NUM}', 'dimensionless'),
            "Explainability_Method": (r'(?i)\b(SHAP|LIME)\b', 'string'),
        },
        "SYNTHESIS": {
            "Method": (r'(?i)\b(solid[- ]state|sol[- ]gel|hydrothermal|solvothermal|ball milling|melt quenching|melt-quench|CVD|PLD|co-precipitation|spray pyrolysis|freeze[- ]drying)\b', 'string'),
            "Temperature": (rf'(?i)(?:calcined|sintered|annealed|synthesized)[^\d]{{0,20}}?at{GAP}{NUM}\s*(°C|K)', 'temperature'),
            "Time": (rf'(?i)(?:calcined|sintered|annealed|held)[^\d]{{0,30}}?for{GAP}{NUM}\s*(h|hours|min|minutes)', 'time'),
            "Atmosphere": (r'(?i)\b(argon|nitrogen|air atmosphere|vacuum|inert atmosphere|ambient air)\b', 'string'),
        },
        "CHARACTERIZATION": {
            "Technique": (r'\b(XRD|SEM|TEM|HRTEM|EDS|EDX|XPS|Raman|FTIR|EIS|CV|GITT|NMR|BET|TGA|DSC|SAXS|PDF analysis)\b', 'string'),
        },
    }

    # Compiled once at import time (schema section 18: compile regexes once).
    COMPILED_SCHEMA: Dict[str, Dict[str, Tuple[Pattern, str]]] = {
        cat: {prop: (re.compile(pattern), norm_type) for prop, (pattern, norm_type) in props.items()}
        for cat, props in SCHEMA.items()
    }

    # Equation classification (schema section 10): name/keyword patterns -> canonical equation type.
    EQUATION_PATTERNS: Dict[str, str] = {
        r'(?i)arrhenius': "Arrhenius",
        r'(?i)nernst-?einstein': "Nernst-Einstein",
        r'(?i)mean square(?:d)? displacement|\bMSD\b': "MSD/Diffusion",
        r'(?i)einstein relation': "Einstein Relation",
        r'(?i)nudged elastic band|\bNEB\b': "NEB",
        r'(?i)butler-?volmer': "Butler-Volmer",
        r'(?i)fick\'?s (?:first|second) law': "Fick's Law",
        r'(?i)vegard\'?s law': "Vegard's Law",
    }

    # Ordered computational/experimental workflow stage keywords (schema section 11).
    WORKFLOW_STAGES: List[Tuple[str, str]] = [
        (r'(?i)\b(ICSD|Materials Project|crystal structure database|structure database)\b', "Structure Retrieval"),
        (r'(?i)\b(structural relaxation|geometry optimization|DFT relaxation|VC-relax)\b', "DFT Relaxation"),
        (r'(?i)\bsupercell\b', "Supercell Construction"),
        (r'(?i)\b(ab initio molecular dynamics|AIMD)\b', "AIMD"),
        (r'(?i)\b(mean square(?:d)? displacement|MSD)\b', "MSD Analysis"),
        (r'(?i)\bdiffusion coefficient\b', "Diffusion Analysis"),
        (r'(?i)\barrhenius\b', "Arrhenius Fitting"),
        (r'(?i)\b(ionic conductivity|conductivity)\b', "Conductivity Extraction"),
        (r'(?i)\b(machine learning|neural network|random forest|regression model)\b', "Machine Learning"),
        (r'(?i)\b(experimental validation|experimentally validated|synthesized and tested)\b', "Experimental Validation"),
    ]
