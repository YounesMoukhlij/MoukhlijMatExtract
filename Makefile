# MoukhlijMatExtract — every command of the project, with every option, from the project root.
#
#   make help                 this list (every target, every option)
#   make <part>-help          the command's own help (make local-help, make web-help, make rank-help, ...)
#
# An option is given as NAME=value after the target, named after the option it sets:
#   make local WORKERS=8 OFFLINE=1          ->  python -m LocalExtraction extract --workers 8 --offline
#   make rank COMPONENT="grain boundary" TOP=20 FORMAT="csv html"
# A switch (an option without a value) is on with NAME=1. Only what is written on the make command line
# counts: a variable of the same name in your shell (SOURCE, JOB, TOP, ...) is not taken by mistake.
# The commands run inside the project's venv (.venv/) when it exists, even if it is not activated.

PYTHON := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

# The mme-* commands of .venv run the code of this folder (pip install -e .). When the package itself changes
# (pyproject.toml, setup.py: a new part, a new folder), they are registered again before anything runs, by itself,
# so that mme-gui and the others keep working from any folder. Nothing is downloaded: the dependencies stay.
STAMP := .venv/.mme-installed
$(STAMP): pyproject.toml setup.py
	@if [ -x .venv/bin/python ]; then \
	    echo "The package changed: registering it again in .venv (no download) ..."; \
	    .venv/bin/python -m pip install -q --no-deps -e . && rm -rf build *.egg-info && touch $(STAMP); fi

# ---- How an option is written -------------------------------------------------------------------
# given NAME            : NAME was written on the make command line
# opt NAME,--flag       : --flag 'value'            (a value, quoted: it may hold spaces)
# list NAME,--flag      : --flag value value ...    (several values, split on spaces)
# switch NAME,--flag    : --flag when NAME=1 (or yes / true / on)
given  = $(filter command line,$(origin $(1)))
quote  = '$(subst ','\'',$(1))'
opt    = $(if $(call given,$(1)),$(2) $(call quote,$($(1))))
list   = $(if $(call given,$(1)),$(2) $($(1)))
switch = $(if $(call given,$(1)),$(if $(filter 1 yes true on YES TRUE ON,$($(1))),$(2)))

# ---- The options of each command ---------------------------------------------------------------
LOCAL_OPTS  = $(call opt,INPUT,--input) $(call opt,OUTPUT,--output) $(call opt,WORKERS,--workers) \
              $(call switch,VERBOSE,--verbose) $(call switch,OFFLINE,--offline) $(call opt,DOMAIN,--domain)
WEB_COMMON  = $(call opt,JOB,--job) $(call opt,OUTPUT,--output) $(call opt,WORKERS,--workers) \
              $(call switch,VERBOSE,--verbose)
# DOIS=1: the list of Fetch DOIs; DOIS=path/to/list.csv: that list
WEB_DOIS    = $(if $(call given,DOIS),--dois $(if $(filter 1 yes true on,$(DOIS)),,$(call quote,$(DOIS))))
WEB_OPTS    = $(WEB_COMMON) $(call opt,STAGE,--stage) $(call switch,YES,--yes) $(call opt,LIMIT,--limit) \
              $(WEB_DOIS) $(call switch,CHECK,--check) $(call opt,PROBE_DOI,--probe-doi) \
              $(call switch,REFRESH,--refresh) $(call switch,REBUILD,--rebuild) $(call switch,RESCREEN,--rescreen) \
              $(call switch,SNOWBALL,--snowball) $(call switch,UPDATE,--update)
DOI_OPTS    = $(call opt,COUNT,--count) $(call opt,JOB,--job) $(call opt,MAX,--max) $(call opt,OUT,--out) \
              $(call switch,REFRESH,--refresh) $(call switch,NO_EXPAND,--no-expand) \
              $(if $(call given,KEYWORDS),$(KEYWORDS))
RANK_OPTS   = $(call list,SOURCE,--source) $(call opt,OUT,--out) $(call opt,CRITERIA,--criteria) \
              $(call opt,DOMAIN,--domain) $(call opt,KIND,--kind) \
              $(call opt,POLICY,--policy) $(call switch,BY_PHASE,--by-phase) $(call opt,ORIGIN,--origin) \
              $(call opt,ATTRIBUTION,--attribution) $(call opt,COMPONENT,--component) \
              $(call list,ELEMENT,--element) $(call opt,MIN_CONFIDENCE,--min-confidence) $(call opt,TOP,--top) \
              $(call switch,INCLUDE_FLAGGED,--include-flagged) $(call switch,VERIFIED_ONLY,--verified-only) \
              $(call switch,MATERIALS_PROJECT,--materials-project) \
              $(call opt,BOOTSTRAP,--bootstrap) $(call list,FORMAT,--format) $(call switch,NO_FILES,--no-files) $(call switch,OPEN,--open) \
              $(call switch,QUIET,--quiet) $(call switch,NO_COLOR,--no-color) $(call switch,FORCE,--force)
