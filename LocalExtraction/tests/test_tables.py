# LocalExtraction/tests/test_tables.py
"""Tables printed without ruling lines (LocalExtraction/tables.py), and how their columns are read."""

import unittest

from LocalExtraction.chemistry import ChemistryEngine
from LocalExtraction.extractor import ExtractorEngine
from LocalExtraction.parser import _MATERIAL_HEADER
from LocalExtraction.tables import caption_tables


class _Page:
    """A pdfplumber page as caption_tables reads it: its width and its words."""

    def __init__(self, lines, width=600.0):
        self.width, self._words = width, []
        for top, cells in lines:  # (top, [(x0, text), …]): one line of words
            for x0, text in cells:
                self._words.append({"x0": x0, "x1": x0 + 5.5 * len(text), "top": top, "bottom": top + 9, "text": text})

    def extract_words(self, **_):
        return list(self._words)


def _table(lines, width=600.0):
    found = caption_tables(_Page(lines, width))
    return found[0] if found else None


def _prose(text, x=50.0):
    """A line of running text: its words one space (3 points) apart."""
    cells = []
    for word in text.split():
        cells.append((x, word))
        x += 5.5 * len(word) + 3
    return cells


# One column of running text, a caption, a two-line header, three rows, then running text again.
PAGE = [
    (40, _prose("The conductivity was measured by impedance spectroscopy between 25 and 100 °C.")),
    (60, _prose("Table 2. Ionic conductivity of the samples.")),
    (80, [(50, "Sample"), (200, "σ"), (330, "Ea")]),
    (92, [(200, "(S"), (213, "cm−1)"), (330, "(eV)")]),
    (110, [(50, "Li6PS5Cl"), (200, "1.2"), (219, "×"), (227, "10−3"), (330, "0.31")]),
    (124, [(50, "Li6PS5Br"), (200, "8.0"), (219, "×"), (227, "10−4"), (330, "0.35")]),
    (138, [(50, "Li6PS5I"), (200, "2.1"), (219, "×"), (227, "10−6"), (330, "0.45")]),
    (170, _prose("These values agree well with those reported before for argyrodite electrolytes.")),
]


class UnruledTableTests(unittest.TestCase):
    def test_a_table_under_its_caption(self):
        number, rows = _table(PAGE)
        self.assertEqual(number, "2")
        self.assertEqual(rows[0], ["Sample", "σ (S cm−1)", "Ea (eV)"])  # the two header lines, one cell per column
        self.assertEqual(rows[1:], [["Li6PS5Cl", "1.2 × 10−3", "0.31"], ["Li6PS5Br", "8.0 × 10−4", "0.35"],
                                    ["Li6PS5I", "2.1 × 10−6", "0.45"]])  # the running text after it is left out

    def test_no_caption_no_table(self):
        self.assertIsNone(_table([line for line in PAGE if line[0] != 60]))

    def test_a_ruled_table_already_read_is_not_read_again(self):
        self.assertEqual(caption_tables(_Page(PAGE), skip=[(40, 75, 500, 150)]), [])


class HeaderTests(unittest.TestCase):
    def test_the_unit_in_square_brackets_or_after_a_slash(self):
        for header, cell, value in (("σ Li+ [S cm−1]", "4.03 × 10−9", "4.03e-09 S/cm"), ("E a [eV]", "0.70", "0.7 eV"),
                                    ("σ / S cm−1", "1.2 × 10−3", "0.0012 S/cm"), ("Ea / eV", "0.31", "0.31 eV"),
                                    ("Ea (GB) (eV)", "0.4", "0.4 eV")):
            cat, prop = ExtractorEngine._match_header_property(header)
            field = ExtractorEngine._extract_cell_value(cell, header, cat, prop, "1", "Results", {"caption": "x"})
            self.assertEqual(field.normalized_value, value, header)

    def test_a_subscript_put_after_the_unit(self):
        self.assertEqual(ExtractorEngine._match_header_property("E (eV) a"), ("ELECTROCHEMICAL", "Activation_Energy"))

    def test_the_column_of_the_materials(self):
        for header in ("Samples", "Sample name", "Nominal composition", "Chemical formula", "Electrolytes", "Compound"):
            self.assertTrue(_MATERIAL_HEADER.match(header), header)
        for header in ("x (pfu)", "Ea (eV)", "Synthesis", "Systematic error"):
            self.assertFalse(_MATERIAL_HEADER.match(header), header)


