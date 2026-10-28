# Each part runs on its own; these are shortcuts to their commands (run from the project root).
# They run inside the project's venv (.venv/) when it exists, even if it is not activated.

PYTHON := $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

help:
	@echo "make install    create the venv .venv/ and install requirements.txt and the language model into it"
	@echo "make gui        python -m mme_gui                        the one window for the whole project (every part)"
	@echo "make local      python -m LocalExtraction                extract the PDFs of LocalExtraction/papers"
	@echo "make local-gui  python -m LocalExtraction gui            the same, in a window"
	@echo "make web        python -m WebScraping                    method 1: search open sources, download and extract"
	@echo "make web-gui    python -m WebScraping gui                the web two-method chooser, in a window"
	@echo "make doi        add new DOIs to WebScraping/Fetch_DOIs/dois.csv + dois.txt: make doi COUNT=500 (no COUNT: until Ctrl-C)"
	@echo "make rank       python -m SelectingTopMaterial           rank the materials of the databases"
	@echo "make rank-gui   python -m SelectingTopMaterial gui       the same, in a window"
	@echo "make classify   python -m Classification   classify the materials by structure"
	@echo "make classify-gui  python -m Classification gui   the same, in a window"
	@echo "make test       python -m pytest                         every test of the four parts"
	@echo "make clean      remove every __pycache__ folder, in every subfolder of the project"
	@echo "(python here is $(PYTHON))"

install:
	@test -d .venv || { echo "Creating the venv .venv/..."; python3 -m venv .venv; }
	@echo "Installing requirements.txt into .venv/..."
	@.venv/bin/python -m pip install -r requirements.txt
	@.venv/bin/python -m spacy download en_core_web_sm
	@echo "Done. Enter the venv in each new terminal with: source .venv/bin/activate"

gui:
	@echo "Opening the MoukhlijMatExtract window..."
	@$(PYTHON) -m mme_gui

local:
	@echo "Running LocalExtraction..."
	@$(PYTHON) -m LocalExtraction

local-gui:
	@echo "Running LocalExtraction in GUI mode..."
	@$(PYTHON) -m LocalExtraction gui

web:
	@echo "Running WebScraping..."
	@$(PYTHON) -m WebScraping

web-gui:
	@echo "Running WebScraping in GUI mode..."
	@$(PYTHON) -m WebScraping gui

doi:
	@echo "Running Fetch_DOIs..."
	@$(PYTHON) WebScraping/Fetch_DOIs/get_dois.py $(if $(COUNT),--count $(COUNT))

rank:
	@echo "Running SelectingTopMaterial..."
	@$(PYTHON) -m SelectingTopMaterial

rank-gui:
	@echo "Running SelectingTopMaterial in GUI mode..."
	@$(PYTHON) -m SelectingTopMaterial gui

classify:
	@echo "Running Crystal and Structure Classification..."
	@$(PYTHON) -m Classification

classify-gui:
	@echo "Running Crystal and Structure Classification in GUI mode..."
	@$(PYTHON) -m Classification gui

test:
	@echo "Running tests..."
	$(PYTHON) -m pytest

clean:
	@echo "Removing every __pycache__ folder under $(CURDIR)..."
	@found=$$(find . -type d -name __pycache__ -prune | wc -l | tr -d ' '); \
	find . -type d -name __pycache__ -prune -exec rm -rf {} +; \
	left=$$(find . -type d -name __pycache__ -prune | wc -l | tr -d ' '); \
	echo "Removed $$found __pycache__ folder(s), $$left left."

.PHONY: help install gui local local-gui web web-gui doi rank rank-gui classify classify-gui test clean
