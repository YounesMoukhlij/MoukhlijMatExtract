# MLDataset/cli.py
"""mme-ml-export: a dataset for machine learning from the databases of MoukhlijMatExtract, into
~/MoukhlijMatExtract/Ready for ML/<name>/. `mme-ml-export gui` (or `python -m MLDataset gui`) opens the window."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence

from . import export
from .export import ANY, ATTRIBUTIONS, COMPONENTS, ORIGINS, PROPERTIES, Settings

TARGET_WORDS = {"ea": "Ea", "activation_energy": "Ea", "sigma": "sigma", "ionic_conductivity": "sigma", "conductivity": "sigma",
                "sigma_e": "sigma_e", "electronic_conductivity": "sigma_e", "d": "D", "diffusion": "D",
                "diffusion_coefficient": "D"}


def build_parser() -> argparse.ArgumentParser:
    from LocalExtraction.about import command_name, version_text
    parser = argparse.ArgumentParser(
        prog=command_name("mme-ml-export", "MLDataset"),
        description="Prepare a dataset for machine learning: one family of materials, one property, one transport "
                    "component and origin, filtered for quality. Written to ~/MoukhlijMatExtract/Ready for ML/<name>/ "
                    "(dataset.csv, values.csv, excluded.csv, README.md, settings.json).",
        epilog="Examples: mme-ml-export --list · mme-ml-export --family garnet --target Ea --component bulk "
               "--origin experimental · mme-ml-export --family NASICON --target sigma --temperature room · "
               "mme-ml-export gui")
    parser.add_argument("--version", action="version", version=version_text("mme-ml-export"))
    parser.add_argument("--list", action="store_true", help="List the families, with how many values of each property")
    parser.add_argument("--settings", help="Make again the dataset of a settings.json (other options override it)")
    parser.add_argument("--family", "-f", help="garnet, NASICON, oxide … (a class of Classification), or a database "
                                               "such as database:WebScraping/web_output")
    parser.add_argument("--target", "-t", help="Ea (activation energy), sigma (ionic conductivity), sigma_e "
                                               "(electronic conductivity) or D (diffusion coefficient)")
    parser.add_argument("--component", "-c", choices=(*COMPONENTS, ANY), help="Transport component (default: any)")
    parser.add_argument("--origin", "-o", choices=(*ORIGINS, ANY), help="Measured or computed (default: any)")
    parser.add_argument("--attribution", choices=("this-work", "cited", ANY),
                        help="The paper's own results, cited ones, or any (default: this-work)")
    parser.add_argument("--kind", help="Activation energies: kind of energy (default: arrhenius; any for all)")
    parser.add_argument("--ion", help="Mobile ion: Li+, Na+ … (default: any)")
    parser.add_argument("--temperature", help="Conductivities and diffusion: any, room, or a range in K such as 300-400")
    parser.add_argument("--min", type=float, dest="value_min", help="Smallest value kept (in the property's unit)")
    parser.add_argument("--max", type=float, dest="value_max", help="Largest value kept (in the property's unit)")
    parser.add_argument("--include-flagged", action="store_true", help="Keep the values the extraction flagged")
    parser.add_argument("--no-needs-check", action="store_true", help="Leave out the values marked worth a look too")
    parser.add_argument("--min-confidence", type=float, help="Smallest extraction confidence kept (0 to 1)")
    parser.add_argument("--verified-only", action="store_true", help="Activation energies checked by hand only")
    parser.add_argument("--keep-duplicates", action="store_true",
                        help="Keep a value repeated in its paper or quoted from another paper (default: counted once, "
                             "its original kept)")
    parser.add_argument("--per-value", action="store_true", help="dataset.csv with one row per value, not per material")
    parser.add_argument("--min-values", type=int, help="A material needs at least this many values (default 1)")
    parser.add_argument("--name", help="Name of the dataset folder (default: made from the settings)")
    parser.add_argument("--out", help="Folder to write into (default: ~/MoukhlijMatExtract/Ready for ML)")
    return parser


def settings_from(args: argparse.Namespace) -> Settings:
    base = {}
    if args.settings:
        with open(args.settings, encoding="utf-8") as f:
            saved = json.load(f)
        base = {k: v for k, v in saved.items() if k in Settings.__dataclass_fields__}
    if args.family:
        base["family"] = args.family
    if not base.get("family"):
        raise ValueError("--family is needed (mme-ml-export --list shows them)")
    if args.target:
        key = TARGET_WORDS.get(args.target.lower(), args.target)
        if key not in PROPERTIES:
            raise ValueError(f"--target {args.target}: choose Ea, sigma, sigma_e or D")
        base["target"] = key
    for name in ("component", "origin", "value_min", "value_max", "min_confidence", "min_values", "name"):
        if getattr(args, name) is not None:
            base[name] = getattr(args, name)
    if args.attribution:
        base["attribution"] = args.attribution.replace("-", " ")
    if args.kind:
        base["energy_kind"] = args.kind
    if args.ion:
        base["mobile_ion"] = args.ion
    if args.temperature:
        base["temperature"] = args.temperature
    if args.include_flagged:
        base["plausible_only"] = False
    if args.no_needs_check:
        base["no_needs_check"] = True
    if args.verified_only:
        base["verified_only"] = True
    if args.per_value:
        base["per_material"] = False
    if args.keep_duplicates:
        base["keep_duplicates"] = True
    return Settings(**base)


def _list() -> int:
    every = export.families()
    if not every:
        print("No family yet: run 4 · Classification (mme-classify) for the crystal structures and structure families.")
        return 1
    print(f"{'family':52} {'Ea':>6} {'sigma':>7} {'sigma_e':>8} {'D':>5}")
    for family in every:
        n = export.counts(family)
        print(f"{family.label[:52]:52} {n['Ea']:>6} {n['sigma']:>7} {n['sigma_e']:>8} {n['D']:>5}")
    return 0


def _main(argv: Optional[Sequence[str]] = None) -> int:
    words = list(sys.argv[1:] if argv is None else argv)
    if words[:1] == ["gui"]:
        from .gui import main as window
        return window(words[1:])
    args = build_parser().parse_args(words)
    if args.list:
        return _list()
    try:
        settings = settings_from(args)
        chosen = export.select(settings)
        folder = export.generate(settings, out=args.out)
    except (ValueError, OSError) as error:
        print(f"mme-ml-export: {error}", file=sys.stderr)
        return 2
    print(f"Dataset written: {folder}")
    print(f"  {chosen.materials()} materials · {len(chosen.kept)} values from {chosen.papers()} papers · "
          f"{len(chosen.excluded)} values left out (see excluded.csv)")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """The command. Stopped from the terminal, it finishes and saves first (it takes seconds)."""
    words = list(sys.argv[1:] if argv is None else argv)
    if words[:1] == ["gui"]:
        return _main(argv)
    from LocalExtraction import runcontrol
    with runcontrol.finish_then_stop("ML export"):
        return _main(argv)


if __name__ == "__main__":
    sys.exit(main())