RANK_GUI_OPTS = $(call list,SOURCE,--source) $(call opt,OUT,--out) $(call opt,CRITERIA,--criteria)
CLASSIFY_OPTS = $(call list,SOURCE,--source) $(call opt,OUT,--out) $(call switch,FORCE,--force)
CLASSIFY_GUI_OPTS = $(call list,SOURCE,--source) $(call opt,OUT,--out) $(call switch,NO_WRITE,--no-write)
GUI_OPTS = $(call switch,INSTALL_APP,--install-app)
ML_OPTS = $(call switch,LIST,--list) $(call opt,SETTINGS,--settings) $(call opt,FAMILY,--family) \
              $(call opt,TARGET,--target) $(call opt,COMPONENT,--component) $(call opt,ORIGIN,--origin) \
              $(call opt,ATTRIBUTION,--attribution) $(call opt,KIND,--kind) $(call opt,ION,--ion) \
              $(call opt,TEMPERATURE,--temperature) $(call opt,MIN,--min) $(call opt,MAX,--max) \
              $(call switch,INCLUDE_FLAGGED,--include-flagged) $(call switch,NO_NEEDS_CHECK,--no-needs-check) \
              $(call opt,MIN_CONFIDENCE,--min-confidence) $(call switch,VERIFIED_ONLY,--verified-only) \
              $(call switch,PER_VALUE,--per-value) $(call opt,MIN_VALUES,--min-values) $(call opt,NAME,--name) \
              $(call opt,OUT,--out)
EVAL_SHEET_OPTS = $(call list,SOURCE,--source) $(call opt,PAPERS,--papers) $(call opt,SEED,--seed) \
              $(call opt,OUT,--out) $(call switch,FORCE,--force) $(call switch,ALL_PAPERS,--all-papers)
EVAL_SCORE_OPTS = $(call opt,GOLD,--gold) $(call list,SOURCE,--source) $(call opt,OUT,--out) $(call opt,SEED,--seed) \
              $(call list,PREDICTIONS,--predictions)
EVAL_REF_OPTS = $(call list,DB,--db) $(call switch,NO_FETCH,--no-fetch) $(call opt,LIMIT,--limit) \
              $(call switch,REFRESH,--refresh) $(call opt,WORKERS,--workers) $(call list,PREDICTIONS,--predictions) \
              $(call opt,AGAINST,--against)
RELEASE_OPTS = $(call list,SOURCE,--source) $(call list,WITH,--with) $(call switch,NO_RESULTS,--no-results) \
              $(call opt,OUT,--out) $(call switch,KEEP_TEXT,--keep-text) $(call opt,FINISH,--finish) \
              $(call switch,KEEP_UNRECORDED,--keep-unrecorded)
TEST_OPTS   = $(if $(call given,K),-k $(call quote,$(K))) $(call switch,VERBOSE,-v) $(call switch,FAST,-x) \
              $(if $(call given,TESTS),$(TESTS)) $(if $(call given,ARGS),$(ARGS))

