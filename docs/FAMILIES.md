# The families of solid electrolytes

One job file of the web search per family (`configs/`, copied into `~/MoukhlijMatExtract/configs/`), written by
`scripts/families/make_family_jobs.py`. Each has its own queries, topic words, exclusions, DOI list, PDF folder
and database (`WebScraping/web_output_<family>`). `garnet_nasicon.yaml` holds garnet and NASICON together.

The literature groups electrolytes in more than one way, and so do the files. **Kind** says which:
- **crystal-structure type** — one prototype structure and its relatives (garnet, NASICON, argyrodite, …);
- **chemical family** — by anion or polyanion, whatever the structure (halides, nitrides, fluorides, …);
- **composition system** — glasses and glass-ceramics along a join (Li2S–P2S5);
- **material class** — polymers, composites, amorphous films;
- **grouping by mobile ion** — the multivalent conductors.

A material can belong to more than one: Li6PS5Cl is an argyrodite (structure type) and a sulfide-halide
(mixed-anion chemical family). The files overlap where the literature does; each keeps its own database.

| Job file | Family | Kind | Prototype, space groups | Mobile ions | Examples | Queries | Topic words |
|---|---|---|---|---|---|---:|---:|
| [`garnet.yaml`](../configs/garnet.yaml) | Garnet-type solid electrolytes | crystal-structure type | garnet A3B2(XO4)3; Li7La3Zr2O12: cubic Ia-3d, tetragonal I41/acd | lithium | Li7La3Zr2O12, Li6.4La3Zr1.4Ta0.6O12, Li6.5La3Zr1.5Ta0.5O12, Li6.25Al0.25La3Zr2O12, Li6.75La3Zr1.75Ta0.25O12 | 256 | 55 |
| [`nasicon.yaml`](../configs/nasicon.yaml) | NASICON-type solid electrolytes | crystal-structure type | NZP / NaZr2(PO4)3 framework, rhombohedral R-3c; Na3Zr2Si2PO12 also monoclinic C2/c | lithium, sodium | Na3Zr2Si2PO12, Na1+xZr2SixP3-xO12, Na3.4Zr2Si2.4P0.6O12, Na3Sc2(PO4)3, Na3Hf2Si2PO12 | 294 | 55 |
| [`lisicon.yaml`](../configs/lisicon.yaml) | LISICON and thio-LISICON solid electrolytes | crystal-structure type | gamma-Li3PO4 (Pnma): Li14Zn(GeO4)4; thio-LISICON Li4-xGe1-xPxS4 | lithium | gamma-Li3PO4, γ-Li3PO4, Li3PO4-type, Li14Zn(GeO4)4, Li4SiO4 | 127 | 36 |
| [`lgps.yaml`](../configs/lgps.yaml) | LGPS-type (Li10GeP2S12 family) solid electrolytes | crystal-structure type | Li10GeP2S12, tetragonal P42/nmc | lithium | Li10GeP2S12-type, Li10GeP2S12, Li10SnP2S12, Li10SiP2S12, Li11Si2PS12 | 129 | 21 |
| [`argyrodite.yaml`](../configs/argyrodite.yaml) | Argyrodite-type solid electrolytes | crystal-structure type | Ag8GeS6 argyrodite; Li6PS5X, cubic F-43m | lithium, sodium | Li6PS5Cl, Li6PS5Br, Li6PS5I, Li6PS5X, Li5.5PS4.5Cl1.5 | 147 | 26 |
| [`sulfide_glass.yaml`](../configs/sulfide_glass.yaml) | Thiophosphate glasses, glass-ceramics and sodium thio-salts | composition system | Li2S-P2S5 and Na2S-P2S5 glasses and glass-ceramics; Li7P3S11 (P-1), beta-Li3PS4 (Pnma), cubic Na3PS4 (I-43m) | lithium, sodium | Li2S-P2S5, Li7P3S11, Li3PS4, β-Li3PS4, beta-Li3PS4 | 153 | 45 |
| [`perovskite.yaml`](../configs/perovskite.yaml) | Perovskite-type lithium-ion conductors (LLTO and relatives) | crystal-structure type | ABO3 perovskite, A-site deficient; Li3xLa2/3-xTiO3 (P4/mmm, Cmmm) | lithium | Li3xLa2/3-xTiO3, La2/3-xLi3xTiO3, Li0.33La0.56TiO3, Li0.34La0.51TiO2.94, Li0.5La0.5TiO3 | 130 | 23 |
| [`antiperovskite.yaml`](../configs/antiperovskite.yaml) | Anti-perovskite solid electrolytes | crystal-structure type | anti-perovskite (anti-ABX3); Li3OCl, cubic Pm-3m | lithium, sodium | Li3OCl, Li3OBr, Li3OCl0.5Br0.5, Li3OI, Li2OHCl | 145 | 27 |
| [`halide.yaml`](../configs/halide.yaml) | Halide and oxyhalide solid electrolytes | chemical family (anion: Cl, Br, I, F; oxyhalides) | Li3MX6 (Li3YCl6 P-3m1, Li3InCl6 C2/m), Li2MCl6 (Li2ZrCl6 P-3m1) | lithium, sodium | Li3MCl6, Li3MX6, Li2MCl6, Na3MCl6, Li3YCl6 | 151 | 59 |
| [`complex_hydride.yaml`](../configs/complex_hydride.yaml) | Complex hydride and closo-borate solid electrolytes | chemical family (complex anions BH4-, closo-borates) | LiBH4 (high-T P63mc), Li2B12H12, LiCB11H12 | lithium, sodium, magnesium | LiBH4, LiBH4-LiI, Li4(BH4)3I, LiBH4-LiNH2, Li2(BH4)(NH2) | 167 | 39 |
| [`beta_alumina.yaml`](../configs/beta_alumina.yaml) | Beta-alumina solid electrolytes | crystal-structure type | beta-alumina P63/mmc, beta''-alumina R-3m | sodium, potassium | Na-β''-Al2O3, Na-β-Al2O3, NaAl11O17, Na1.67Mg0.67Al10.33O17, Na2O·5.33Al2O3 | 119 | 23 |
| [`lipon.yaml`](../configs/lipon.yaml) | LiPON and oxide-glass thin-film electrolytes | material class (amorphous thin films and oxide glasses) | amorphous Li-P-O-N; lithium borate and borophosphate glasses | lithium | Li3.3PO3.9N0.17, Li2.9PO3.3N0.46, Li3PO4, Li3BO3, Li2O-B2O3 | 103 | 31 |
| [`nitride.yaml`](../configs/nitride.yaml) | Nitride, amide and imide solid electrolytes | chemical family (anion: N3-, with amides and imides) | Li3N (P6/mmm); nitridophosphates (Li7PN4), nitridosilicates (Li2SiN2) | lithium | Li3N, α-Li3N, β-Li3N, Li7PN4, LiPN2 | 100 | 25 |
| [`fluoride.yaml`](../configs/fluoride.yaml) | Fluoride, oxyfluoride and fluoride-ion solid electrolytes | chemical family (anion: F-, with oxyfluorides) | tysonite LaF3 (P-3c1), fluorite (Fm-3m); Li3AlF6 | lithium, sodium, fluoride | LaF3, La1-xBaxF3-x, La0.9Ba0.1F2.9, CeF3, BaF2 | 135 | 32 |
| [`mixed_anion.yaml`](../configs/mixed_anion.yaml) | Mixed-anion solid electrolytes (oxysulfides, sulfide-halides, nitride-halides) | chemical family (two or more anions) | oxysulfides, sulfide-halides (Li7P2S8I), nitride-halides (Li6NBr3) | lithium, sodium | Li7P2S8I, Li4PS4I, Li3PS4-xOx, Li2S-P2S5-P2O5, Li2S-P2S5-Li3PO4 | 116 | 28 |
| [`oxide_chemistry.yaml`](../configs/oxide_chemistry.yaml) | Oxide conductors by chemistry: niobates, tantalates, zirconates, aluminates, borates, silicates, … | chemical families (oxide anions) | niobates, tantalates, zirconates, aluminates, titanates, tungstates, molybdates, borates, silicates, germanates | lithium, sodium | LiNbO3, Li3NbO4, Li7NbO6, LiTaO3, Li3TaO4 | 142 | 31 |
| [`oxide_structure.yaml`](../configs/oxide_structure.yaml) | Oxide conductors by structure type: spinel, pyrochlore, scheelite, brownmillerite, olivine-related | crystal-structure types not covered elsewhere | spinel (Fd-3m), pyrochlore (Fd-3m), scheelite (I41/a), brownmillerite, olivine-related, layered | lithium, sodium | — | 114 | 15 |
| [`polymer.yaml`](../configs/polymer.yaml) | Polymer electrolytes (solvent-free, gel, single-ion, block copolymer) | material class (polymer electrolytes) | polyethers (PEO), polycarbonates, polysiloxanes, PVDF-HFP and PAN gels, single-ion polymers, block copolymers | lithium, sodium | — | 143 | 32 |
| [`hybrid.yaml`](../configs/hybrid.yaml) | Composite and framework electrolytes (polymer-ceramic, MOF, COF, plastic crystals, ionogels) | material class (composites and framework electrolytes) | polymer-ceramic composites, MOF and COF electrolytes, plastic crystals, ionogels | lithium, sodium | — | 142 | 24 |
| [`multivalent.yaml`](../configs/multivalent.yaml) | Multivalent-ion solid electrolytes (Mg2+, Ca2+, Zn2+, Al3+, Sc3+) | grouping by mobile ion (Mg2+, Ca2+, Zn2+, Al3+, Sc3+) | spinel MgSc2Se4, NASICON-type MgZr4(PO4)6, Sc2(WO4)3 type, Mg(BH4)2 | magnesium, calcium, zinc | MgSc2Se4, MgSc2S4, MgZr4(PO4)6, Mg0.5Zr2(PO4)3, Mg0.5Ti2(PO4)3 | 160 | 27 |

Every family's queries add, to its own: each of its main names with every transport measurement and method
(ionic conductivity, activation energy, migration barrier, NMR, AIMD, …), the older names of fast ion conduction
(fast ion conductor, superionic conductor) and the transport mechanisms (concerted migration, vacancy and
interstitial mechanisms, paddle-wheel, percolation, bottleneck size). A formula is found however a title writes
it (spaces, subscripts), and a part of a family's formula finds its doped members.
