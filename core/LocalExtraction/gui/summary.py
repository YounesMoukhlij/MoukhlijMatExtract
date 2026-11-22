# LocalExtraction/gui/summary.py
"""What the window says about a paper once it has been read: a few readable lines, not a table."""

from typing import List

from ..models import ExtractedField, PaperData

# (category attribute on PaperData, property name) highlighted for every processed paper —
# activation energy plus the other properties most commonly asked about across categories.
_HIGHLIGHT_PROPERTIES = [
    ("electrochemical", "Activation_Energy"),
    ("electrochemical", "Ionic_Conductivity"),
    ("electrochemical", "Diffusion_Coefficient"),
    ("electrochemical", "Capacity"),
    ("electrochemical", "Voltage"),
    ("electronic", "Band_Gap"),
    ("thermodynamic", "Formation_Energy"),
    ("mechanical", "Bulk_Modulus"),
    ("structural", "Density"),
]


def describe_context(field: ExtractedField) -> str:
    """What a value was obtained for, under which conditions, and where in the paper it sits:
    "Li6PS5Cl, cubic | argyrodite, 298.1 K, experimental — Table 2, p.5"."""
    known = [v for v in (field.material_formula, field.structure, field.temperature, field.pressure)
             if v != "NONE"]
    if field.data_origin not in ("NONE", "unspecified"):
        known.append(field.data_origin)
    where = field.source_label if field.source_label != "NONE" else field.source_type
    return f"{', '.join(known)} — {where}, p.{field.source_page}" if known else f"{where}, p.{field.source_page}"


def summarize_paper(paper: PaperData) -> str:
    """One readable block per processed paper: materials found plus every headline property
    that was actually extracted (activation energy, conductivity, band gap, ...)."""
    lines: List[str] = []

    title = paper.metadata.get("title")
    if title and not title.is_empty():
        lines.append(f"    Title: {title.normalized_value}")

    top_materials = [m.normalized_formula for m in paper.materials[:5]]
    lines.append(f"    Materials ({len(paper.materials)}): "
                 f"{', '.join(top_materials) if top_materials else 'none found'}")

    found_any_property = False
    for cat_field, prop in _HIGHLIGHT_PROPERTIES:
        candidates = (getattr(paper, cat_field, {}) or {}).get(prop, [])
        if candidates:
            found_any_property = True
            best = next((c for c in candidates if c.material_formula != "NONE"), candidates[0])
            component = f" [{best.transport_component}]" if best.transport_component not in ("NONE", "unspecified") else ""
            more = f" (+{len(candidates) - 1} more)" if len(candidates) > 1 else ""
            lines.append(f"    {prop}: {best.normalized_value}{component}{more} (confidence {best.confidence:.2f})")
            lines.append(f"        {describe_context(best)}")
    if not found_any_property:
        lines.append("    No headline properties (activation energy, conductivity, ...) matched.")

    lines.append(f"    Relations: {len(paper.relations)} | Tables: {len(paper.tables)} | "
                 f"Figures: {len(paper.figures)} | Equations: {len(paper.equations)}")
    return "\n".join(lines)


def final_summary(papers: List[PaperData]) -> str:
    if not papers:
        return "No papers were successfully processed."

    total_materials = sum(len(p.materials) for p in papers)
    total_relations = sum(len(p.relations) for p in papers)
    with_activation_energy = sum(1 for p in papers if p.electrochemical.get("Activation_Energy"))
    values = sum(len(p.electrochemical.get("Activation_Energy") or []) for p in papers)

    lines = [
        "",
        "==================== Summary ====================",
        f"Papers processed:              {len(papers)}",
        f"Materials found (total):       {total_materials}",
        f"Property relations found:      {total_relations}",
        f"Papers with Activation Energy: {with_activation_energy} ({values} values)",
        "===================================================",
    ]
    return "\n".join(lines)