help:
	@echo "MoukhlijMatExtract — make <target> [NAME=value ...]     (python here: $(PYTHON))"
	@echo ""
	@echo "Set up and look after"
	@echo "  make install        create .venv/, install requirements.txt, the project and the language model"
	@echo "  make install-locked the same, with the exact versions of requirements.lock (to reproduce published results)"
	@echo "  make lock           write requirements.lock: the exact versions of this venv"
	@echo "  make dictionary     rewrite docs/DATA_DICTIONARY.md (every column of the database) from LocalExtraction/schema.py"
	@echo "  make demo           the worked example: two open-access papers through every step -> examples/output/"
	@echo "  make test          every test        K=<words> (-k)  TESTS=<files or folders>  VERBOSE=1  FAST=1 (-x)  ARGS=<more pytest options>"
	@echo "  make clean          remove every __pycache__ folder"
	@echo "  make version        the version of MoukhlijMatExtract"
	@echo "  make commands       rewrite docs/COMMANDS.md: every command with all of its options (from each one's --help)"
	@echo "  make manual         every command at a glance, with the typical runs (= mme help)"
	@echo ""
	@echo "The one window"
	@echo "  make gui            python -m mme_gui: one button per part"
	@echo ""
	@echo "1 · Local extraction (python -m LocalExtraction)"
	@echo "  make local          extract the PDFs of LocalExtraction/papers"
	@echo "                      INPUT=<folder> OUTPUT=<folder> WORKERS=<n> VERBOSE=1 OFFLINE=1 REBUILD=1"
	@echo "                      DOMAIN=electrolyte|cathode|anode (what the papers are about; one output folder per domain)"
	@echo "  make local-cathode  the PDFs of LocalExtraction/papers_cathode -> LocalExtraction/output_cathode (DOMAIN=cathode)"
	@echo "  make local-anode    the PDFs of LocalExtraction/papers_anode -> LocalExtraction/output_anode (DOMAIN=anode)"
	@echo "  make local-rebuild  extract every PDF again (the present database is moved to <output>/previous_<date>/)"
	@echo "  make local-gui      the same, in a window       INPUT= OUTPUT= WORKERS= VERBOSE=1 OFFLINE=1"
	@echo ""
	@echo "2 · Web scraping (python -m WebScraping)"
	@echo "  make doi            1 · Fetch DOIs: the job's keywords asked for DOIs, saved in the DOI list"
	@echo "                      COUNT=<new DOIs, else until Ctrl-C> JOB=<job file> MAX=<results per source per keyword>"
	@echo "                      OUT=<list.csv> REFRESH=1 NO_EXPAND=1 KEYWORDS='\"solid electrolyte\" \"LLZO garnet\"'"
	@echo "  make web            the whole run: search (keywords + DOIs), review, download, extract"
	@echo "                      JOB=<job file> OUTPUT=<folder> WORKERS=<n> VERBOSE=1 STAGE=discover|fetch|extract"
	@echo "                      YES=1 (approve without review) LIMIT=<papers> DOIS=1|<list.csv> CHECK=1 PROBE_DOI=<doi>"
	@echo "                      REFRESH=1 (search again) REBUILD=1 (extract again) RESCREEN=1 (decide the papers again)"
	@echo "                      SNOWBALL=1 (also follow the citations of the papers kept) UPDATE=1 (only what is new)"
	@echo "  make update         every job run before, searched for what was published since    YES=1 WORKERS=<n>"
	@echo "  make web-check      test the setup: network, API keys, folders       JOB= PROBE_DOI=<an Elsevier DOI>"
	@echo "  make coverage       how far each job's papers went, and by publisher -> WebScraping/coverage/"
	@echo "  make web-fetch      after the review: download what is approved, then extract   (STAGE=fetch; LIMIT= YES=1 ...)"
	@echo "  make web-extract    only extract what is downloaded                              (STAGE=extract; REBUILD=1 ...)"
	@echo "  make web-dois       the saved DOIs only: checked, then those on topic downloaded and extracted   (DOIS=<list.csv>)"
	@echo "  make web-gui        the window                    JOB= OUTPUT= WORKERS= VERBOSE=1"
	@echo "  make web-cathode    the whole run for cathodes: configs/cathode.yaml -> WebScraping/web_output_cathode (every web option)"
	@echo "  make web-anode      the whole run for anodes:   configs/anode.yaml -> WebScraping/web_output_anode (every web option)"
	@echo ""
	@echo "3 · Ranking (python -m SelectingTopMaterial)"
	@echo "  make rank           rank the materials by activation energy"
	@echo "                      SOURCE='<folder> <folder>' OUT=<folder> CRITERIA=<file.toml> POLICY=consensus|optimistic|conservative"
	@echo "                      BY_PHASE=1 ORIGIN=experimental|simulation ATTRIBUTION=this-work|cited"
	@echo "                      COMPONENT=bulk|grain_boundary|total ELEMENT='Li Na' MIN_CONFIDENCE=<0-1> TOP=<n> INCLUDE_FLAGGED=1"
	@echo "                      DOMAIN=electrolyte|cathode|anode (the criteria of that domain)"
	@echo "                      KIND=arrhenius|migration_barrier|bvse|local_hop|vtf|unspecified (one kind of energy)"
	@echo "                      FORMAT='csv xlsx json html' NO_FILES=1 OPEN=1 QUIET=1 NO_COLOR=1 FORCE=1"
	@echo "  make rank-gui       the window                    SOURCE= OUT= CRITERIA="
	@echo "  make rank-cathode   rank WebScraping/web_output_cathode with the cathode criteria -> SelectingTopMaterial/results_cathode"
	@echo "  make rank-anode     rank WebScraping/web_output_anode with the anode criteria -> SelectingTopMaterial/results_anode"
	@echo ""
	@echo "4 · Classification (python -m Classification)"
	@echo "  make classify       classify the materials by structure     SOURCE='<folder> <folder>' OUT=<folder> FORCE=1"
	@echo "  make classify-gui   the window                    SOURCE= OUT= NO_WRITE=1"
	@echo ""
	@echo "Evaluation — how accurate is the extraction? (python -m Evaluation)"
	@echo "  make eval-sheet     draw papers at random, write the workbook to annotate (Evaluation/annotation.xlsx)"
	@echo "                      SOURCE='<folder> <folder>' PAPERS=<n, default 60> SEED=<n> OUT=<file.xlsx> FORCE=1"
	@echo "                      ALL_PAPERS=1 (draw from every paper, not only those mme-release would publish)"
	@echo "  make eval-score     precision, recall, F1 (95 % intervals), calibration, errors -> Evaluation/scores/"
	@echo "                      GOLD=<annotated.xlsx> SOURCE='<folder> ...' (score a newer run) OUT=<folder> SEED=<n>"
	@echo "                      PREDICTIONS='<other_tool.csv> ...' (other tools scored the same way, compared side by side)"
	@echo "  make eval-agree     agreement of two annotators      FIRST=<a.xlsx> SECOND=<b.xlsx>"
	@echo "  make eval-reference recall against curated databases (OBELiX, Liverpool), on their own papers"
	@echo "                      AGAINST=<results folder>: that database against them, material by material"
	@echo "                      DB='obelix liverpool' NO_FETCH=1 LIMIT=<papers> REFRESH=1 WORKERS=<n>"
	@echo "                      PREDICTIONS='<other_tool.csv> ...' (other tools scored the same way, side by side)"
	@echo ""
	@echo "Release — the dataset, ready to deposit (python -m Release)"
	@echo "  make release        databases + ranking + classification, license-checked, with datasheet and SHA256SUMS -> Release/"
	@echo "                      SOURCE='<folder> ...' WITH='<folder> ...' NO_RESULTS=1 OUT=<folder> KEEP_TEXT=1"
	@echo "                      KEEP_UNRECORDED=1 (keep papers with no record of a legal copy: private copies only)"
	@echo "  make release FINISH=<release folder>    after completing its README: SHA256SUMS and .zip again"
	@echo ""
	@echo "Each command's own help: make gui-help, local-help, local-gui-help, web-help, web-gui-help, doi-help,"
	@echo "rank-help, rank-gui-help, classify-help, classify-gui-help, eval-help, release-help, mme-help"
	@echo "Installed without this folder: the same commands as mme <part> …  (mme help, mme commands)"

