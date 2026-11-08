# Evaluation/baselines/chemdataextractor_baseline.py
"""A baseline to compare MoukhlijMatExtract with: ChemDataExtractor 2 (Mavračić et al., J. Chem. Inf. Model.
61, 4280 (2021)), the toolkit most used to build materials databases from papers, given models for the two
quantities of the evaluation it can be taught: activation energies and conductivities (the way the battery
database of Huang & Cole, Sci. Data 7, 260 (2020), taught it its properties).

ChemDataExtractor 2 runs in its own Python environment (it needs older packages than MoukhlijMatExtract):

    python3.11 -m venv cde-venv
    cde-venv/bin/pip install chemdataextractor2==2.4.1
    cde-venv/bin/python Evaluation/baselines/chemdataextractor_baseline.py <pdf folder or files> -o cde.csv
    mme-eval score --predictions cde.csv

It is slow: its BERT model reads each paragraph in about 5 s on a laptop CPU, so a paper takes 10–30 minutes,
and each process needs about 3 GB of memory. Each PDF is read in its own process, `--jobs` at a time (2 by
default: more only with more than 8 GB of memory); one that takes longer than `--timeout` seconds is stopped
and reported, not waited for. A run stopped half-way goes on where it stopped when started again
(`<out>.done` lists the PDFs read; delete it to start over).

It reads each PDF as ChemDataExtractor does (its own PDF reader) and writes one row per value it found, in
the CSV form `mme-eval score --predictions` reads: paper_id (the PDF's file name), property, material,
value, unit. It imports nothing of MoukhlijMatExtract."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from chemdataextractor import Document
from chemdataextractor.model import Compound, ModelType, StringType
from chemdataextractor.model.units.dimension import Dimension
from chemdataextractor.model.units.energy import Energy
from chemdataextractor.model.units.length import Length
from chemdataextractor.model.units.quantity_model import QuantityModel
from chemdataextractor.model.units.unit import Unit
from chemdataextractor.parse.elements import I, R, W

# --- A conductance unit, the siemens (ChemDataExtractor has none), and a conductivity: siemens per length ---


class Conductance(Dimension):
    pass


class ConductanceUnit(Unit):
    def __init__(self, magnitude=0.0, powers=None):
        super().__init__(Conductance(), magnitude, powers)


class Siemens(ConductanceUnit):
    def convert_value_to_standard(self, value):
        return value

    def convert_value_from_standard(self, value):
        return value

    def convert_error_to_standard(self, error):
        return error

    def convert_error_from_standard(self, error):
        return error


Conductance.units_dict = {R("S(iemens)?", group=0): Siemens}
Conductance.standard_units = Siemens()

# --- The models: what is looked for, and how it is named in a paper ---


class ActivationEnergy(QuantityModel):
    dimensions = Energy()
    specifier = StringType(parse_expression=(I("activation") + I("energy")) | (I("migration") + I("barrier"))
                           | (I("energy") + I("barrier")) | R("^E[a]$") | W("Ea"), required=True)
    compound = ModelType(Compound, required=False, contextual=True)


class IonicConductivity(QuantityModel):
    dimensions = Conductance() / Length()
    specifier = StringType(parse_expression=(I("ionic") + I("conductivity")) | (I("ion") + I("conductivity"))
                           | (R("^[Ll]i(\\+)?$") + I("conductivity")) | W("σ") | I("conductivity"), required=True)
    compound = ModelType(Compound, required=False, contextual=True)


class ElectronicConductivity(QuantityModel):
    dimensions = Conductance() / Length()
    specifier = StringType(parse_expression=(I("electronic") + I("conductivity")) | W("σe") | W("σ_e"), required=True)
    compound = ModelType(Compound, required=False, contextual=True)


MODELS = {ActivationEnergy: "activation_energy", IonicConductivity: "ionic_conductivity",
          ElectronicConductivity: "electronic_conductivity"}
COLUMNS = ["paper_id", "property", "material", "value", "unit"]


def values_of(pdf: Path):
    """(property, material, value, unit as written) for every value ChemDataExtractor finds in a PDF."""
    with pdf.open("rb") as f:
        document = Document.from_file(f)
    document.models = list(MODELS)
    for record in document.records:
        prop = MODELS.get(type(record))
        if prop is None or not record.value:
            continue
        names = sorted(record.compound.names) if record.compound is not None and record.compound.names else []
        # a formula when it found one among the names of the compound, else its first name
        material = next((n for n in names if any(c.isdigit() for c in n)), names[0] if names else "")
        value = sum(record.value) / len(record.value)  # a range "0.2–0.3" counts as its middle
        unit = (record.raw_units or "").strip()
        yield prop, material, value, unit


def _one(pdf: Path, timeout: float):
    """The values of one PDF, read in a process of its own: (values, None) or (None, why it failed)."""
    command = [sys.executable, "-I", str(Path(__file__).resolve()), "--one", str(pdf)]
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, f"stopped after {timeout:.0f} s"
    if done.returncode != 0:
        last = (done.stderr.strip().splitlines() or ["no message"])[-1]
        return None, f"could not be read ({last})"
    return json.loads(done.stdout.strip().splitlines()[-1]), None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="ChemDataExtractor 2 baseline: values of PDFs as a predictions CSV.")
    parser.add_argument("pdfs", nargs="+", type=Path, help="PDF files, or folders of them")
    parser.add_argument("--out", "-o", type=Path, help="The predictions CSV to write")
    parser.add_argument("--jobs", "-j", type=int, default=2, help="PDFs read at the same time, about 3 GB of memory each (default 2)")
    parser.add_argument("--timeout", type=float, default=3600, help="Seconds allowed per PDF (default 3600)")
    parser.add_argument("--one", action="store_true", help=argparse.SUPPRESS)  # internal: one PDF, JSON to stdout
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.ERROR)
    if args.one:
        print(json.dumps(list(values_of(args.pdfs[0]))))
        return 0
    if args.out is None:
        parser.error("--out is required")
    files = sorted({p for given in args.pdfs for p in ([given] if given.is_file() else given.glob("*.pdf"))})
    # A run stopped half-way goes on where it stopped: the PDFs listed in <out>.done are not read again.
    done_list = args.out.with_name(args.out.name + ".done")
    done = set(done_list.read_text(encoding="utf-8").split("\n")) - {""} if done_list.exists() and args.out.exists() else set()
    kept = []
    if done:
        with args.out.open(newline="", encoding="utf-8") as f:
            kept = [row for row in csv.reader(f)][1:]
        print(f"{len(done)} PDF(s) read before — kept", flush=True)
    else:
        done_list.write_text("", encoding="utf-8")
    todo = [pdf for pdf in files if pdf.name not in done]
    rows, failed = len(kept), 0
    with args.out.open("w", newline="", encoding="utf-8") as f, done_list.open("a", encoding="utf-8") as marks, \
            ThreadPoolExecutor(max(1, args.jobs)) as pool:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        writer.writerows(kept)
        for number, (pdf, (found, why)) in enumerate(zip(todo, pool.map(lambda p: _one(p, args.timeout), todo)),
                                                     len(done) + 1):
            if found is None:
                failed += 1
                print(f"[{number}/{len(files)}] {pdf.name}: {why}", flush=True)
                continue
            for prop, material, value, unit in found:
                writer.writerow([pdf.name, prop, material, value, unit])
            f.flush()
            marks.write(pdf.name + "\n")
            marks.flush()
            rows += len(found)
            print(f"[{number}/{len(files)}] {pdf.name}: {len(found)} value(s)", flush=True)
    print(f"Wrote {args.out}: {rows} values from {len(files) - failed} of {len(files)} PDFs"
          + (f" ({failed} not read)." if failed else "."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
