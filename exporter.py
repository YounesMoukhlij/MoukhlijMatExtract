# exporter.py

import json
import logging
import os
import re
from dataclasses import asdict
from datetime import datetime
from typing import Any, Dict, List

import pandas as pd

from models import ExtractedField, Material, PaperData

# Characters XML (and therefore .xlsx) cannot store.
_ILLEGAL_XML_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# Paper-level (not tied to a single material) categorized property dicts on PaperData.
CATEGORY_FIELDS = [
    "electrochemical", "thermodynamic", "mechanical", "structural", "electronic", "thermal",
    "spectroscopy", "dft", "aimd", "ml", "synthesis", "characterization", "battery_perf", "interfaces",
]


# The tables of the relational schema, as CSV files and as sheets of the workbook.
TABLE_NAMES = ["papers", "materials", "properties", "activation_energy", "unassigned_values", "methods",
               "relations", "tables", "figures", "equations", "workflow"]
# A column every table of this version has and no earlier one had: tells an old database apart.
_VERSION_MARK = ("properties.csv", "basis")
_BASIS_ORDER = ("structure", "temperature", "pressure", "origin", "component")
NOT_APPLICABLE = "n/a"


class StrictExporter:
    """Builds the normalized relational schema (schema section 16: papers/materials/properties/
    relations/tables/figures/equations/workflow) and writes it as linked CSV files, a multi-sheet
    Excel workbook, and nested JSON — plus the original flat one-row-per-paper summary CSV kept
    for backward-compatible quick scanning (schema rule: don't remove working functionality).

    Every table only has columns that apply to each of its rows, so that an empty cell ("NONE")
    always means "looked for and not found":
      properties         the values of materials (a number, for a material, with its context)
      activation_energy  the activation energies among them, one column in eV whatever the paper called it
      unassigned_values  the values no material could be established for
      methods            how the study was done and what it mentions: DFT/AIMD/ML settings, synthesis, techniques
    """

    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    @classmethod
    def is_outdated(cls, output_dir: str) -> bool:
        """Whether the folder holds a database written by an earlier version, with other columns.
        New papers cannot be merged into it: it has to be rebuilt from the PDFs."""
        name, column = _VERSION_MARK
        path = os.path.join(output_dir, name)
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            # An older database may hold no property at all; its papers table gives it away.
            return os.path.exists(os.path.join(output_dir, "papers.csv")) and not os.path.exists(
                os.path.join(output_dir, "methods.csv"))
        try:
            return column not in pd.read_csv(path, nrows=0).columns
        except Exception:
            return False

    @staticmethod
    def archive(output_dir: str) -> str:
        """Moves the database files of a folder into a dated sub-folder of it, so that the database
        can be rebuilt from the PDFs without anything being deleted. Returns that sub-folder ("" if
        there was nothing to move)."""
        files = [name for name in (os.listdir(output_dir) if os.path.isdir(output_dir) else [])
                 if name.endswith(".csv") or name in ("database.json", "database.xlsx")]
        if not files:
            return ""
        kept = os.path.join(output_dir, "previous_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
        os.makedirs(kept)
        for name in files:
            os.replace(os.path.join(output_dir, name), os.path.join(kept, name))
        return kept

    # ------------------------------------------------------------------
    # Normalized table builders
    # ------------------------------------------------------------------
    # Every per-value table (properties, activation_energy, relations) describes a value the same
    # way, through these three column groups: what it was obtained for, under which conditions,
    # and where in the paper it sits.
    @staticmethod
    def _composition(elements: Dict[str, Any]) -> str:
        """Element -> amount as JSON with the elements in alphabetical order, so that one
        composition is one text however the paper ordered its formula."""
        return json.dumps({symbol: elements[symbol] for symbol in sorted(elements)}, ensure_ascii=False) \
            if elements else "NONE"

    @classmethod
    def _material_columns(cls, f: ExtractedField, materials: Dict[str, Material]) -> Dict[str, Any]:
        """The material the value was obtained for. `structure` is the value's own — the form of
        the material it is quoted for."""
        m = materials.get(f.material_id)
        return {
            "material_id": f.material_id, "material_formula": f.material_formula,
            "composition": cls._composition(m.elements) if m else "NONE",
            "structure": f.structure,
            "ionic_radii": json.dumps(m.ionic_radii, ensure_ascii=False) if m and m.ionic_radii else "NONE",
        }

    @staticmethod
    def basis_text(f: ExtractedField) -> str:
        """Where each part of a value's context comes from, as one line:
        "structure: stated | temperature: paper (...) | pressure: assumed (...) | origin: ..."."""
        return " | ".join(f"{name}: {f.basis[name]}" for name in _BASIS_ORDER if name in f.basis) or "NONE"

    @classmethod
    def _condition_columns(cls, f: ExtractedField) -> Dict[str, Any]:
        return {
            "temperature": f.temperature, "pressure": f.pressure, "data_origin": f.data_origin,
            # Only the ion-transport properties split into bulk / grain boundary / surface / total.
            "transport_component": f.transport_component if f.transport_component != "NONE" else NOT_APPLICABLE,
            "attribution": f.attribution, "basis": cls.basis_text(f),
        }

    @staticmethod
    def source_text(f: ExtractedField) -> str:
        """Where in the paper the value sits, in words: "Text", "Text, citing Figure 4b", "Figure 3
        caption", "Table 2, row: LLZO | column: Ea (eV)"."""
        if f.source_type == "Table":
            where = f.source_label if f.source_label != "NONE" else "Table"
            where += f", {f.source_detail}" if f.source_detail != "NONE" else ""
        elif f.source_label != "NONE":
            where = f"{f.source_label} caption"
        else:
            where = f.source_type
        return where + (f", citing {f.cited_refs}" if f.cited_refs != "NONE" else "")

    @classmethod
    def _source_columns(cls, f: ExtractedField) -> Dict[str, Any]:
        return {"source_type": f.source_type, "source": cls.source_text(f), "page": f.source_page,
                "section": f.source_section}

    @classmethod
    def _build_rows(cls, papers: List[PaperData]) -> Dict[str, List[Dict[str, Any]]]:
        tables: Dict[str, List[Dict[str, Any]]] = {name: [] for name in TABLE_NAMES}

        for paper in papers:
            pid = paper.filename
            materials = {m.material_id: m for m in paper.materials}
            meta = paper.metadata

            def meta_val(key: str) -> str:
                return meta.get(key, ExtractedField.empty()).normalized_value

            provenance = paper.provenance
            tables["papers"].append({
                "paper_id": pid, "filename": paper.filename,
                "title": meta_val("title"), "authors": meta_val("authors"), "journal": meta_val("journal"),
                "doi": meta_val("doi"), "publication_year": meta_val("publication_year"),
                "n_materials": len(paper.materials), "n_relations": len(paper.relations),
                "n_references": len(paper.references),
                "origin": paper.origin,
                **{key: provenance.get(key, "NONE") for key in (
                    "source_service", "source_url", "license", "retrieved_at", "file_sha256", "openalex_id")},
            })

            for m in paper.materials:
                tables["materials"].append({
                    "paper_id": pid, "material_id": m.material_id, "raw_formula": m.raw_formula,
                    "normalized_formula": m.normalized_formula,
                    "elements": cls._composition(m.elements),
                    "structure": m.structure, "structure_basis": m.structure_basis,
                    "ionic_radii": json.dumps(m.ionic_radii, ensure_ascii=False) if m.ionic_radii else "NONE",
                    "is_known_alias": m.is_known_alias, "confidence": round(m.confidence, 3),
                    "page": m.source_page, "section": m.source_section, "source_type": m.source_type,
                })

            for cat_field in CATEGORY_FIELDS:
                for prop, cands in (getattr(paper, cat_field, {}) or {}).items():
                    for c in cands:
                        value = {"raw_value": c.raw_value, "normalized_value": c.normalized_value, "unit": c.unit}
                        where = {"confidence": round(c.confidence, 3), **cls._source_columns(c), "sentence": c.source_sentence}
                        named = {"paper_id": pid, "category": cat_field.upper(), "property_name": prop}
                        if not c.basis:  # a setting of the study or a bare mention: it has no context
                            tables["methods"].append({**named, **value, **where})
                        elif c.material_id == "NONE":
                            tables["unassigned_values"].append({**named, **value, **cls._condition_columns(c), **where})
                        else:
                            tables["properties"].append({
                                "paper_id": pid, **cls._material_columns(c, materials),
                                "material_link": c.material_link, "category": cat_field.upper(), "property_name": prop,
                                **value, **cls._condition_columns(c), **where,
                            })

            # Dedicated activation-energy table. Papers describe the same physical quantity (the
            # energy barrier of an ion hop) under many names — "activation energy", "Ea",
            # "migration barrier", "hopping barrier", "energy barrier" — which are one property
            # here (config.EA_TERM); "reported_as" keeps the paper's own word. One numeric column
            # in eV, so the table sorts and plots as it is. An activation energy is a property of a
            # material, so only values tied to one are listed.
            for c in paper.electrochemical.get("Activation_Energy", []):
                if c.material_id == "NONE":
                    continue
                columns = cls._material_columns(c, materials)
                tables["activation_energy"].append({
                    "paper_id": pid, "material_formula": columns["material_formula"],
                    "activation_energy_eV": float(c.normalized_value.split(" ", 1)[0]),
                    "reported_as": c.reported_as,
                    "composition": columns["composition"], "structure": columns["structure"],
                    "ionic_radii": columns["ionic_radii"],
                    **cls._condition_columns(c), "confidence": round(c.confidence, 3),
                    **cls._source_columns(c), "sentence": c.source_sentence,
                    "raw_value": c.raw_value, "material_id": c.material_id, "material_link": c.material_link,
                })

            for r in paper.relations:
                context = cls._condition_columns(r.property_value) if r.property_value.basis else {}
                tables["relations"].append({
                    "paper_id": pid, **cls._material_columns(r.property_value, materials),
                    "category": r.category, "property_name": r.property_name,
                    "value": r.property_value.normalized_value, "unit": r.property_value.unit,
                    **{name: context.get(name, NOT_APPLICABLE) for name in (
                        "temperature", "pressure", "data_origin", "transport_component")},
                    "confidence": round(r.confidence, 3), "extraction_method": r.extraction_method,
                    **cls._source_columns(r.property_value), "sentence": r.source_sentence,
                })

            for t in paper.tables:
                tables["tables"].append({
                    "paper_id": pid, "table_number": t.table_number, "caption": t.caption,
                    "page": t.page, "section": t.section,
                    "headers": json.dumps(t.headers, ensure_ascii=False),
                    "rows": json.dumps(t.rows, ensure_ascii=False),
                    "material_column": t.material_column,
                })

            for f in paper.figures:
                tables["figures"].append({
                    "paper_id": pid, "figure_number": f.figure_number, "caption": f.caption,
                    "page": f.page, "section": f.section,
                    "referenced_materials": " | ".join(f.referenced_materials) or "NONE",
                    "referenced_properties": " | ".join(f.referenced_properties) or "NONE",
                    "referenced_tables": " | ".join(f.referenced_tables) or "NONE",
                    "referenced_equations": " | ".join(f.referenced_equations) or "NONE",
                    "mentioned_methods": " | ".join(f.mentioned_methods) or "NONE",
                })

            for e in paper.equations:
                tables["equations"].append({
                    "paper_id": pid, "equation_type": e.equation_type, "equation_text": e.equation_text,
                    "page": e.page, "section": e.section,
                    "variables": " | ".join(e.variables) or "NONE", "context_sentence": e.context_sentence,
                })

            for w in paper.workflow:
                tables["workflow"].append({
                    "paper_id": pid, "step_order": w.order, "stage": w.stage,
                    "evidence_sentence": w.evidence_sentence, "page": w.page, "section": w.section,
                })

        return tables

    # ------------------------------------------------------------------
    # Legacy flat one-row-per-paper summary (kept so nothing existing is removed)
    # ------------------------------------------------------------------
    @staticmethod
    def to_flat_dict(paper: PaperData) -> Dict[str, Any]:
        row: Dict[str, Any] = {"Filename": paper.filename}

        for k, v in paper.metadata.items():
            row.update(v.to_flat_dict(f"Meta_{k}"))

        for cat_field in CATEGORY_FIELDS:
            prefix = cat_field[:5].capitalize()
            for prop_name, cands in (getattr(paper, cat_field, {}) or {}).items():
                best = cands[0] if cands else ExtractedField.empty()
                row.update(best.to_flat_dict(f"{prefix}_{prop_name}"))
                for i in range(1, 3):
                    cand = cands[i] if len(cands) > i else ExtractedField.empty()
                    row[f"{prefix}_{prop_name}_Cand{i + 1}"] = cand.normalized_value

        top_mats = [m.normalized_formula for m in paper.materials[:5]]
        row["Top_Materials"] = " | ".join(top_mats) if top_mats else "NONE"

        rels = [f"{r.material_formula}[{r.property_name}={r.property_value.normalized_value}]"
                for r in paper.relations[:5]]
        row["Top_Relations"] = " | ".join(rels) if rels else "NONE"

        return row

    # ------------------------------------------------------------------
    # Export: CSV (one file per table), Excel (one sheet per table), JSON (nested per paper)
    # ------------------------------------------------------------------
    def export(self, new_dataset: List[PaperData], excel: bool = True) -> None:
        """Merges `new_dataset` into the database files. A long run calls this after every batch of
        papers with `excel=False` and builds the workbook once at the end (`export_excel`): merging
        each batch into the workbook would re-read all of it every time, and by 800 papers that
        alone takes half a minute per batch."""
        if not new_dataset:
            return

        tables = self._build_rows(new_dataset)
        self._export_csv(tables)
        self._export_json(new_dataset)
        self._export_legacy_summary(new_dataset)
        if excel:
            self.export_excel()

    def _export_csv(self, tables: Dict[str, List[Dict[str, Any]]]) -> None:
        for name, rows in tables.items():
            path = os.path.join(self.output_dir, f"{name}.csv")
            new_df = self._strict_none(pd.DataFrame(rows))
            final_df = self._merge_csv(path, new_df)
            final_df.to_csv(path, index=False, encoding="utf-8-sig")

    def export_excel(self) -> None:
        """Builds the workbook from the CSV files, which hold the merged database."""
        path = os.path.join(self.output_dir, "database.xlsx")
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            for name in TABLE_NAMES:
                try:
                    # As written: pandas would read the text "n/a" (not applicable) as an empty cell.
                    table = pd.read_csv(os.path.join(self.output_dir, f"{name}.csv"), keep_default_na=False)
                except (FileNotFoundError, pd.errors.EmptyDataError):
                    continue
                self._strict_none(table).to_excel(writer, sheet_name=name[:31], index=False)

    def _export_json(self, new_dataset: List[PaperData]) -> None:
        path = os.path.join(self.output_dir, "database.json")
        existing_papers: List[Dict[str, Any]] = []
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                    existing_papers = existing.get("papers", []) if isinstance(existing, dict) else existing
            except Exception as e:
                logging.warning(f"Could not read existing JSON database, overwriting: {e}")

        existing_filenames = {p.get("filename") for p in existing_papers}
        new_papers = [self._paper_to_nested_dict(p) for p in new_dataset if p.filename not in existing_filenames]

        with open(path, "w", encoding="utf-8") as f:
            json.dump({"papers": existing_papers + new_papers}, f, indent=2, ensure_ascii=False)

    def _export_legacy_summary(self, new_dataset: List[PaperData]) -> None:
        path = os.path.join(self.output_dir, "database_summary.csv")
        new_df = self._strict_none(pd.DataFrame([self.to_flat_dict(p) for p in new_dataset]))
        final_df = self._merge_csv(path, new_df)
        final_df.to_csv(path, index=False, encoding="utf-8-sig")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _merge_csv(path: str, new_df: pd.DataFrame) -> pd.DataFrame:
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return new_df
        try:
            old_df = pd.read_csv(path, keep_default_na=False)  # "n/a" stays "n/a", see export_excel
            return StrictExporter._strict_none(pd.concat([old_df, new_df], ignore_index=True))
        except pd.errors.EmptyDataError:
            return new_df
        except Exception as e:
            logging.warning(f"Could not merge with existing {path}: {e}")
            return new_df

    @staticmethod
    def _strict_none(df: pd.DataFrame) -> pd.DataFrame:
        """Enforces the strict-NONE policy (schema section 17): never NaN/null/empty string."""
        if df.empty:
            return df
        df = df.fillna("NONE").replace("", "NONE")
        # Control characters left over from PDF extraction make openpyxl raise IllegalCharacterError
        # and abort the whole workbook export, so they are stripped from every text cell.
        return df.apply(lambda col: col.map(
            lambda v: _ILLEGAL_XML_CHARS.sub("", v) if isinstance(v, str) else v))

    @classmethod
    def _paper_to_nested_dict(cls, paper: PaperData) -> Dict[str, Any]:
        def field_dict(f: ExtractedField) -> Dict[str, Any]:
            # Source, material and measurement context; like the transport keys, each is only
            # written when it was established.
            context = {
                "source_label": f.source_label, "source_detail": f.source_detail, "cited_refs": f.cited_refs,
                "material_id": f.material_id, "material_formula": f.material_formula,
                "material_link": f.material_link, "structure": f.structure,
                "temperature": f.temperature, "pressure": f.pressure,
                "data_origin": f.data_origin, "data_origin_evidence": f.data_origin_evidence,
                "reported_as": f.reported_as, "attribution": f.attribution,
            }
            return {
                "raw_value": f.raw_value, "normalized_value": f.normalized_value, "unit": f.unit,
                "confidence": round(f.confidence, 3), "page": f.source_page, "section": f.source_section,
                "sentence": f.source_sentence, "source_type": f.source_type,
                **{key: value for key, value in context.items() if value != "NONE"},
                **({"basis": f.basis} if f.basis else {}),
                **({"transport_component": f.transport_component,
                    "transport_component_evidence": f.transport_component_evidence,
                    "dominant_component": f.dominant_component}
                   if f.transport_component != "NONE" else {}),
            }

        return {
            "filename": paper.filename,
            "origin": paper.origin, "provenance": paper.provenance,
            "metadata": {k: field_dict(v) for k, v in paper.metadata.items()},
            "materials": [
                {
                    "material_id": m.material_id, "raw_formula": m.raw_formula,
                    "normalized_formula": m.normalized_formula, "elements": m.elements,
                    "structure": m.structure, "structure_basis": m.structure_basis, "ionic_radii": m.ionic_radii,
                    "is_known_alias": m.is_known_alias, "confidence": round(m.confidence, 3),
                    "page": m.source_page, "section": m.source_section,
                    "properties": [field_dict(p) for p in m.properties],
                }
                for m in paper.materials
            ],
            "paper_level_properties": {
                cat_field.upper(): {prop: [field_dict(c) for c in cands] for prop, cands in
                                     (getattr(paper, cat_field, {}) or {}).items() if cands}
                for cat_field in CATEGORY_FIELDS
            },
            "relations": [
                {
                    "material_id": r.material_id, "material_formula": r.material_formula,
                    "category": r.category, "property_name": r.property_name,
                    "value": r.property_value.normalized_value, "unit": r.property_value.unit,
                    "structure": r.property_value.structure, "temperature": r.property_value.temperature,
                    "pressure": r.property_value.pressure, "data_origin": r.property_value.data_origin,
                    "transport_component": r.property_value.transport_component,
                    "confidence": round(r.confidence, 3), "extraction_method": r.extraction_method,
                    "source_type": r.property_value.source_type, "source_label": r.property_value.source_label,
                    "sentence": r.source_sentence, "page": r.source_page,
                }
                for r in paper.relations
            ],
            "tables": [asdict(t) for t in paper.tables],
            "figures": [asdict(f) for f in paper.figures],
            "equations": [asdict(e) for e in paper.equations],
            "workflow": [asdict(w) for w in paper.workflow],
            "references": paper.references,
        }
