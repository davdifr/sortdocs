PYTHON ?= python3.11
UV ?= uv
INPUT ?= $(HOME)/Documents/Inbox

.PHONY: install install-path test lint run-example

install:
	$(UV) sync --extra dev

install-path:
	bash scripts/install-path.sh

test:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(UV) run pytest

lint:
	$(UV) run ruff check src tests

run-example:
	$(UV) run sortdocs "$(INPUT)" --dry-run --config sortdocs.example.yaml