# ---- Set up and look after ------------------------------------------------------------------------
install:
	@test -d .venv || { echo "Creating the venv .venv/..."; python3 -m venv .venv; }
	@echo "Installing requirements.txt into .venv/..."
	@.venv/bin/python -m pip install -r requirements.txt
	@.venv/bin/python -m pip install -e .   # the mme-* commands run the code of this folder
	@.venv/bin/python -m spacy download en_core_web_sm
	@echo "Done. Enter the venv in each new terminal with: source .venv/bin/activate"

install-locked:
	@test -d .venv || { echo "Creating the venv .venv/..."; python3 -m venv .venv; }
	@echo "Installing the exact versions of requirements.lock into .venv/..."
	@.venv/bin/python -m pip install -r requirements.lock
	@.venv/bin/python -m pip install --no-deps -e .
	@echo "Done. Enter the venv in each new terminal with: source .venv/bin/activate"

lock:
	@{ echo "# The exact environment MoukhlijMatExtract was run with. Install it with: make install-locked"; \
	   echo "# Python $$($(PYTHON) -c 'import sys; print(sys.version.split()[0])') on $$(uname -sm), written $$(date -u +%Y-%m-%d)."; \
	   echo "# requirements.txt keeps the ranges the program works with; this file, the versions it was run with."; \
	   $(PYTHON) -m pip freeze --exclude-editable; } > requirements.lock
	@echo "Wrote requirements.lock ($$(grep -vc '^#' requirements.lock) packages)"

