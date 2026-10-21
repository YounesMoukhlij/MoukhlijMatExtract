# Each part runs on its own; these are shortcuts to their commands (run from the project root).

help:
	@echo "make local      python3 -m LocalExtraction               extract the PDFs of LocalExtraction/papers"
	@echo "make local-gui  python3 -m LocalExtraction gui           the same, in a window"
	@echo "make web        python3 -m WebScraping                   search, download and extract the papers of the job"
	@echo "make web-gui    python3 -m WebScraping gui               search, review, download, extract in a window"
	@echo "make rank       python3 -m SelectingTopMaterial          rank the materials of the databases"
	@echo "make rank-gui   python3 -m SelectingTopMaterial gui      the same, in a window"
	@echo "make classify   python3 \"Crystal and Structure Classification\"   classify the materials by structure"
	@echo "make test       python3 -m pytest                        every test of the four parts"
	@echo "make clean      remove the __pycache__ folders"

local:
	@echo "Running LocalExtraction..."
	python3 -m LocalExtraction

local-gui:
	@echo "Running LocalExtraction in GUI mode..."
	python3 -m LocalExtraction gui

web:
	@echo "Running WebScraping..."
	python3 -m WebScraping

web-gui:
	@echo "Running WebScraping in GUI mode..."
	python3 -m WebScraping gui

rank:
	@echo "Running SelectingTopMaterial..."
	@python3 -m SelectingTopMaterial

rank-gui:
	@echo "Running SelectingTopMaterial in GUI mode..."
	@python3 -m SelectingTopMaterial gui

classify:
	@echo "Running Crystal and Structure Classification..."
	python3 "Crystal and Structure Classification"

test:
	@echo "Running tests..."
	python3 -m pytest

clean:
	@echo "Removing __pycache__ folders..."
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

.PHONY: help local local-gui web web-gui rank rank-gui classify test clean
