# ranking.py

import math
from typing import Any, Dict, List, Set, Tuple

from config import SchemaConfig
from models import ExtractedField, Material, Relation

TOP_K = 5  # return multiple ranked candidates per property, not just one (schema section 15)
# ... and every value of a material: a paper that gives eight activation energies of Li3YCl6 gives
# eight. (Still bounded, so that a table read wrongly cannot flood the database.)
PER_MATERIAL = 25


def _safe_int(value: str, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class Ranker:
    """Multi-factor confidence scoring (schema section 15).

    extractor.py already assigns each candidate a base confidence (section weight, source-type
    weight, positive/negative language cues) at extraction time, since that's naturally a
    per-sentence computation. Ranker layers on the signals that require seeing the *whole*
    document's candidates at once: frequency-across-paper agreement, cross-agreement with the
    Abstract/Conclusion, and whether a value was actually resolved to a specific material via a
    relation (dependency-parse or table-row) rather than left as an orphan candidate.
    """

    @classmethod
    def process(cls, extracted_data: Dict[str, Any]) -> Dict[str, Any]:
        final: Dict[str, Any] = {}

        relations: List[Relation] = extracted_data.get("relations", [])
        # id()-based identity set: extractor.py appends the SAME ExtractedField object both to
        # results[cat][prop] and into its Relation, so this cheaply flags "was this linked".
        linked_field_ids = {id(r.property_value) for r in relations if r.extraction_method in (
            "apposition", "named_with_quantity", "dependency_parse", "table_row", "list_alignment")}

        for cat in SchemaConfig.SCHEMA:
            final[cat] = {}
            for prop in SchemaConfig.SCHEMA[cat]:
                candidates = extracted_data.get(cat, {}).get(prop, [])
                final[cat][prop] = cls._rank_candidates(candidates, linked_field_ids)

        final["materials"] = cls._rank_materials(extracted_data.get("materials", []))
        final["relations"] = cls._rank_relations(relations)
        final["tables"] = extracted_data.get("tables", [])
        final["figures"] = sorted(extracted_data.get("figures", []),
                                   key=lambda f: (_safe_int(f.page), _safe_int(f.figure_number)))
        final["equations"] = sorted(extracted_data.get("equations", []), key=lambda e: _safe_int(e.page))
        final["workflow"] = extracted_data.get("workflow", [])

        return final

    @staticmethod
    def _rank_candidates(candidates: List[ExtractedField], linked_field_ids: Set[int]) -> List[ExtractedField]:
        if not candidates:
            return []

        value_counts: Dict[str, int] = {}
        abstract_conclusion_values: Set[str] = set()
        for c in candidates:
            value_counts[c.normalized_value] = value_counts.get(c.normalized_value, 0) + 1
            if c.source_section in ("Abstract", "Conclusion"):
                abstract_conclusion_values.add(c.normalized_value)

        for c in candidates:
            boost = 0.0
            repeats = value_counts.get(c.normalized_value, 1)
            if repeats > 1:  # duplicate-agreement across the paper
                boost += min(0.15, 0.05 * math.log2(repeats + 1))
            if c.normalized_value in abstract_conclusion_values and c.source_section not in ("Abstract", "Conclusion"):
                boost += 0.1  # agrees with what the Abstract/Conclusion itself states
            if id(c) in linked_field_ids:
                boost += 0.1  # resolved to a specific material, not an orphan candidate
            c.confidence = max(0.01, min(0.99, c.confidence + boost))

        ranked = sorted(candidates, key=lambda x: x.confidence, reverse=True)
        seen: Set[Tuple[str, str, str]] = set()
        unique: List[ExtractedField] = []
        kept_per_group: Dict[Tuple[str, str], int] = {}
        for c in ranked:
            # The same value for another material, or of another transport type, is not a duplicate.
            group = (c.material_id, c.transport_component)
            key = (c.normalized_value, *group)
            if key in seen:
                continue
            # The limit is applied per material and per transport type ("NONE" when a value has
            # neither), so one material's values — or a paper's bulk / grain-boundary / surface /
            # total values — don't crowd the others out. A material's own values are data rather
            # than candidates, so their limit is only a guard against a mis-read table.
            if kept_per_group.get(group, 0) >= (PER_MATERIAL if c.material_id != "NONE" else TOP_K):
                continue
            seen.add(key)
            unique.append(c)
            kept_per_group[group] = kept_per_group.get(group, 0) + 1
        return unique

    @staticmethod
    def _rank_materials(materials: List[Material]) -> List[Material]:
        seen: Set[str] = set()
        unique: List[Material] = []
        for m in sorted(materials, key=lambda x: x.confidence, reverse=True):
            if m.normalized_formula in seen:
                continue
            seen.add(m.normalized_formula)
            unique.append(m)
        return unique

    @staticmethod
    def _rank_relations(relations: List[Relation]) -> List[Relation]:
        """Keeps all distinct relations, capping near-duplicate repeats of the same
        material/property/value triple (redundant identical evidence) at 3."""
        seen_counts: Dict[Tuple[str, str, str, str], int] = {}
        kept: List[Relation] = []
        for r in sorted(relations, key=lambda x: x.confidence, reverse=True):
            key = (r.material_id, r.category, r.property_name, r.property_value.normalized_value)
            seen_counts[key] = seen_counts.get(key, 0) + 1
            if seen_counts[key] > 3:
                continue
            kept.append(r)
        return kept
