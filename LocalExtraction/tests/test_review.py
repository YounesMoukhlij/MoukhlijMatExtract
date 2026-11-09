# LocalExtraction/tests/test_review.py
"""The needs_check column: which values a person should look at, and why (LocalExtraction/review.py)."""

import unittest

from LocalExtraction.review import needs_check


class NeedsCheckTests(unittest.TestCase):
    def test_a_clear_value(self):
        self.assertEqual(needs_check("in range", 0.85, "apposition",
                                     "Li6PS5Cl shows an ionic conductivity of 1.1 × 10−3 S cm−1.", "Li6PS5Cl"), "no")

    def test_each_reason(self):
        cases = {
            "out of range": ("check: 12.58 S/cm is outside the 1e-12–0.1 S/cm known", 0.8, "proximity", "s", "Li6PS5Cl"),
            "unusual formula": ("in range", 0.8, "proximity", "s", "LiSO3"),
            "doped sample": ("in range", 0.8, "proximity", "The Ta-doped LLZO reaches 7.98 × 10−4 S cm−1.", "Li7La3Zr2O12"),
            "material from another sentence": ("in range", 0.8, "previous_sentence", "s", "Li6PS5Cl"),
            "table text": ("in range", 0.8, "proximity", "LiFePO4 2.7 (30) 0.1 (40) 1.2 3.4 5.6 7.8 9.0 1.1", "Li6PS5Cl"),
            "low confidence": ("in range", 0.3, "proximity", "s", "Li6PS5Cl"),
        }
        for reason, args in cases.items():
            self.assertEqual(needs_check(*args), f"yes: {reason}", reason)

    def test_several_reasons_and_what_is_not_one(self):
        self.assertEqual(needs_check("check: …", 0.2, "paragraph_topic", "s", "Li6PS5Cl"),
                         "yes: out of range; material from another sentence; low confidence")
        # a series, a formula's subscripts, a sentence naming the material plainly: no reason
        self.assertEqual(needs_check("in range", 0.8, "proximity", "s", "Li7-xLa3Zr2-xTaxO12"), "no")
        self.assertEqual(needs_check("in range", 0.8, "proximity", "Li10GeP2S12 and Li6PS5Cl: 12 and 3 mS/cm.", "Li10GeP2S12"), "no")


if __name__ == "__main__":
    unittest.main()