dictionary:
	@$(PYTHON) -m LocalExtraction.schema

demo:
	@echo "The worked example: two CC BY papers (examples/README.md) -> examples/output/"
	$(PYTHON) -m LocalExtraction extract -i "$(CURDIR)/examples/papers" -o "$(CURDIR)/examples/output/database" --offline
	$(PYTHON) -m SelectingTopMaterial --source "$(CURDIR)/examples/output/database" --out "$(CURDIR)/examples/output/ranking"
	$(PYTHON) -m Classification --source "$(CURDIR)/examples/output/database" --out "$(CURDIR)/examples/output/classes"

test:
	$(PYTHON) -m pytest $(TEST_OPTS)

clean:
	@echo "Removing every __pycache__ folder under $(CURDIR)..."
	@found=$$(find . -type d -name __pycache__ -prune | wc -l | tr -d ' '); \
	find . -type d -name __pycache__ -prune -exec rm -rf {} +; \
	left=$$(find . -type d -name __pycache__ -prune | wc -l | tr -d ' '); \
	echo "Removed $$found __pycache__ folder(s), $$left left."

version:
	@$(PYTHON) -m mme_gui --version

commands:
	@$(PYTHON) -m mme_gui.commands commands --markdown --output docs/COMMANDS.md

manual:
	@$(PYTHON) -m mme_gui.commands help

# ---- The one window ---------------------------------------------------------------------------------
gui:
	@$(PYTHON) -m mme_gui $(GUI_OPTS)

# ---- 1 · Local extraction ---------------------------------------------------------------------------
local:
	$(PYTHON) -m LocalExtraction extract $(LOCAL_OPTS) $(call switch,REBUILD,--rebuild)

local-rebuild:
	$(PYTHON) -m LocalExtraction extract $(LOCAL_OPTS) --rebuild

local-gui:
	$(PYTHON) -m LocalExtraction gui $(LOCAL_OPTS)

local-cathode:
	$(PYTHON) -m LocalExtraction extract --domain cathode --input LocalExtraction/papers_cathode \
	    --output LocalExtraction/output_cathode $(LOCAL_OPTS) $(call switch,REBUILD,--rebuild)

local-anode:
	$(PYTHON) -m LocalExtraction extract --domain anode --input LocalExtraction/papers_anode \
	    --output LocalExtraction/output_anode $(LOCAL_OPTS) $(call switch,REBUILD,--rebuild)

# ---- 2 · Web scraping -------------------------------------------------------------------------------
doi:
	$(PYTHON) -m WebScraping.Fetch_DOIs.get_dois $(DOI_OPTS)

web:
	$(PYTHON) -m WebScraping run $(WEB_OPTS)

web-check:
	$(PYTHON) -m WebScraping run --check $(call opt,JOB,--job) $(call opt,OUTPUT,--output) $(call opt,PROBE_DOI,--probe-doi) $(call switch,VERBOSE,--verbose)

web-fetch:
	$(PYTHON) -m WebScraping run --stage fetch $(WEB_COMMON) $(call switch,YES,--yes) $(call opt,LIMIT,--limit) $(call switch,REBUILD,--rebuild)

web-extract:
	$(PYTHON) -m WebScraping run --stage extract $(WEB_COMMON) $(call switch,REBUILD,--rebuild)

web-dois:
	$(PYTHON) -m WebScraping run $(WEB_COMMON) $(if $(call given,DOIS),$(WEB_DOIS),--dois) $(call switch,YES,--yes) $(call opt,LIMIT,--limit)

web-gui:
	$(PYTHON) -m WebScraping gui $(WEB_COMMON)

update:
	$(PYTHON) -m WebScraping update $(call switch,YES,--yes) $(call opt,WORKERS,--workers) $(call switch,VERBOSE,--verbose)

coverage:
	$(PYTHON) -m WebScraping coverage $(call opt,OUTPUT,--output) $(call switch,VERBOSE,--verbose)

web-cathode:
	$(PYTHON) -m WebScraping run --job configs/cathode.yaml --output WebScraping/web_output_cathode $(WEB_OPTS)

web-anode:
	$(PYTHON) -m WebScraping run --job configs/anode.yaml --output WebScraping/web_output_anode $(WEB_OPTS)

# ---- 3 · Ranking ------------------------------------------------------------------------------------
rank:
	$(PYTHON) -m SelectingTopMaterial $(RANK_OPTS)