class HydrideTests(unittest.TestCase):
    def test_the_count_of_a_last_hydrogen_is_kept(self):
        # hydrogen is −1 in BH4 and +1 in NH2: no simple rule balances Li3(BH4)(NH2)2, and its 8 is no citation
        self.assertEqual([m["formula"] for m in ChemistryEngine.find_materials("Li3BN2H8 and Li4BN3H10")],
                         ["Li3BH8N2", "Li4BH10N3"])


if __name__ == "__main__":
    unittest.main()


def _materials_of(sentence):
    found = ExtractorEngine.extract_all([{"text": sentence, "type": "Text", "page": 1, "section": "Results"}])
    return [(f.material_formula, f.normalized_value) for prop in ("Ionic_Conductivity", "Activation_Energy",
            "Electronic_Conductivity", "Diffusion_Coefficient") for f in found["ELECTROCHEMICAL"][prop]]


class RoleTests(unittest.TestCase):
    """A material named in a role that is never the measured sample takes no value."""

    def test_the_electrode_of_a_battery(self):
        self.assertEqual(_materials_of("The F-GPE shows an ionic conductivity of 2.24 × 10−4 S cm−1, and the NCA//Li "
                                       "battery keeps 178 mAh g−1."), [("NONE", "0.000224 S/cm")])
        self.assertEqual(_materials_of("The PEO/LiTFSI electrolyte reached 2.7 mS cm−1 at 60 °C in a LiFePO4 full cell."),
                         [("NONE", "0.0027 S/cm")])

    def test_a_reagent_and_a_group_of_a_name(self):
        self.assertEqual(_materials_of("This work with NaH2PO4 as a new phosphate source reached an ionic conductivity "
                                       "of 1.98 × 10−4 S cm−1."), [("NONE", "0.000198 S/cm")])
        self.assertEqual(_materials_of("A PIL matrix with TpPa-SO3Li COF as fillers reached a conductivity of "
                                       "1.32 × 10−3 S cm−1."), [("NONE", "0.00132 S/cm")])

    def test_what_stays_the_materials_own(self):
        self.assertEqual(_materials_of("Li6PS5Cl reached 1.1 × 10−3 S cm−1, and the Li6PS5Cl/LiCoO2 cell delivered "
                                       "120 mAh g−1."), [("Li6PS5Cl", "0.0011 S/cm")])
        self.assertEqual(_materials_of("Cathode materials such as LiCoO2 with high electronic conductivity (10−3 S cm−1) "
                                       "need no carbon."), [("LiCoO2", "0.001 S/cm")])


def _table_block(caption, headers, rows):
    return {"type": "Table", "page": 2, "section": "Results", "table_number": "2", "caption": caption,
            "headers": headers, "material_column": "Samples" if "Samples" in headers else "NONE", "rows": rows,
            "text": " ".join(headers) + " " + " ".join(" ".join(r.values()) for r in rows)}


class TableRowMaterialTests(unittest.TestCase):
    def test_rows_of_a_series_whose_formula_is_unknown_are_not_given_one(self):
        block = _table_block("Table 2. Conductivities of LATP-xSn (x = 0–0.4).", ["x", "σt (mS/cm)"],
                             [{"x": "0", "σt (mS/cm)": "0.0505"}, {"x": "0.1", "σt (mS/cm)": "0.0633"}])
        found = ExtractorEngine.extract_all([block])
        self.assertEqual({f.material_formula for f in found["ELECTROCHEMICAL"]["Ionic_Conductivity"]}, {"NONE"})

    def test_the_rows_of_a_table_of_fillers(self):
        block = _table_block("Table 4. Influence of inorganic fillers on ionic conductivity.", ["Samples", "σ (S cm−1)"],
                             [{"Samples": "Al2O3", "σ (S cm−1)": "1.25 × 10−4"}, {"Samples": "SiO2", "σ (S cm−1)": "4.4 × 10−5"}])
        found = ExtractorEngine.extract_all([block])
        self.assertEqual({f.material_formula for f in found["ELECTROCHEMICAL"]["Ionic_Conductivity"]}, {"NONE"})

    def test_a_formula_a_cell_spaces_out(self):
        block = _table_block("Table 1. Perovskites.", ["Samples", "σ total (mS/cm)"],
                             [{"Samples": "(Li 0.375 Sr 0.4375 )(Ta0.75Zr0.25 )O 3-δ", "σ total (mS/cm)": "0.094"},
                              {"Samples": "(Li0.34La0.51 )TiO 3-δ", "σ total (mS/cm)": "0.02"}])
        found = ExtractorEngine.extract_all([block])
        self.assertEqual(sorted(f.material_formula for f in found["ELECTROCHEMICAL"]["Ionic_Conductivity"]),
                         ["Li0.34La0.51TiO3-δ", "Sr0.4375Li0.375Zr0.25Ta0.75O3-δ"])
