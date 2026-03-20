PYTHON ?= python3.11
UV ?= uv
INPUT ?= $(HOME)/Documents/Inbox

.PHONY: install install-gui install-bundle install-path test lint run-example run-gui open-gui bundle-gui open-bundle

install:
	$(UV) sync --extra dev

install-gui:
	$(UV) sync --extra dev --extra gui

install-bundle:
	$(UV) sync --extra dev --extra gui --extra bundle

install-path:
	bash scripts/install-path.sh

test:
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(UV) run pytest

lint:
	$(UV) run ruff check src tests

run-example:
	$(UV) run sortdocs "$(INPUT)" --dry-run --config sortdocs.example.yaml

run-gui:
	$(UV) run sortdocs-gui

open-gui:
	open sortdocs-gui.command

bundle-gui:
	bash scripts/build-macos-app.sh

open-bundle:
	open dist/sortdocs.app
