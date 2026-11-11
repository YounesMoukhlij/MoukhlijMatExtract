# mme_gui/commands.py
"""`mme`: every command of the project in one, for an installed copy (no Makefile, no project folder needed).

    mme                       every command at a glance, with the typical runs
    mme help                  the same
    mme commands              the full reference: every command with all of its options (each one's own --help)
    mme commands --markdown --output docs/COMMANDS.md     the same, as the reference document of the project
    mme <part> [options]      runs that part: mme local …, mme web run …, mme rank …, mme eval score …

The parts: gui, local, web, dois, rank, classify, eval, release (the mme-* commands, without the "mme-"). The list
of commands and their options come from manual.py, which asks each command for its own --help: what is printed
here is what the installed program does."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from .manual import COMMANDS, START, Command, help_text, make_lines, overview

# The part names `mme <part>` takes, and the module each runs (its console script's).
PARTS = {
    "gui": ("mme_gui", ()),
    "local": ("LocalExtraction", ()),
    "web": ("WebScraping", ()),
    "dois": ("WebScraping.Fetch_DOIs.get_dois", ()),
    "rank": ("SelectingTopMaterial", ()),
    "classify": ("Classification", ()),
    "eval": ("Evaluation", ()),
    "release": ("Release", ()),
}
DOCS = "https://github.com/YounesMoukhlij/MoukhlijMatExtract/tree/main/docs"


def _plain(block: str) -> List[str]:
    """manual.START's marked lines ("§ heading", "• bullet", "$ command") as plain text."""
    out = []
    for line in block.strip("\n").splitlines():
        if line.startswith("§ "):
            out += ["", line[2:].upper(), ""]
        elif line.startswith(("• ", "$ ", "| ")):
            out.append(("  " if line[0] != "•" else "- ") + line[2:])
        else:
            out.append(line)
    return out


def at_a_glance() -> str:
    """What `mme help` prints."""
    lines = ["MoukhlijMatExtract — every command of the project", "",
             "Run any of them as `mme <part> …` or as its own command (mme-local …). Add --help for its options;",
             "`mme commands` prints every option of every command.", ""]
    lines += overview()
    lines += _plain(START)
    make = make_lines()
    if make:
        lines += ["", "WITH MAKE (in the project folder)", ""] + ["  " + line for line in make]
    lines += ["", f"Manuals: docs/MANUAL.md (how to use and reproduce), docs/COMMANDS.md (every option), {DOCS}"]
    return "\n".join(lines) + "\n"


_HOME = re.compile(re.escape(str(Path.home())))


def _portable(text: str) -> str:
    """A --help as it reads on any computer: the user's home folder written "~"."""
    return _HOME.sub("~", text)


def reference(markdown: bool = False, commands: Sequence[Command] = COMMANDS) -> str:
    """Every command with its whole --help, in the order of the manual. In Markdown, one section per command."""
    out: List[str] = []
    if markdown:
        out += ["# MoukhlijMatExtract — command reference", "",
                "Every command of the project with all of its options, as each prints them with `--help`.",
                "Written by `mme commands --markdown --output docs/COMMANDS.md` (or `make commands`): do not edit it by",
                "hand. How to use the commands, in order, and how to reproduce a result: [MANUAL.md](MANUAL.md).", "",
                "| Command | Same as | make | What it does |", "|---|---|---|---|"]
        out += [f"| [`{c.name}`](#{_anchor(c.name)}) | `{c.python_form}` | `{c.make or '–'}` | {c.what} |"
                for c in commands]
    for command in commands:
        ok, body = help_text(command)
        body = _portable(body) if ok else f"(its help could not be read: {body})"
        if markdown:
            out += ["", f"## {command.name}", "", f"*{command.part}* — {command.what}. "
                    f"Same as `{command.python_form}`" + (f"; with make: `{command.make}`." if command.make else "."),
                    "", "```text", body, "```"]
        else:
            out += ["", "=" * 100, f"{command.name}   ({command.python_form}; {command.make or 'no make target'})",
                    "=" * 100, body]
    return "\n".join(out).lstrip("\n") + "\n"


def _anchor(name: str) -> str:
    return re.sub(r"[^a-z0-9 -]", "", name.lower()).replace(" ", "-")


def run_part(part: str, args: Sequence[str]) -> int:
    """Runs `mme <part> args…` as the part's own command would, in this Python."""
    module, fixed = PARTS[part]
    env = dict(os.environ, MME_AS_COMMAND="1")
    try:
        return subprocess.call([sys.executable, "-m", module, *fixed, *args], env=env)
    except KeyboardInterrupt:
        return 130


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in PARTS:
        return run_part(argv[0], argv[1:])
    parser = argparse.ArgumentParser(
        prog="mme", description="Every command of MoukhlijMatExtract in one. `mme <part> …` runs a part ("
                                + ", ".join(PARTS) + "): mme local, mme web run, mme rank --domain cathode …")
    from LocalExtraction.about import version_text
    parser.add_argument("--version", action="version", version=version_text("mme"))
    sub = parser.add_subparsers(dest="what", metavar="{help,commands," + ",".join(PARTS) + "}")
    sub.add_parser("help", help="Every command at a glance, with the typical runs")
    ref = sub.add_parser("commands", help="Every command with all of its options")
    ref.add_argument("--markdown", action="store_true", help="As a Markdown document (docs/COMMANDS.md)")
    ref.add_argument("--output", "-o", metavar="FILE", help="Write it to FILE instead of printing it")
    for part, (module, _) in PARTS.items():
        sub.add_parser(part, help=f"Runs {module} (mme-{part}); add --help for its options", add_help=False)
    args = parser.parse_args(argv)
    if args.what in (None, "help"):
        sys.stdout.write(at_a_glance())
        return 0
    text = reference(markdown=args.markdown)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
