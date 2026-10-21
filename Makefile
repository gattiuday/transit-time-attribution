PY ?= python3
export PYTHONPATH := $(CURDIR)/src:$(CURDIR)/experiments:$(CURDIR)/tests

.PHONY: help install lint test experiments fixture evidence diagram receipts verify clean

help:
	@echo "install      install the package and development dependencies"
	@echo "lint         ruff check and format check"
	@echo "test         pytest with coverage and machine readable reports"
	@echo "experiments  re-run every experiment into docs/experiments/"
	@echo "fixture      regenerate the committed event log"
	@echo "evidence     re-capture the console evidence SVGs"
	@echo "diagram      re-render the architecture SVG"
	@echo "receipts     re-measure every published figure and check the prose"
	@echo "verify       lint, test, receipts, then the suite again. See ADR-006."

install:
	$(PY) -m pip install -e ".[dev]"

lint:
	ruff check src tests experiments tools
	ruff format --check src tests experiments tools

test:
	$(PY) -m pytest tests/ -q --junitxml=junit.xml --cov=tta --cov-report=json --cov-report=term

experiments:
	@for e in experiments/exp*.py; do echo "== $$e"; $(PY) $$e; done

fixture:
	$(PY) -m tta.cli generate --out data/fixtures/event-log.csv \
	  --truth data/fixtures/planted-causes.csv

evidence:
	$(PY) tools/capture_evidence.py

diagram:
	$(PY) tools/render_diagram.py

# `collect_metrics --skip-tests` reads junit.xml and coverage.json, which are
# not committed, so this target used to fail with a FileNotFoundError traceback
# on a fresh clone while the help text advertised it as standalone. It runs the
# suite first if those files are missing.
receipts:
	@test -f junit.xml -a -f coverage.json || $(MAKE) test
	$(PY) tools/capture_evidence.py
	$(PY) tools/collect_metrics.py --skip-tests
	$(PY) tools/check_numbers.py

# The suite runs twice, deliberately. The second run is the mitigation ADR-006
# names for exempting the receipts suite from the collector's red run guard:
# those tests read the file collection writes, so they can only be judged after
# it has been written. An earlier version of this target was `lint test
# receipts` while ADR-006 claimed the suite ran afterwards, which meant the one
# safeguard the ADR relied on did not exist.
verify: lint test receipts
	$(PY) -m pytest tests/ -q

clean:
	rm -rf .pytest_cache .ruff_cache junit.xml coverage.json .coverage
