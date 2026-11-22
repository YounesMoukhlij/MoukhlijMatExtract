"""Writes one job file per family of solid electrolytes (garnet, NASICON, LISICON, …) and the garnet + NASICON job
of the article, from one description of each family. What every family shares — the sources, the property words,
the download and extraction settings — is read from configs/garnet_nasicon.yaml, the job the others grew from.

    python scripts/families/make_family_jobs.py            # writes resources/configs/*.yaml

Each family's job has:
  - its queries: the hand-written ones about its chemistry, then every main name of the family with every
    transport measurement and method ("LLZO ionic conductivity", "LLZO lithium migration barrier", …);
  - its topic words: the family's names, abbreviations, formulas and the parts of formulas that find its doped
    members (a formula is found however a title writes it: see screening.py);
  - the property words every family shares, and exclusion words for the family's usual noise;
  - its own DOI list, PDF folder and database (WebScraping/papers_<family>, WebScraping/web_output_<family>).
The files ship with the package (setup.py copies them in); ~/MoukhlijMatExtract/configs/ gets a copy of each
(mme_home.populate)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[2]
sys.path[0:0] = [str(ROOT / group) for group in ("core", "export", "app")]  # where the packages are
BASE = ROOT / "resources" / "configs" / "garnet_nasicon.yaml"
OUT = ROOT / "resources" / "configs"

# Every measurement and method, asked with every main name of a family. {ion}: each mobile ion of the family.
TRANSPORT = (
    "{a} ionic conductivity", "{a} activation energy", "{a} {ion} ion diffusion", "{a} {ion} migration barrier",
    "{a} ion transport mechanism", "{a} grain boundary conductivity", "{a} bulk ionic conductivity",
    "{a} impedance spectroscopy", "{a} temperature dependent conductivity", "{a} diffusion coefficient",
    "{a} doping ionic conductivity", "{a} electronic conductivity", "{a} electrochemical stability window",
    "{a} interfacial resistance", "{a} molecular dynamics {ion} diffusion", "{a} density functional theory migration",
    "{a} NMR {ion} dynamics", "{a} synthesis ionic conductivity",
    # The older and broader names the same papers go by.
    "{a} fast ion conductor", "{a} superionic conductor",
)
# The ways papers name a transport mechanism, asked with the first name of each family.
MECHANISMS = ("concerted migration", "vacancy mechanism", "interstitial mechanism", "interstitialcy mechanism",
              "paddle-wheel mechanism", "correlated ion hopping", "percolation conduction pathway",
              "bottleneck size migration", "anion framework lithium diffusion")
# Property words every family's job gets on top of those of the base job (not the article's job, garnet_nasicon,
# whose screening stays as it is): the mechanisms, and the older names of fast ion conduction.
MECHANISM_WORDS = ("Transport mechanisms and the older names of fast ion conduction", [
    "concerted migration", "vacancy mechanism", "interstitial mechanism", "interstitialcy", "paddle-wheel",
    "correlated migration", "correlated hopping", "percolation pathway", "bottleneck size", "fast ion conductor",
    "fast-ion conductor", "superionic conductor", "superionic conductivity", "solid ionic conductor",
    "solid-state ionics"])

# What kind of family each job is — kept apart, as the literature keeps them apart: a crystal-structure type (one
# prototype and its relatives), a chemical family (by its anion or polyanion), a composition system (glasses and
# glass-ceramics along a join), a material class, or a grouping by mobile ion. (kind, prototype and space groups)
TAXONOMY = {
    "garnet": ("crystal-structure type", "garnet A3B2(XO4)3; Li7La3Zr2O12: cubic Ia-3d, tetragonal I41/acd"),
    "nasicon": ("crystal-structure type", "NZP / NaZr2(PO4)3 framework, rhombohedral R-3c; Na3Zr2Si2PO12 also monoclinic C2/c"),
    "lisicon": ("crystal-structure type", "gamma-Li3PO4 (Pnma): Li14Zn(GeO4)4; thio-LISICON Li4-xGe1-xPxS4"),
    "lgps": ("crystal-structure type", "Li10GeP2S12, tetragonal P42/nmc"),
    "argyrodite": ("crystal-structure type", "Ag8GeS6 argyrodite; Li6PS5X, cubic F-43m"),
    "sulfide_glass": ("composition system", "Li2S-P2S5 and Na2S-P2S5 glasses and glass-ceramics; Li7P3S11 (P-1), beta-Li3PS4 (Pnma), cubic Na3PS4 (I-43m)"),
    "perovskite": ("crystal-structure type", "ABO3 perovskite, A-site deficient; Li3xLa2/3-xTiO3 (P4/mmm, Cmmm)"),
    "antiperovskite": ("crystal-structure type", "anti-perovskite (anti-ABX3); Li3OCl, cubic Pm-3m"),
    "halide": ("chemical family (anion: Cl, Br, I, F; oxyhalides)", "Li3MX6 (Li3YCl6 P-3m1, Li3InCl6 C2/m), Li2MCl6 (Li2ZrCl6 P-3m1)"),
    "complex_hydride": ("chemical family (complex anions BH4-, closo-borates)", "LiBH4 (high-T P63mc), Li2B12H12, LiCB11H12"),
    "beta_alumina": ("crystal-structure type", "beta-alumina P63/mmc, beta''-alumina R-3m"),
    "lipon": ("material class (amorphous thin films and oxide glasses)", "amorphous Li-P-O-N; lithium borate and borophosphate glasses"),
    "nitride": ("chemical family (anion: N3-, with amides and imides)", "Li3N (P6/mmm); nitridophosphates (Li7PN4), nitridosilicates (Li2SiN2)"),
    "fluoride": ("chemical family (anion: F-, with oxyfluorides)", "tysonite LaF3 (P-3c1), fluorite (Fm-3m); Li3AlF6"),
    "mixed_anion": ("chemical family (two or more anions)", "oxysulfides, sulfide-halides (Li7P2S8I), nitride-halides (Li6NBr3)"),
    "oxide_chemistry": ("chemical families (oxide anions)", "niobates, tantalates, zirconates, aluminates, titanates, tungstates, molybdates, borates, silicates, germanates"),
    "oxide_structure": ("crystal-structure types not covered elsewhere", "spinel (Fd-3m), pyrochlore (Fd-3m), scheelite (I41/a), brownmillerite, olivine-related, layered"),
    "polymer": ("material class (polymer electrolytes)", "polyethers (PEO), polycarbonates, polysiloxanes, PVDF-HFP and PAN gels, single-ion polymers, block copolymers"),
    "hybrid": ("material class (composites and framework electrolytes)", "polymer-ceramic composites, MOF and COF electrolytes, plastic crystals, ionogels"),
    "multivalent": ("grouping by mobile ion (Mg2+, Ca2+, Zn2+, Al3+, Sc3+)", "spinel MgSc2Se4, NASICON-type MgZr4(PO4)6, Sc2(WO4)3 type, Mg(BH4)2"),
}
SHARED_EXCLUDE = ["supercapacitor", "photocatalyst", "solar cell", "fuel cell", "SOFC", "water splitting", "electrolyzer"]

Groups = List[Tuple[str, List[str]]]


# ----------------------------------------------------------------------------------------------------------------
# The families
# ----------------------------------------------------------------------------------------------------------------
FAMILIES: Dict[str, dict] = {
    "lisicon": dict(
        title="LISICON and thio-LISICON solid electrolytes",
        about="The LISICON family (gamma-Li3PO4 type: Li14Zn(GeO4)4, Li4SiO4-Li3PO4, Li3VO4-Li4GeO4 solid solutions) "
              "and its sulfide analogues, the thio-LISICONs (Li4-xGe1-xPxS4, Li4GeS4, Li4SnS4).",
        ions=["lithium"],
        names=["LISICON solid electrolyte", "thio-LISICON", "Li14Zn(GeO4)4", "Li4SiO4-Li3PO4", "Li3.25Ge0.25P0.75S4"],
        topic=[("LISICON family and aliases", [
            "LISICON", "LISICON-type", "lithium superionic conductor", "thio-LISICON", "thio-LISICON-type",
            "gamma-Li3PO4", "γ-Li3PO4", "Li3PO4-type"]),
            ("Oxide LISICON formulas and solid solutions", [
                "Li14Zn(GeO4)4", "Li4SiO4", "Li3PO4", "Li3.5Si0.5P0.5O4", "Li4SiO4-Li3PO4", "Li3VO4", "Li4GeO4",
                "Li3.6Ge0.6V0.4O4", "Li3+xGexV1-xO4", "Li4+xSi1-xAlxO4", "Li4-xSi1-xPxO4", "Li2+2xZn1-xGeO4",
                "lithium zinc germanate", "lithium orthosilicate", "lithium orthophosphate"]),
            ("thio-LISICON formulas", [
                "Li4-xGe1-xPxS4", "Li3.25Ge0.25P0.75S4", "Li4GeS4", "Li4SnS4", "Li3.4Si0.4P0.6S4", "Li4SiS4",
                "Li3.833Sn0.833As0.166S4", "Li4-xSn1-xSbxS4", "Ge1-xPxS4"])],
        queries=[
            ("LISICON: oxide compositions and their conduction", [
                "Li14Zn(GeO4)4 lithium ion conductivity aging", "LISICON conductivity decrease aging trapping",
                "Li4SiO4 Li3PO4 solid solution conductivity", "Li3VO4 Li4GeO4 solid solution conductivity",
                "Li4SiO4 lithium ion conduction mechanism", "gamma Li3PO4 structure lithium interstitial",
                "LISICON interstitial lithium conduction", "LISICON aliovalent substitution conductivity",
                "Li3+xP1-xSixO4 thin film conductivity", "LISICON lithium stuffed tetrahedral framework"]),
            ("thio-LISICON: sulfide compositions", [
                "thio-LISICON Li4-xGe1-xPxS4 conductivity", "Li3.25Ge0.25P0.75S4 lithium conductivity",
                "Li4GeS4 Li3PS4 solid solution", "Li4SnS4 air stable sulfide electrolyte conductivity",
                "Li4SnS4 arsenic substitution conductivity", "Li4SiS4 lithium conductivity",
                "thio-LISICON polyanion rotation lithium transport", "orthothiophosphate lithium conductor"]),
        ],
        exclude=[],
    ),
    "lgps": dict(
        title="LGPS-type (Li10GeP2S12 family) solid electrolytes",
        about="Li10GeP2S12 and its relatives: Li10SnP2S12, Li10SiP2S12, Li11Si2PS12, Li9.54Si1.74P1.44S11.7Cl0.3, "
              "and the LGPS-type selenides and oxygen- or halogen-substituted phases.",
        ions=["lithium"],
        names=["LGPS", "Li10GeP2S12", "Li10SnP2S12", "Li10SiP2S12", "Li9.54Si1.74P1.44S11.7Cl0.3"],
        topic=[("LGPS family and aliases", [
            "LGPS", "LGPS-type", "Li10GeP2S12-type", "LSiPSCl", "LSnPS", "LiMPS"]),
            ("LGPS formulas", [
                "Li10GeP2S12", "Li10SnP2S12", "Li10SiP2S12", "Li11Si2PS12", "Li9.54Si1.74P1.44S11.7Cl0.3",
                "Li9.6P3S12", "Li10GeP2Se12", "Li10GeP2S11.7O0.3", "Li7GePS8", "Li10+δGe1+δP2-δS12",
                "Li10±1MP2X12", "Li3.45Si0.45P0.55S4"]),
            ("Parts of LGPS formulas (find the doped members)", ["P2S12", "P2S11", "Si1.74P1.44"])],
        queries=[
            ("LGPS: structure and anisotropic transport", [
                "Li10GeP2S12 one-dimensional diffusion channel", "LGPS c-axis lithium diffusion",
                "LGPS three-dimensional lithium diffusion", "LGPS tetragonal P42/nmc lithium sites",
                "LGPS anisotropic conductivity single crystal", "Li10GeP2S12 lithium disorder neutron diffraction",
                "LGPS framework polyanion lithium transport", "Li10GeP2S12 vacancy lithium conduction"]),
            ("LGPS: substitutions and new members", [
                "Li10SnP2S12 tin substitution conductivity", "Li10SiP2S12 silicon substitution conductivity",
                "Li9.54Si1.74P1.44S11.7Cl0.3 high power", "Li11Si2PS12 high pressure synthesis conductivity",
                "LGPS oxygen substitution stability", "LGPS halogen substitution conductivity",
                "LGPS-type Li10GeP2Se12 conductivity", "Li10GeP2S12 high entropy substitution"]),
            ("LGPS: stability and interfaces", [
                "Li10GeP2S12 electrochemical decomposition", "Li10GeP2S12 lithium metal interface reaction",
                "LGPS interphase growth impedance", "LGPS phase stability metastable"]),
        ],
        exclude=[],
    ),
    "argyrodite": dict(
        title="Argyrodite-type solid electrolytes",
        about="Lithium argyrodites Li6PS5X (X = Cl, Br, I), the halide-rich Li6-xPS5-xX1+x, the Ge-, Si- and "
              "Sb-substituted members, and the sodium argyrodites.",
        ions=["lithium", "sodium"],
        names=["argyrodite solid electrolyte", "Li6PS5Cl", "Li6PS5Br", "Li6PS5I", "Li5.5PS4.5Cl1.5"],
        topic=[("Argyrodite family and aliases", [
            "argyrodite", "argyrodite-type", "lithium argyrodite", "sodium argyrodite", "halide argyrodite"]),
            ("Argyrodite formulas", [
                "Li6PS5Cl", "Li6PS5Br", "Li6PS5I", "Li6PS5X", "Li5.5PS4.5Cl1.5", "Li5.4PS4.4Cl1.6",
                "Li6-xPS5-xCl1+x", "Li6PS5Cl0.5Br0.5", "Li6+xP1-xGexS5I", "Li6.6P0.4Ge0.6S5I", "Li6+xP1-xSixS5Br",
                "Li7PS6", "Li7PSe6", "Li6PO5Cl", "Li6.6Si0.6Sb0.4S5I", "Na6PS5Cl"]),
            ("Parts of argyrodite formulas (find the doped members)", ["PS5Cl", "PS5Br", "PS5I", "PS4.5Cl", "PS4.4Cl"])],
        queries=[
            ("Argyrodite: halide disorder and lithium excess", [
                "argyrodite S2- Cl- site disorder conductivity", "argyrodite halide disorder lithium conduction",
                "Li6PS5Cl anion disorder ionic conductivity", "halide rich argyrodite Li5.5PS4.5Cl1.5",
                "Li6+xP1-xGexS5I lithium excess conductivity", "argyrodite intercage intracage lithium jumps",
                "argyrodite lithium sublattice polyhedral cages", "Li6PS5Br Li6PS5I conductivity difference"]),
            ("Argyrodite: synthesis and processing", [
                "argyrodite mechanochemical synthesis conductivity", "argyrodite solution synthesis conductivity",
                "Li6PS5Cl annealing temperature conductivity", "Li6PS5Cl cold pressing densification conductivity",
                "argyrodite thin membrane electrolyte conductivity", "argyrodite moisture H2S stability"]),
            ("Argyrodite: interfaces and cells", [
                "Li6PS5Cl lithium metal interface", "Li6PS5Cl cathode composite interface resistance",
                "argyrodite electrochemical stability window", "argyrodite critical current density"]),
        ],
        exclude=["thermoelectric", "ore deposit", "hydrothermal deposit", "mineralization"],
    ),
    "sulfide_glass": dict(
        title="Thiophosphate glasses, glass-ceramics and sodium thio-salts",
        about="Li2S-P2S5 glasses and glass-ceramics (Li7P3S11, beta-Li3PS4, 75Li2S-25P2S5, with LiI or LiBH4), the "
              "Li2S-SiS2 / GeS2 / B2S3 glasses, and the sodium thiophosphates and thioantimonates (Na3PS4, Na3SbS4, "
              "Na11Sn2PS12).",
        ions=["lithium", "sodium"],
        names=["Li2S-P2S5 glass", "Li7P3S11", "Li3PS4", "Na3PS4", "Na3SbS4"],
        topic=[("Thiophosphate and sulfide glass aliases", [
            "thiophosphate", "lithium thiophosphate", "sodium thiophosphate", "sulfide glass", "sulfide glass-ceramic",
            "glass-ceramic electrolyte"]),
            ("Lithium sulfide glass and glass-ceramic formulas", [
                "Li2S-P2S5", "Li7P3S11", "Li3PS4", "β-Li3PS4", "beta-Li3PS4", "Li4P2S6", "Li4P2S7", "Li2S-P2S5-LiI",
                "75Li2S-25P2S5", "70Li2S-30P2S5", "80Li2S-20P2S5", "Li2S-SiS2", "Li2S-GeS2", "Li2S-B2S3",
                "Li3PS4-LiI", "Li3PS4-LiBH4"]),
            ("Sodium thio-salt formulas", [
                "Na3PS4", "cubic Na3PS4", "Na3SbS4", "Na3PSe4", "Na3SbSe4", "Na11Sn2PS12", "Na11Sn2PSe12", "Na2S-P2S5",
                "Na3-xSbS4-xClx", "Na2.88Sb0.88W0.12S4", "Na3P1-xAsxS4"]),
            ("Parts of formulas (find the doped members)", ["P3S11", "SbS4", "Sn2PS12"])],
        queries=[
            ("Lithium sulfide glasses and glass-ceramics", [
                "Li2S-P2S5 glass ionic conductivity composition", "Li7P3S11 glass ceramic crystallization conductivity",
                "beta-Li3PS4 nanoporous conductivity", "Li3PS4 glass local structure PS4 units",
                "Li2S-P2S5-LiI glass conductivity", "sulfide glass electrolyte mixed former effect",
                "Li2S-SiS2 glass lithium conduction", "Li2S-GeS2 glass lithium conduction",
                "Li2S-B2S3 glass conductivity", "sulfide glass Raman P2S7 PS4 P2S6 units",
                "Li7P3S11 metastable phase decomposition", "glass-ceramic sulfide electrolyte heat treatment"]),
            ("Sodium thio-salts", [
                "cubic Na3PS4 sodium conductivity", "tetragonal cubic Na3PS4 phase", "Na3SbS4 sodium conductivity",
                "Na3SbS4 tungsten doping vacancy conductivity", "Na3PSe4 sodium conductivity",
                "Na11Sn2PS12 sodium conductivity", "Na3PS4 halogen doping conductivity",
                "sodium thioantimonate electrolyte", "Na3PS4 sodium metal interface"]),
            ("Stability of sulfides", [
                "sulfide electrolyte H2S generation moisture", "sulfide electrolyte oxidation stability",
                "sulfide solid electrolyte wet chemical synthesis"]),
        ],
        exclude=["chalcogenide glass optical", "infrared optics", "phase change memory", "photonic"],
    ),
    "perovskite": dict(
        title="Perovskite-type lithium-ion conductors (LLTO and relatives)",
        about="A-site-deficient perovskite lithium-ion conductors: Li3xLa2/3-xTiO3 (LLTO), LSTZ "
              "(Li3/8Sr7/16Ta3/4Zr1/4O3), Li-Sr-(Ta,Nb,Hf) perovskites. Halide perovskites for solar cells are kept out.",
        ions=["lithium"],
        names=["LLTO", "lithium lanthanum titanate", "Li3xLa2/3-xTiO3", "Li0.33La0.56TiO3", "perovskite lithium ion conductor"],
        topic=[("Perovskite lithium conductors: aliases", [
            "LLTO", "lithium lanthanum titanate", "perovskite-type lithium conductor", "A-site deficient perovskite",
            "perovskite solid electrolyte", "perovskite-type solid electrolyte", "LSTZ"]),
            ("Perovskite formulas", [
                "Li3xLa2/3-xTiO3", "La2/3-xLi3xTiO3", "Li0.33La0.56TiO3", "Li0.34La0.51TiO2.94", "Li0.5La0.5TiO3",
                "Li0.35La0.55TiO3", "Li0.3La0.57TiO3", "Li3/8Sr7/16Ta3/4Zr1/4O3", "Li0.375Sr0.4375Ta0.75Zr0.25O3",
                "Li0.375Sr0.4375Ta0.75Hf0.25O3", "LiSr1-xTaO3", "Li3xLa1/3-xNbO3", "La1/3NbO3"]),
            ("Parts of perovskite formulas (find the doped members)", ["La0.56TiO3", "La0.5TiO3", "Sr0.4375Ta0.75"])],
        queries=[
            ("Perovskite: structure and transport", [
                "LLTO A-site vacancy lithium conduction", "LLTO bottleneck size lithium migration",
                "LLTO octahedral tilting conductivity", "LLTO lithium content conductivity maximum",
                "LLTO superlattice ordering conductivity", "LLTO grain boundary blocking effect",
                "LLTO bulk grain boundary separation impedance", "LLTO thin film conductivity",
                "LLTO single crystal anisotropic conductivity", "LLTO percolation lithium conduction"]),
            ("Perovskite: substitutions and new members", [
                "LLTO aluminum substitution conductivity", "LLTO strontium substitution conductivity",
                "Li3/8Sr7/16Ta3/4Zr1/4O3 lithium conductivity", "LSTZ perovskite electrolyte",
                "lithium strontium tantalate perovskite conductivity", "Li3xLa1/3-xNbO3 lithium conductivity",
                "perovskite lithium conductor high entropy"]),
            ("Perovskite: stability", [
                "LLTO Ti4+ reduction lithium metal", "LLTO electronic conductivity reduction",
                "LLTO composite polymer electrolyte conductivity", "LLTO nanofiber composite electrolyte"]),
        ],
        exclude=["perovskite solar", "photovoltaic", "halide perovskite", "lead halide", "CsPbBr3", "CsPbI3", "MAPbI3",
                 "methylammonium", "formamidinium", "light-emitting", "quantum dot", "ferroelectric", "piezoelectric",
                 "multiferroic", "proton-conducting", "oxygen evolution", "photodetector"],
    ),
    "antiperovskite": dict(
        title="Anti-perovskite solid electrolytes",
        about="Lithium- and sodium-rich anti-perovskites: Li3OCl, Li3OBr, Li2OHCl, Na3OCl, Na3OBH4 and their mixed-anion "
              "and cluster-ion relatives.",
        ions=["lithium", "sodium"],
        names=["antiperovskite solid electrolyte", "Li3OCl", "Li2OHCl", "Na3OCl", "lithium-rich anti-perovskite"],
        topic=[("Anti-perovskite aliases", [
            "antiperovskite", "anti-perovskite", "inverse perovskite", "LiRAP", "NaRAP", "lithium-rich anti-perovskite",
            "sodium-rich anti-perovskite", "cluster-ion anti-perovskite"]),
            ("Anti-perovskite formulas", [
                "Li3OCl", "Li3OBr", "Li3OCl0.5Br0.5", "Li3OI", "Li2OHCl", "Li2(OH)Cl", "Li2OHBr", "Li3-xOHxCl",
                "Li3OCl1-xBrx", "Na3OCl", "Na3OBr", "Na3OI", "Na3OBH4", "Na3OCN", "Na4OI2", "Li6OSI2", "Li3SI",
                "Li3OBH4", "Na3SI"])],
        queries=[
            ("Anti-perovskite: transport and defects", [
                "Li3OCl vacancy interstitial lithium migration", "Li3OCl Schottky defect conductivity",
                "anti-perovskite lithium vacancy mechanism", "anti-perovskite cluster anion rotation paddle wheel",
                "Li3OCl glass amorphous conductivity", "Li3OCl thin film conductivity",
                "Li2OHCl proton lithium conduction", "Li2OHCl phase transition conductivity",
                "Na3OBH4 sodium conductivity", "Na3OCl sodium conductivity",
                "anti-perovskite tolerance factor conductivity", "anti-perovskite hydroxide content conductivity"]),
            ("Anti-perovskite: synthesis and stability", [
                "Li3OCl synthesis hygroscopic", "anti-perovskite electrolyte lithium metal stability",
                "Li3OCl density functional theory stability", "anti-perovskite composite electrolyte"]),
        ],
        exclude=["magnetocaloric", "superconducting", "superconductivity", "negative thermal expansion",
                 "anomalous Hall", "Mn3GaN", "MgCNi3"],
    ),
    "halide": dict(
        title="Halide and oxyhalide solid electrolytes",
        about="Lithium and sodium chlorides, bromides and fluorides (Li3YCl6, Li3InCl6, Li2ZrCl6, Li3ScCl6, Na3YCl6, "
              "Na2ZrCl6, NaAlCl4) and the oxyhalides (LiTaOCl4, LiNbOCl4, NaNbOCl4).",
        ions=["lithium", "sodium"],
        names=["halide solid electrolyte", "Li3YCl6", "Li3InCl6", "Li2ZrCl6", "Na3YCl6"],
        topic=[("Halide electrolyte aliases", [
            "halide solid electrolyte", "halide superionic conductor", "chloride solid electrolyte",
            "bromide solid electrolyte", "fluoride solid electrolyte", "oxyhalide solid electrolyte",
            "oxychloride solid electrolyte", "ternary chloride", "ternary halide", "Li3MCl6", "Li3MX6", "Li2MCl6",
            "Na3MCl6"]),
            ("Lithium halide formulas", [
                "Li3YCl6", "Li3YBr6", "Li3InCl6", "Li3InBr6", "Li3ScCl6", "Li3ErCl6", "Li3HoCl6", "Li3TbCl6",
                "Li3YbCl6", "Li3LuCl6", "Li2ZrCl6", "Li2HfCl6", "Li2.5Y0.5Zr0.5Cl6", "Li3-xY1-xZrxCl6",
                "Li3YCl6-xBrx", "Li3InCl6-xFx", "LiAlCl4", "LiGaCl4", "Li2Sc2/3Cl4", "Li3TiCl6", "Li3AlF6",
                "Li3InF6", "Li2ZrF6"]),
            ("Sodium halide formulas", [
                "Na3YCl6", "Na3ErCl6", "Na3YBr6", "Na2ZrCl6", "Na3-xY1-xZrxCl6", "NaAlCl4", "Na3InCl6",
                "Na2.25Y0.25Zr0.75Cl6", "NaTaCl6"]),
            ("Oxyhalide formulas", ["LiTaOCl4", "LiNbOCl4", "NaNbOCl4", "NaTaOCl4", "Li3InCl6-xOx"]),
            ("Parts of halide formulas (find the doped members)", [
                "YCl6", "YBr6", "InCl6", "ScCl6", "ErCl6", "ZrCl6", "HfCl6", "AlCl4", "OCl4"])],
        queries=[
            ("Halides: structure and transport", [
                "Li3YCl6 trigonal monoclinic structure conductivity", "Li3InCl6 monoclinic lithium conduction",
                "halide electrolyte anion sublattice ccp hcp conductivity", "halide electrolyte cation site disorder",
                "Li2ZrCl6 low cost halide conductivity", "Li3ScCl6 lithium conductivity",
                "zirconium substitution Li3YCl6 conductivity", "halide electrolyte vacancy engineering conductivity",
                "halide electrolyte mechanochemical synthesis amorphous", "Li3InCl6 water mediated synthesis",
                "halide electrolyte high voltage stability cathode", "halide electrolyte lithium metal reduction"]),
            ("Sodium halides", [
                "Na3YCl6 sodium conductivity", "Na2ZrCl6 sodium conductivity", "Na3-xY1-xZrxCl6 sodium conductivity",
                "NaAlCl4 sodium conductivity solid electrolyte", "sodium halide solid electrolyte cathode"]),
            ("Oxyhalides", [
                "LiTaOCl4 lithium conductivity", "LiNbOCl4 lithium conductivity", "NaNbOCl4 sodium conductivity",
                "oxyhalide superionic conductor", "oxychloride glass electrolyte conductivity"]),
        ],
        exclude=["perovskite solar", "halide perovskite", "lead halide", "CsPbBr3", "photovoltaic", "luminescence",
                 "phosphor", "scintillator", "neutron detection", "molten salt"],
    ),
    "complex_hydride": dict(
        title="Complex hydride and closo-borate solid electrolytes",
        about="Borohydrides (LiBH4 and its halide-stabilised forms, Mg(BH4)2-based conductors), closo-borates and "
              "carba-closo-borates (Li2B12H12, Na2B12H12, LiCB11H12, NaCB11H12, LiCB9H10) and their mixtures.",
        ions=["lithium", "sodium", "magnesium"],
        names=["complex hydride solid electrolyte", "LiBH4", "closo-borate", "Na2B12H12", "LiCB11H12"],
        topic=[("Complex hydride aliases", [
            "complex hydride", "borohydride", "closo-borate", "closo-hydroborate", "carba-closo-borate",
            "carba-closo-dodecaborate", "closo-dodecaborate", "closo-decaborate", "nido-borate", "metal hydroborate"]),
            ("Borohydride formulas", [
                "LiBH4", "LiBH4-LiI", "Li4(BH4)3I", "LiBH4-LiNH2", "Li2(BH4)(NH2)", "Mg(BH4)2", "Mg(BH4)(NH2)",
                "Ca(BH4)2", "Na3BH4B12H12", "LiBH4·NH3"]),
            ("closo-Borate formulas", [
                "Li2B12H12", "Na2B12H12", "Li2B10H10", "Na2B10H10", "LiCB11H12", "NaCB11H12", "LiCB9H10", "NaCB9H10",
                "Li(CB9H10)0.7(CB11H12)0.3", "Na2(CB9H10)(CB11H12)", "Na2(B12H12)0.5(B10H10)0.5", "K2B12H12"]),
            ("Parts of formulas (find the mixed members)", ["B12H12", "B10H10", "CB11H12", "CB9H10", "BH4"])],
        queries=[
            ("Hydrides: order-disorder transitions and transport", [
                "LiBH4 hexagonal phase lithium conductivity", "LiBH4 orthorhombic hexagonal transition conductivity",
                "LiBH4 halide stabilization hexagonal phase", "closo-borate order disorder transition conductivity",
                "Na2B12H12 superionic phase transition", "anion reorientation cation diffusion paddle wheel borate",
                "LiCB11H12 lithium superionic conductor", "NaCB11H12 sodium superionic conductor",
                "mixed anion closo-borate conductivity", "Na2B10H10 Na2B12H12 mixed conductivity",
                "carba-closo-borate solid electrolyte battery", "LiBH4 nanoconfinement oxide conductivity",
                "LiBH4 SiO2 interface conductivity", "Mg(BH4)2 magnesium ion conductivity",
                "magnesium borohydride ethylenediamine conductivity", "Li2B12H12 lithium conductivity"]),
            ("Hydrides: stability and cells", [
                "closo-borate electrochemical stability window", "borohydride electrolyte lithium metal stability",
                "complex hydride solid electrolyte all solid state battery"]),
        ],
        exclude=["hydrogen storage", "dehydrogenation", "hydrogen release", "hydrolysis", "reducing agent",
                 "neutron capture", "BNCT", "catalytic reduction"],
    ),
    "beta_alumina": dict(
        title="Beta-alumina solid electrolytes",
        about="Sodium beta- and beta''-alumina (Na2O-Al2O3, Mg- or Li-stabilised beta''), and their potassium and "
              "lithium-exchanged forms, as used in sodium-sulfur, ZEBRA and AMTEC cells.",
        ions=["sodium", "potassium"],
        names=["beta-alumina solid electrolyte", "beta''-alumina", "sodium beta alumina", "Na-β''-Al2O3"],
        topic=[("beta-Alumina aliases", [
            "beta-alumina", "β-alumina", "beta''-alumina", "β''-alumina", "beta double prime alumina",
            "beta-alumina solid electrolyte", "sodium beta alumina", "potassium beta alumina", "Na-β''-alumina",
            "Na-β-alumina", "K-β''-alumina"]),
            ("beta-Alumina formulas", [
                "Na-β''-Al2O3", "Na-β-Al2O3", "NaAl11O17", "Na1.67Mg0.67Al10.33O17", "Na2O·5.33Al2O3",
                "Na2O-Al2O3", "K-β''-Al2O3", "Li-stabilized β''-alumina", "Mg-stabilized β''-alumina"]),
            ("Parts of formulas (find the doped members)", ["Al11O17", "Al10.33O17"])],
        queries=[
            ("beta-Alumina: phases, conduction plane and processing", [
                "beta'' alumina conduction plane sodium", "beta beta'' alumina phase ratio conductivity",
                "Mg stabilized beta'' alumina conductivity", "Li stabilized beta'' alumina conductivity",
                "beta alumina vapor phase conversion conductivity", "beta alumina sintering zirconia toughened",
                "beta alumina grain boundary conductivity", "beta alumina single crystal sodium diffusion",
                "beta alumina ion exchange potassium lithium", "beta alumina water uptake conductivity",
                "beta alumina sodium sulfur battery electrolyte", "beta alumina ZEBRA battery electrolyte",
                "beta alumina AMTEC electrolyte", "beta alumina wetting molten sodium interface"]),
        ],
        exclude=["catalyst support", "alumina catalyst", "Pt/Al2O3", "adsorbent"],
    ),
    "lipon": dict(
        title="LiPON and oxide-glass thin-film electrolytes",
        about="Lithium phosphorus oxynitride (LiPON) and its relatives (LiSiPON, LiBON, LiPOS), amorphous Li3PO4 and "
              "lithium borate, borophosphate and silicate glasses used as thin-film or glassy oxide electrolytes.",
        ions=["lithium"],
        names=["LiPON", "lithium phosphorus oxynitride", "LiPON thin film", "lithium borate glass"],
        topic=[("LiPON and oxide glass aliases", [
            "LiPON", "lithium phosphorus oxynitride", "LiSiPON", "LiBON", "LiPOS", "LiPOxNy", "nitrided Li3PO4",
            "nitrogen-doped Li3PO4", "amorphous Li3PO4", "lithium borophosphate", "lithium borate glass",
            "oxide glass electrolyte", "thin-film electrolyte"]),
            ("Formulas", [
                "Li3.3PO3.9N0.17", "Li2.9PO3.3N0.46", "Li3PO4", "Li3BO3", "Li2O-B2O3", "Li2O-B2O3-P2O5",
                "Li2O-SiO2", "Li2O-P2O5", "Li3BO3-Li2SO4", "Li2.2C0.8B0.2O3"]),
            ("Parts of formulas (find the other compositions)", ["PO3.9N", "PO3.3N", "POxNy"])],
        queries=[
            ("LiPON: nitrogen, structure and transport", [
                "LiPON nitrogen content conductivity", "LiPON apical bridging nitrogen conductivity",
                "LiPON sputtering conditions conductivity", "LiPON thin film lithium metal stability",
                "LiPON interface dendrite suppression", "LiPON atomic layer deposition conductivity",
                "LiPON amorphous structure lithium diffusion simulation", "LiPON electrochemical stability window",
                "LiSiPON thin film conductivity", "LiBON thin film electrolyte"]),
            ("Oxide glasses", [
                "lithium borate glass ionic conductivity", "lithium borophosphate glass conductivity",
                "mixed glass former effect lithium conductivity", "lithium silicate glass conductivity",
                "Li3BO3 sintering aid conductivity", "oxide glass electrolyte thin film battery"]),
        ],
        exclude=["optical glass", "bioactive glass", "glaze"],
    ),
    "nitride": dict(
        title="Nitride, amide and imide solid electrolytes",
        about="Lithium nitride (Li3N) and the lithium nitridophosphates, nitridosilicates, nitridoaluminates and "
              "nitridoborates, with lithium amide and imide conductors.",
        ions=["lithium"],
        names=["lithium nitride", "Li3N", "lithium nitridophosphate", "lithium nitridosilicate"],
        topic=[("Nitride aliases", [
            "lithium nitride", "nitride solid electrolyte", "nitride ionic conductor", "lithium nitridophosphate",
            "nitridophosphate", "lithium nitridosilicate", "nitridosilicate", "lithium nitridoaluminate",
            "lithium nitridoborate", "lithium amide", "lithium imide"]),
            ("Nitride, amide and imide formulas", [
                "Li3N", "α-Li3N", "β-Li3N", "Li7PN4", "LiPN2", "Li10P4N10", "Li2SiN2", "Li5SiN3", "Li8SiN4", "LiSi2N3",
                "Li3AlN2", "Li3BN2", "LiNH2", "Li2NH"])],
        queries=[
            ("Nitrides: transport", [
                "Li3N single crystal lithium conductivity anisotropy", "Li3N hydrogen doping conductivity",
                "Li3N vacancy lithium migration", "Li3N decomposition voltage electrolyte",
                "Li3N interlayer lithium metal anode", "Li7PN4 lithium ion conductivity",
                "LiPN2 lithium conductivity", "lithium nitridosilicate ionic conductivity",
                "Li2SiN2 lithium conduction", "nitride solid electrolyte stability lithium metal",
                "lithium imide Li2NH conductivity", "lithium amide LiNH2 ion conduction"]),
        ],
        exclude=["gallium nitride", "GaN", "light-emitting", "transistor", "HEMT", "hydrogen storage",
                 "dehydrogenation", "hard coating", "cutting tool"],
    ),
    "fluoride": dict(
        title="Fluoride, oxyfluoride and fluoride-ion solid electrolytes",
        about="Lithium and sodium fluorides and oxyfluorides used as solid electrolytes or coatings, and the "
              "fluoride-ion conductors of fluoride-ion batteries (tysonite LaF3, fluorite BaF2-based, PbSnF4 type).",
        ions=["lithium", "sodium", "fluoride"],
        names=["fluoride solid electrolyte", "fluoride ion conductor", "LaF3", "Li3AlF6"],
        topic=[("Fluoride aliases", [
            "fluoride solid electrolyte", "fluoride-ion conductor", "fluoride ion conductor", "fluoride-ion battery",
            "fluoride ion battery", "fluoride-ion conducting", "tysonite", "tysonite-type", "fluorite-type conductor",
            "oxyfluoride solid electrolyte", "lithium oxyfluoride", "fluoride glass electrolyte",
            "lithium fluoride coating"]),
            ("Fluoride formulas", [
                "LaF3", "La1-xBaxF3-x", "La0.9Ba0.1F2.9", "CeF3", "BaF2", "CaF2-BaF2", "Ba1-xLaxF2+x", "Ba0.6La0.4F2.4",
                "PbSnF4", "BaSnF4", "Li3AlF6", "LiAlF4", "Li2ZrF6", "Li3ScF6", "Li3GaF6", "Li3InF6", "LiF-AlF3"])],
        queries=[
            ("Fluoride-ion conductors", [
                "tysonite LaF3 fluoride ion conductivity", "La1-xBaxF3-x fluoride ion conductivity",
                "BaF2 CaF2 nanocrystalline fluoride conductivity", "PbSnF4 fluoride ion conductor",
                "BaSnF4 fluoride ion conductivity", "fluoride ion battery solid electrolyte",
                "fluoride ion conductor room temperature", "fluoride ion migration mechanism"]),
            ("Lithium and sodium fluorides", [
                "Li3AlF6 lithium conductivity", "LiAlF4 glass lithium conductivity", "Li2ZrF6 lithium conductivity",
                "lithium fluoride based solid electrolyte", "oxyfluoride lithium ion conductor",
                "fluoride coating lithium ion conductivity cathode"]),
        ],
        exclude=["dental", "toothpaste", "fluorosis", "defluoridation", "drinking water", "radiotracer", "PET imaging",
                 "scintillator", "upconversion", "luminescence", "phosphor", "optical fiber", "laser crystal"],
        properties=[("Fluoride transport", ["fluoride ion conductivity", "fluoride-ion conductivity", "F- conductivity",
                                            "fluoride ion migration"])],
    ),
    "mixed_anion": dict(
        title="Mixed-anion solid electrolytes (oxysulfides, sulfide-halides, nitride-halides)",
        about="Solid electrolytes with two or more anions: oxysulfide glasses and crystals, sulfide-halides such as "
              "Li7P2S8I and Li4PS4I, and nitride-halides such as Li6NBr3 and Li5NCl2. The argyrodites, oxyhalides and "
              "anti-perovskites, mixed-anion too, have files of their own.",
        ions=["lithium", "sodium"],
        names=["mixed-anion solid electrolyte", "oxysulfide electrolyte", "Li7P2S8I", "nitride halide lithium conductor"],
        topic=[("Mixed-anion aliases", [
            "mixed-anion", "mixed anion", "heteroanionic", "dual-anion", "oxysulfide", "oxy-sulfide", "oxysulfide glass",
            "sulfide-halide", "thiohalide", "chalcohalide", "nitride-halide", "nitride halide", "anion mixing"]),
            ("Mixed-anion formulas", [
                "Li7P2S8I", "Li4PS4I", "Li3PS4-xOx", "Li2S-P2S5-P2O5", "Li2S-P2S5-Li3PO4", "Li2S-SiS2-Li4SiO4",
                "Li2S-SiS2-Li3PO4", "Li6NBr3", "Li5NCl2", "Na3PS4-xOx", "Li10GeP2S11.7O0.3"])],
        queries=[
            ("Mixed anions: structure and transport", [
                "oxysulfide glass lithium conductivity", "oxygen substitution sulfide electrolyte stability conductivity",
                "Li7P2S8I lithium conductivity", "Li4PS4I lithium conductivity", "sulfide halide solid electrolyte",
                "mixed anion effect ionic conductivity", "anion substitution lithium diffusion",
                "nitride halide lithium conductor", "Li6NBr3 lithium conductivity", "heteroanionic lithium conductor",
                "polyanion mixing conductivity solid electrolyte"]),
        ],
        exclude=["phosphor", "luminescence", "photocatalytic", "thermoelectric"],
    ),
    "oxide_chemistry": dict(
        title="Oxide conductors by chemistry: niobates, tantalates, zirconates, aluminates, borates, silicates, …",
        about="Lithium and sodium oxides not covered by a structure-type file, grouped by chemistry: niobates "
              "(LiNbO3, Li3NbO4), tantalates (LiTaO3, Li7TaO6), zirconates (Li2ZrO3, Li6Zr2O7, Li8ZrO6), aluminates "
              "(LiAlO2, Li5AlO4), titanates, tungstates, molybdates, borates, silicates and germanates — as solid "
              "electrolytes, amorphous films and cathode coatings.",
        ions=["lithium", "sodium"],
        names=["lithium niobate solid electrolyte", "lithium tantalate electrolyte", "lithium zirconate ionic conductor",
               "lithium borate solid electrolyte", "lithium silicate solid electrolyte"],
        topic=[("Oxide chemistry aliases", [
            "lithium niobate", "amorphous LiNbO3", "lithium tantalate", "lithium zirconate", "lithium aluminate",
            "lithium borate", "lithium silicate", "lithium germanate", "lithium tungstate", "lithium molybdate",
            "titanate solid electrolyte", "lithium-ion conducting oxide", "oxide solid electrolyte"]),
            ("Oxide formulas", [
                "LiNbO3", "Li3NbO4", "Li7NbO6", "LiTaO3", "Li3TaO4", "Li7TaO6", "Li2ZrO3", "Li6Zr2O7", "Li8ZrO6",
                "LiAlO2", "Li5AlO4", "Li2SiO3", "Li2Si2O5", "Li2GeO3", "Li2B4O7", "LiBO2", "Li2WO4", "Li2MoO4"])],
        queries=[
            ("Oxide chemistries: transport and coatings", [
                "LiNbO3 coating ionic conductivity cathode interface", "amorphous LiNbO3 lithium conductivity",
                "LiTaO3 coating lithium conductivity", "Li7TaO6 lithium ion conductivity", "Li6Zr2O7 lithium conductivity",
                "Li2ZrO3 lithium ion conductivity", "Li5AlO4 lithium conductivity", "LiAlO2 coating lithium conductivity",
                "Li2SiO3 lithium ion conductivity", "Li2B4O7 lithium ion conductivity", "Li2WO4 lithium conductivity",
                "lithium borate coating ionic conductivity", "amorphous oxide lithium conductor thin film"]),
        ],
        exclude=["waveguide", "nonlinear optical", "nonlinear optics", "surface acoustic wave", "electro-optic",
                 "photonic", "modulator", "second harmonic", "periodically poled", "piezoelectric", "ferroelectric",
                 "CO2 capture", "CO2 sorption", "tritium", "breeder blanket", "thermoluminescence", "dosimeter",
                 "dosimetry"],
    ),
    "oxide_structure": dict(
        title="Oxide conductors by structure type: spinel, pyrochlore, scheelite, brownmillerite, olivine-related",
        about="Lithium and sodium conductors of structure types without a file of their own: spinel, pyrochlore "
              "(including the pyrochlore-type oxyfluorides), scheelite, brownmillerite, olivine-related and layered "
              "oxide frameworks.",
        ions=["lithium", "sodium"],
        names=["spinel lithium ion conductor", "pyrochlore lithium ion conductor", "scheelite type ion conductor",
               "brownmillerite ion conductor"],
        topic=[("Structure-type aliases", [
            "spinel-type solid electrolyte", "spinel solid electrolyte", "spinel lithium ion conductor",
            "spinel-type lithium conductor", "pyrochlore solid electrolyte", "pyrochlore-type solid electrolyte",
            "pyrochlore lithium conductor", "pyrochlore-type oxyfluoride", "scheelite-type solid electrolyte",
            "scheelite ion conductor", "brownmillerite", "brownmillerite-type", "olivine-type ion conductor",
            "layered oxide ion conductor", "Ruddlesden-Popper lithium conductor"])],
        queries=[
            ("Structure types: transport", [
                "spinel lithium ion conductor solid electrolyte", "spinel structure lithium diffusion pathway",
                "pyrochlore lithium ion conductor", "pyrochlore oxyfluoride lithium conductivity",
                "scheelite structure ionic conductivity", "brownmillerite ionic conductivity vacancy ordering",
                "olivine structure lithium ion conduction electrolyte", "layered oxide fast lithium ion conductor",
                "new structure type lithium superionic conductor discovery"]),
        ],
        exclude=["phosphor", "luminescence", "photoluminescence", "spin ice", "frustrated magnet",
                 "magnetic frustration", "ferrimagnetic", "oxygen evolution"],
    ),
    "polymer": dict(
        title="Polymer electrolytes (solvent-free, gel, single-ion, block copolymer)",
        about="Solid and gel polymer electrolytes: polyethers (PEO), polycarbonates, polysiloxanes, PVDF-HFP, PAN and "
              "PMMA gels, polymer-in-salt and salt-in-polymer systems, single-ion conducting polymers, cross-linked and "
              "block copolymer electrolytes.",
        ions=["lithium", "sodium"],
        names=["solid polymer electrolyte", "PEO electrolyte", "poly(ethylene oxide) electrolyte",
               "gel polymer electrolyte", "single-ion conducting polymer"],
        topic=[("Polymer electrolyte aliases", [
            "solid polymer electrolyte", "polymer electrolyte", "gel polymer electrolyte", "dry polymer electrolyte",
            "solvent-free polymer electrolyte", "polymer-in-salt", "salt-in-polymer", "single-ion conducting polymer",
            "single-ion polymer electrolyte", "single-ion conductor", "block copolymer electrolyte",
            "cross-linked polymer electrolyte", "polymer network electrolyte", "polycarbonate electrolyte",
            "polysiloxane electrolyte", "polyether electrolyte"]),
            ("Polymers", [
                "PEO-based", "PEO electrolyte", "poly(ethylene oxide)", "polyethylene oxide", "poly(propylene carbonate)",
                "poly(ethylene carbonate)", "poly(trimethylene carbonate)", "PVDF-HFP",
                "poly(vinylidene fluoride-co-hexafluoropropylene)", "polyacrylonitrile", "poly(methyl methacrylate)",
                "PS-b-PEO", "SEO block copolymer", "polycaprolactone electrolyte"])],
        queries=[
            ("Polymer electrolytes: transport", [
                "PEO LiTFSI ionic conductivity", "PEO segmental motion lithium transport",
                "polymer electrolyte Vogel-Tammann-Fulcher conductivity", "polymer electrolyte lithium transference number",
                "polymer-in-salt electrolyte conductivity", "single-ion conducting polymer electrolyte conductivity",
                "block copolymer electrolyte morphology conductivity", "cross-linked polymer electrolyte conductivity",
                "polycarbonate electrolyte lithium transport", "polysiloxane electrolyte conductivity",
                "gel polymer electrolyte PVDF-HFP conductivity", "polymer electrolyte crystallinity conductivity",
                "polymer electrolyte electrochemical stability high voltage", "sodium polymer electrolyte conductivity"]),
        ],
        exclude=["drug delivery", "drug release", "tissue engineering", "wound dressing", "biomedical", "cell viability",
                 "plasma electrolytic oxidation", "corrosion", "membrane distillation", "food packaging"],
        properties=[("Polymer transport", ["Vogel-Tammann-Fulcher", "VTF", "segmental motion", "segmental relaxation",
                                           "glass transition temperature", "free volume", "pseudo-activation energy"])],
    ),
    "hybrid": dict(
        title="Composite and framework electrolytes (polymer-ceramic, MOF, COF, plastic crystals, ionogels)",
        about="Polymer-ceramic composite electrolytes (ceramic-in-polymer, polymer-in-ceramic), inorganic-organic "
              "hybrids, metal-organic framework (MOF) and covalent organic framework (COF) electrolytes, porous "
              "framework, organic ionic plastic crystal and ionogel electrolytes.",
        ions=["lithium", "sodium"],
        names=["composite polymer electrolyte", "polymer ceramic composite electrolyte", "MOF solid electrolyte",
               "covalent organic framework electrolyte", "plastic crystal electrolyte"],
        topic=[("Composite and framework aliases", [
            "composite polymer electrolyte", "composite solid electrolyte", "polymer-ceramic composite",
            "ceramic-polymer composite", "ceramic-in-polymer", "polymer-in-ceramic", "hybrid solid electrolyte",
            "inorganic-organic hybrid electrolyte", "organic-inorganic hybrid electrolyte", "MOF electrolyte",
            "MOF-based electrolyte", "MOF-based solid electrolyte", "metal-organic framework electrolyte",
            "metal–organic framework electrolyte", "COF electrolyte", "covalent organic framework electrolyte",
            "ionic covalent organic framework", "porous framework electrolyte", "zeolitic imidazolate framework electrolyte",
            "organic ionic plastic crystal", "plastic crystal electrolyte", "succinonitrile electrolyte",
            "ionogel electrolyte", "quasi-solid-state electrolyte"])],
        queries=[
            ("Composites", [
                "PEO LLZO composite electrolyte conductivity", "PEO LATP composite electrolyte conductivity",
                "ceramic filler polymer electrolyte interface conduction", "polymer ceramic interface lithium transport",
                "percolation ceramic filler composite electrolyte", "vertically aligned ceramic polymer electrolyte"]),
            ("Frameworks, plastic crystals and ionogels", [
                "metal organic framework solid electrolyte lithium conductivity", "MOF single ion conductor",
                "covalent organic framework lithium ion conduction", "ionic covalent organic framework conductivity",
                "succinonitrile plastic crystal electrolyte conductivity", "organic ionic plastic crystal conductivity",
                "ionogel electrolyte lithium conductivity"]),
        ],
        exclude=["gas adsorption", "gas separation", "CO2 capture", "drug delivery", "water harvesting", "heterogeneous catalysis"],
    ),
    "multivalent": dict(
        title="Multivalent-ion solid electrolytes (Mg2+, Ca2+, Zn2+, Al3+, Sc3+)",
        about="Solid conductors of divalent and trivalent ions: magnesium (spinel chalcogenides such as MgSc2Se4, "
              "NASICON-type phosphates, borohydrides), calcium and zinc conductors, and the trivalent-cation conductors "
              "of the Sc2(WO4)3 type.",
        ions=["magnesium", "calcium", "zinc"],
        names=["magnesium solid electrolyte", "magnesium ion conductor", "calcium ion conductor",
               "zinc ion solid electrolyte", "trivalent cation conductor"],
        topic=[("Multivalent conductor aliases", [
            "magnesium solid electrolyte", "solid-state magnesium electrolyte", "magnesium ion conductor",
            "Mg-ion conductor", "magnesium superionic conductor", "calcium solid electrolyte", "calcium ion conductor",
            "Ca-ion conductor", "zinc ion conductor", "Zn-ion solid electrolyte", "aluminium ion conductor",
            "aluminum ion conductor", "trivalent cation conductor", "trivalent ion conduction",
            "multivalent ion conductor", "divalent cation conductor"]),
            ("Multivalent formulas", [
                "MgSc2Se4", "MgSc2S4", "MgZr4(PO4)6", "Mg0.5Zr2(PO4)3", "Mg0.5Ti2(PO4)3", "Mg(BH4)2", "Mg(BH4)(NH2)",
                "Ca(BH4)2", "Sc2(WO4)3", "Al2(WO4)3", "ZnPS3"])],
        queries=[
            ("Multivalent ions: transport", [
                "MgSc2Se4 magnesium ion conductivity", "spinel chalcogenide magnesium conductor",
                "magnesium ion migration barrier solid", "NASICON type magnesium conductor", "MgZr4(PO4)6 conductivity",
                "magnesium borohydride solid electrolyte conductivity", "calcium ion migration solid electrolyte",
                "zinc ion conduction solid electrolyte", "Sc2(WO4)3 trivalent ion conduction",
                "Al2(WO4)3 aluminum ion conduction", "multivalent ion mobility solids design principles"]),
        ],
        exclude=["magnesium alloy", "corrosion", "biodegradable", "implant", "bone", "cement", "fertilizer",
                 "dietary", "zinc oxide nanoparticles", "galvanizing", "aqueous zinc"],
        properties=[("Multivalent transport", ["magnesium ion conductivity", "Mg2+ conductivity", "calcium ion conductivity",
                                               "zinc ion conductivity", "divalent ion conduction", "multivalent ion migration"])],
    ),
}

# Garnet and NASICON: their hand-written groups come from configs/garnet_nasicon.yaml; their main names here.
FROM_BASE = {
    "garnet": dict(title="Garnet-type solid electrolytes",
                   about="Lithium garnets: Li7La3Zr2O12 (LLZO) and its Al-, Ga-, Ta-, Nb-, W-doped forms, Li5La3M2O12 "
                         "(M = Ta, Nb), Li6ALa2M2O12 (A = Ca, Sr, Ba) and the Te, Hf and Sn members.",
                   ions=["lithium"], names=["garnet solid electrolyte", "LLZO", "LLZTO", "Li7La3Zr2O12", "Ga-LLZO"],
                   match=("garnet", "llzo", "llzto", "li7la3zr2o12", "la3zr2o12", "lithium lanthanum", "llz")),
    "nasicon": dict(title="NASICON-type solid electrolytes",
                    about="NASICON (Na superionic conductor) frameworks: Na1+xZr2SixP3-xO12 (NZSP) and its dopings, "
                          "Na3Sc2(PO4)3, and the lithium members Li1+xAlxTi2-x(PO4)3 (LATP), Li1+xAlxGe2-x(PO4)3 (LAGP), "
                          "LiZr2(PO4)3, LiHf2(PO4)3.",
                    ions=["lithium", "sodium"], names=["NASICON solid electrolyte", "NZSP", "Na3Zr2Si2PO12", "LATP", "LAGP",
                                                      "LiZr2(PO4)3"],
                    match=("nasicon", "nzsp", "nzp", "latp", "lagp", "ltap", "lzp", "po4)3", "si2po12", "zirconium phosphate",
                           "titanium phosphate", "germanium phosphate", "zr2(sio4)")),
}
GARNET_EXCLUDE = ["metamorphic", "eclogite", "granulite", "geothermobarometry", "mantle", "petrology", "YAG",
                  "yttrium aluminum garnet", "YIG", "yttrium iron garnet", "magnonic", "ferrimagnetic", "phosphor",
                  "luminescence", "scintillator"]


# ----------------------------------------------------------------------------------------------------------------
# Reading the base job (its comment headings tell the groups apart)
# ----------------------------------------------------------------------------------------------------------------
def _groups(text: str, start: str, stop: str) -> Groups:
    """The (heading, items) of a list of the base file, between the key `start` and the key `stop`."""
    block = text.split(f"\n{start}\n", 1)[1].split(f"\n{stop}", 1)[0]
    groups: Groups = []
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            heading = stripped.lstrip("#").strip()
            if heading and not set(heading) <= {"-"}:
                if groups and not groups[-1][1]:  # a heading written on two lines
                    groups[-1] = (f"{groups[-1][0]} {heading}", [])
                else:
                    groups.append((heading, []))
        elif stripped.startswith("- "):
            if not groups:
                groups.append(("", []))
            groups[-1][1].append(json.loads(stripped[2:]) if stripped[2:].startswith('"') else stripped[2:])
    return [(h.split(". ")[0] if len(h) > 90 else h, items) for h, items in groups if items]


def _which(text: str) -> str:
    low = text.lower()
    garnet = any(w in low for w in FROM_BASE["garnet"]["match"])
    nasicon = any(w in low for w in FROM_BASE["nasicon"]["match"])
    return "both" if garnet and nasicon else "garnet" if garnet else "nasicon" if nasicon else ""


def _base_parts(text: str) -> Dict[str, Dict[str, Groups]]:
    """The base job's query and topic groups, sorted into garnet's and NASICON's."""
    parts: Dict[str, Dict[str, Groups]] = {"garnet": {"queries": [], "topic": []}, "nasicon": {"queries": [], "topic": []}}
    for kind, start, stop in (("queries", "  queries:", "  years:"), ("topic", "  topic_words:", "  property_words:")):
        for heading, items in _groups(text, start, stop):
            whole = _which(heading)
            if whole in ("garnet", "nasicon"):
                parts[whole][kind].append((heading, items))
                continue
            for family in ("garnet", "nasicon"):  # a mixed group (methods): each item to its family
                mine = [item for item in items if _which(item) in (family, "both")]
                if mine:
                    parts[family][kind].append((heading, mine))
    return parts