rank-gui:
	$(PYTHON) -m SelectingTopMaterial gui $(RANK_GUI_OPTS)

rank-cathode:
	$(PYTHON) -m SelectingTopMaterial --domain cathode --source WebScraping/web_output_cathode \
	    --out SelectingTopMaterial/results_cathode $(RANK_OPTS)

rank-anode:
	$(PYTHON) -m SelectingTopMaterial --domain anode --source WebScraping/web_output_anode \
	    --out SelectingTopMaterial/results_anode $(RANK_OPTS)

# ---- 4 · Classification -----------------------------------------------------------------------------
classify:
	$(PYTHON) -m Classification $(CLASSIFY_OPTS)

classify-gui:
	$(PYTHON) -m Classification gui $(CLASSIFY_GUI_OPTS)

# ---- Evaluation --------------------------------------------------------------------------------------
eval-sheet:
	$(PYTHON) -m Evaluation sheet $(EVAL_SHEET_OPTS)

eval-score:
	$(PYTHON) -m Evaluation score $(EVAL_SCORE_OPTS)

eval-reference:
	$(PYTHON) -m Evaluation reference $(EVAL_REF_OPTS)

eval-agree:
	@test -n "$(FIRST)" -a -n "$(SECOND)" || { echo "make eval-agree FIRST=<a.xlsx> SECOND=<b.xlsx>"; exit 2; }
	$(PYTHON) -m Evaluation agree $(call quote,$(FIRST)) $(call quote,$(SECOND))

# ---- Release ----------------------------------------------------------------------------------------
release:
	$(PYTHON) -m Release $(RELEASE_OPTS)

# ---- Each command's own help ------------------------------------------------------------------------
gui-help:
	@$(PYTHON) -m mme_gui --help
local-help:
	@$(PYTHON) -m LocalExtraction extract --help
local-gui-help:
	@$(PYTHON) -m LocalExtraction gui --help
web-help:
	@$(PYTHON) -m WebScraping run --help
web-gui-help:
	@$(PYTHON) -m WebScraping gui --help
doi-help:
	@$(PYTHON) -m WebScraping.Fetch_DOIs.get_dois --help
rank-help:
	@$(PYTHON) -m SelectingTopMaterial --help
rank-gui-help:
	@$(PYTHON) -m SelectingTopMaterial gui --help
classify-help:
	@$(PYTHON) -m Classification --help
classify-gui-help:
	@$(PYTHON) -m Classification gui --help
eval-help:
	@$(PYTHON) -m Evaluation --help; echo; $(PYTHON) -m Evaluation sheet --help; echo; \
	 $(PYTHON) -m Evaluation score --help; echo; $(PYTHON) -m Evaluation agree --help; echo; \
	 $(PYTHON) -m Evaluation reference --help
release-help:
	@$(PYTHON) -m Release --help
mme-help:
	@$(PYTHON) -m mme_gui.commands --help

.PHONY: demo help ml-export ml-gui app install install-locked lock dictionary commands manual test clean version gui local local-rebuild local-gui \
        local-cathode local-anode web-cathode web-anode rank-cathode rank-anode mme-help \
        doi web web-check web-fetch web-extract \
        web-dois web-gui coverage update rank rank-gui classify classify-gui gui-help local-help local-gui-help web-help \
        web-gui-help doi-help rank-help rank-gui-help classify-help classify-gui-help eval-sheet eval-score \
        eval-agree eval-reference eval-help release release-help

# Every target that runs the program first makes sure .venv knows the package as it is now ($(STAMP)).
test demo dictionary commands manual gui local local-rebuild local-gui local-cathode local-anode doi web web-check web-fetch web-extract web-dois web-gui coverage update web-cathode web-anode rank rank-gui rank-cathode rank-anode classify classify-gui eval-sheet eval-score eval-reference eval-agree release: | $(STAMP)

# ---- 5 · ML datasets ----------------------------------------------------------------------------------
ml-export:  ## a dataset for machine learning: make ml-export FAMILY=garnet TARGET=Ea COMPONENT=bulk ORIGIN=experimental
	$(PYTHON) -m MLDataset $(ML_OPTS)

ml-gui:  ## the ML datasets window
	$(PYTHON) -m MLDataset gui

app:  ## macOS: ~/Applications/MoukhlijMatExtract.app, the main window with its own name and icon in the Dock
	$(PYTHON) -m mme_gui --install-app