# ----------------------------------------------------------------------------------------------------------------
# Writing
# ----------------------------------------------------------------------------------------------------------------
def _q(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def _list(groups: Groups, indent: str = "    ") -> str:
    out = []
    for heading, items in groups:
        out.append(f"{indent}# {heading}")
        out += [f"{indent}- {_q(item)}" for item in items]
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def _transport(names: List[str], ions: List[str], seen: set) -> Groups:
    groups = []
    for name in names:
        items = []
        for template in TRANSPORT:
            for ion in (ions if "{ion}" in template else [ions[0]]):
                query = re.sub(r"\s+", " ", template.format(a=name, ion=ion)).strip()
                if query.lower() not in seen:
                    seen.add(query.lower())
                    items.append(query)
        if items:
            groups.append((f"{name}: every transport measurement and method", items))
    return groups


_JOINED = re.compile(r"[0-9A-Za-z)]-[A-Z]")  # two formulas joined by a hyphen: Li2S-P2S5, Li4SiO4-Li3PO4


def _dashes(items: List[str]) -> List[str]:
    """Each formula pair written with a hyphen also with an en dash (Li2S–P2S5), as titles often write it."""
    out = []
    for item in items:
        out.append(item)
        if " " not in item and _JOINED.search(item):
            out.append(_JOINED.sub(lambda m: m.group(0).replace("-", "–"), item))
    return out


def _dedupe(groups: Groups, seen: set, dashes: bool = False) -> Groups:
    out = []
    for heading, items in groups:
        kept = []
        for item in (_dashes(items) if dashes else items):
            if item.lower() not in seen:
                seen.add(item.lower())
                kept.append(item)
        if kept:
            out.append((heading, kept))
    return out


def job_text(key: str, title: str, about: str, queries: Groups, topic: Groups, exclude: List[str], shared: str,
             property_block: str, extra_properties: Groups = ()) -> str:
    n_queries = sum(len(items) for _, items in queries)
    n_topic = sum(len(items) for _, items in topic)
    wrapped = re.sub(r"(.{1,110})(\s+|$)", r"# \1\n", about).rstrip()
    kind, prototype = TAXONOMY.get(key, ("", ""))
    taxonomy = (f"# Kind: {kind}.\n" + re.sub(r"(.{1,100})(\s+|$)", r"#   \1\n", f"Prototype: {prototype}.")
                if kind else "")
    extra = ("\n" + _list(list(extra_properties))) if extra_properties else ""
    return f"""# {title}
#
{wrapped}
#
{taxonomy}#
# {n_queries} queries, {n_topic} topic words. Written by scripts/families/make_family_jobs.py; edit this copy freely
# (“Search settings…” in the Web scraping window), or the script to change every family at once.
#
# Run (each job keeps its own DOI list, PDF folder and database):
#   mme-web run --job configs/{key}.yaml          # extracts into WebScraping/web_output_{key}
#   mme-rank --domain electrolyte --source WebScraping/web_output_{key} --kind arrhenius

name: {key}

# Empty: the e-mail entered in the window ("API keys…", saved as MME_EMAIL in ~/MoukhlijMatExtract/.env) is used.
contact_email: ""

search:
  queries:
{_list(queries)}
{shared.replace("dois_garnet_nasicon", f"dois_{key}")}
screen:
  topic_words:
{_list(topic)}
{property_block.rstrip()}
{extra}
  exclude_words:
{chr(10).join(f"    - {_q(word)}" for word in exclude)}

  min_score: 2
  # Papers no free copy is known for are kept too: the repositories and the publishers' services are asked,
  # and what none of them has goes to to_download_by_hand.csv (with its link).
  propose_closed: true
  review: false

fetch:
  folder: WebScraping/papers_{key}
  sources: [elsevier, wiley, aps, openalex, unpaywall, publisher, arxiv, pmc, osti, hal, zenodo, datacite,
            semanticscholar, ads, openaire, core, crossref]
  workers: 4
  max_pdf_mb: 60

extract:
  properties: [Activation_Energy, Ionic_Conductivity, Diffusion_Coefficient, Electronic_Conductivity,
               Ionic_Radius]
  require_material: true
  # Materials of another kind (electrodes, interphase salts) are flagged; the ranking leaves them out.
  domain: electrolyte
"""


def write_taxonomy(every: Dict[str, dict]) -> None:
    """docs/FAMILIES.md: every family of the job files, with its kind, prototype, mobile ions and examples."""
    rows = []
    for key, family in every.items():
        kind, prototype = TAXONOMY.get(key, ("", ""))
        formulas = [w for _, words in family["topic"] for w in words if re.search(r"\d", w) and " " not in w][:5]
        n_queries, n_topic = family.get("counts", (0, 0))
        rows.append(f"| [`{key}.yaml`](../resources/configs/{key}.yaml) | {family['title']} | {kind} | {prototype} | "
                    f"{', '.join(family['ions'])} | {', '.join(formulas) or '—'} | {n_queries} | {n_topic} |")
    text = "\n".join([
        "# The families of solid electrolytes",
        "",
        "One job file of the web search per family (`configs/`, copied into `~/MoukhlijMatExtract/configs/`), written by",
        "`scripts/families/make_family_jobs.py`. Each has its own queries, topic words, exclusions, DOI list, PDF folder",
        "and database (`WebScraping/web_output_<family>`). `garnet_nasicon.yaml` holds garnet and NASICON together.",
        "",
        "The literature groups electrolytes in more than one way, and so do the files. **Kind** says which:",
        "- **crystal-structure type** — one prototype structure and its relatives (garnet, NASICON, argyrodite, …);",
        "- **chemical family** — by anion or polyanion, whatever the structure (halides, nitrides, fluorides, …);",
        "- **composition system** — glasses and glass-ceramics along a join (Li2S–P2S5);",
        "- **material class** — polymers, composites, amorphous films;",
        "- **grouping by mobile ion** — the multivalent conductors.",
        "",
        "A material can belong to more than one: Li6PS5Cl is an argyrodite (structure type) and a sulfide-halide",
        "(mixed-anion chemical family). The files overlap where the literature does; each keeps its own database.",
        "",
        "| Job file | Family | Kind | Prototype, space groups | Mobile ions | Examples | Queries | Topic words |",
        "|---|---|---|---|---|---|---:|---:|",
        *rows,
        "",
        "Every family's queries add, to its own: each of its main names with every transport measurement and method",
        "(ionic conductivity, activation energy, migration barrier, NMR, AIMD, …), the older names of fast ion conduction",
        "(fast ion conductor, superionic conductor) and the transport mechanisms (concerted migration, vacancy and",
        "interstitial mechanisms, paddle-wheel, percolation, bottleneck size). A formula is found however a title writes",
        "it (spaces, subscripts), and a part of a family's formula finds its doped members.",
        ""])
    (ROOT / "docs" / "FAMILIES.md").write_text(text, encoding="utf-8")


def main() -> int:
    from WebScraping.averageScrap.job import load_job
    base = BASE.read_text(encoding="utf-8")
    shared = "  years:" + base.split("\n  years:", 1)[1].split("\nscreen:", 1)[0].rstrip("\n")
    property_block = "  property_words:\n" + base.split("\n  property_words:\n", 1)[1].split("\n  # \"Garnet\" can refer", 1)[0]
    parts = _base_parts(base)
    OUT.mkdir(parents=True, exist_ok=True)
    written = {}
    every = {**{k: dict(v, queries=parts[k]["queries"], topic=parts[k]["topic"],
                        exclude=GARNET_EXCLUDE if k == "garnet" else []) for k, v in FROM_BASE.items()}, **FAMILIES}
    for key, family in every.items():
        seen: set = set()
        mechanisms = [(f"{family['names'][0]}: transport mechanisms", [f"{family['names'][0]} {m}" for m in MECHANISMS])]
        queries = _dedupe(family["queries"], seen) + _transport(family["names"], family["ions"], seen) + \
            _dedupe(mechanisms, seen)
        topic = _dedupe(family["topic"], set(), dashes=True)
        exclude = list(dict.fromkeys(family["exclude"] + SHARED_EXCLUDE))
        properties = [MECHANISM_WORDS, *family.get("properties", [])]
        text = job_text(key, family["title"], family["about"], queries, topic, exclude, shared, property_block,
                        properties)
        path = OUT / f"{key}.yaml"
        path.write_text(text, encoding="utf-8")
        job = load_job(str(path))  # the loader is the judge of a job file
        clash = {w.lower() for w in job.screen.topic_words} & {w.lower() for w in job.screen.exclude_words}
        assert not clash, f"{key}: topic and excluded words clash: {clash}"
        written[key] = (len(job.search.queries), len(job.screen.topic_words))
        family["counts"] = written[key]

    write_taxonomy(every)

    # The article's job: the garnet + NASICON base, with the transport queries of both families added.
    seen = {q.lower() for q in load_job(str(BASE)).search.queries}
    extra = _transport(FROM_BASE["garnet"]["names"], FROM_BASE["garnet"]["ions"], seen) + \
        _transport(FROM_BASE["nasicon"]["names"], FROM_BASE["nasicon"]["ions"], seen)
    if extra:
        anchor = "    # -------------------------------------------------------------------------\n    # COMPUTATIONAL METHODS"
        block = "".join(f"    # -------------------------------------------------------------------------\n    # {h}\n"
                        "    # -------------------------------------------------------------------------\n"
                        + "".join(f"    - {_q(q)}\n" for q in items) + "\n" for h, items in extra)
        base = base.replace(anchor, block + anchor, 1)
        BASE.write_text(base, encoding="utf-8")
    job = load_job(str(BASE))
    written["garnet_nasicon"] = (len(job.search.queries), len(job.screen.topic_words))
    for key, (n_queries, n_topic) in written.items():
        print(f"{key:16} {n_queries:4} queries  {n_topic:4} topic words")
    return 0


if __name__ == "__main__":
    sys.exit(main())
