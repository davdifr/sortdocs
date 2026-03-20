# sortdocs

`sortdocs` is a Python CLI tool for macOS that organizes local documents based on file content, metadata, and OpenAI-powered classification.

The workflow is intentionally simple:

1. move into the folder you want to organize
2. run `sortdocs .`
3. the tool scans recursively, builds a plan, and asks for confirmation
4. if you confirm, it safely moves and renames files

## Features

- installable CLI command: `sortdocs`
- recursive scanning by default
- initial support for `pdf`, `txt`, `md`, `jpg`, `png`, `docx`
- classification via the OpenAI Responses API
- readable terminal output with a plan and final summary
- first-run onboarding with guided OpenAI API key setup
- guardrails for renames, extensions, path traversal, and collisions
- project-folder protection and nested project subtree skipping
- conservative fallback behavior for weak or ambiguous files
- local memory to improve path reuse across runs
- explicit ignore rules via config or `.sortdocsignore`
- incremental classification cache for unchanged files

## Requirements

- macOS
- Python 3.11+
- an OpenAI Platform API key

## Installation

### With `uv`

```bash
git clone <your-repo-url> sortdocs
cd sortdocs
uv sync --extra dev
```

To install the optional desktop GUI too:

```bash
uv sync --extra dev --extra gui
```

### With `pip`

```bash
git clone <your-repo-url> sortdocs
cd sortdocs
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

To install the optional desktop GUI too:

```bash
pip install -e '.[dev,gui]'
```

## Install The Command In Your PATH

To make `sortdocs` available as a global command:

```bash
bash scripts/install-path.sh
hash -r
```

The launcher is installed into a directory already present in your `PATH` and forwards to the project's `.venv`.

After that, you can simply run:

```bash
cd ~/Documents
sortdocs .
```

Useful note:

- on first run, `sortdocs` can guide you through API key setup interactively
- if you save the key during onboarding, it is stored in `~/.config/sortdocs/.env`
- the launcher created by `scripts/install-path.sh` automatically loads the project's `.env` file if it exists
- the launcher also loads `~/.config/sortdocs/.env` if it exists
- if you run `.venv/bin/sortdocs` directly, the global `~/.config/sortdocs/.env` still works, but a project-local `.env` is not auto-loaded

## Desktop GUI

`sortdocs` also includes an optional macOS desktop GUI built on PySide6.

Install the GUI extra:

```bash
uv sync --extra gui
```

or:

```bash
pip install -e '.[gui]'
```

Then launch it with:

```bash
sortdocs-gui
```

If you prefer launching it from Finder, you can also double-click:

```text
sortdocs-gui.command
```

This launcher:

- loads `~/.config/sortdocs/.env` if it exists
- loads the project `.env` if it exists
- starts the GUI from the local `.venv`
- shows setup instructions if the GUI dependencies are not installed yet

The GUI MVP currently supports:

- folder selection
- API key setup dialog
- analyze flow with live progress
- planned actions table
- details panel for each decision
- apply flow with confirmation

Current GUI status:

- yes, the GUI MVP is complete
- it is usable for real local workflows
- it can now be built locally as an unsigned standalone `.app` bundle
- code signing, notarization, and DMG packaging are still future improvements

## Standalone macOS App Bundle

If you want a Finder-launchable `.app` bundle instead of running from the terminal, `sortdocs`
can now build one locally with PyInstaller.

Install the bundle dependencies:

```bash
uv sync --extra dev --extra gui --extra bundle
```

or:

```bash
pip install -e '.[dev,gui,bundle]'
```

Build the app bundle:

```bash
bash scripts/build-macos-app.sh
```

or:

```bash
make bundle-gui
```

The bundle is created at:

```text
dist/sortdocs.app
```

You can open it with:

```bash
open dist/sortdocs.app
```

Important notes:

- bundle creation currently works on macOS only
- build with Python 3.11+
- the generated app is unsigned and intended for local use
- the standalone app reads the global config from `~/.config/sortdocs/.env`
- if you want the bundle to have API access without terminal setup, save your key through onboarding first

## OpenAI Setup

You have two options.

### Recommended: first-run interactive setup

If `OPENAI_API_KEY` is missing, `sortdocs` will show a short welcome flow and let you paste your API key directly in the terminal.

It also shows where to create the key:

- OpenAI API keys dashboard: `https://platform.openai.com/settings/organization/api-keys`
- OpenAI setup guide: `https://platform.openai.com/docs/quickstart/step-2-setup-your-api-key`

Important:

- this is an OpenAI Platform API key, not a ChatGPT password
- ChatGPT subscriptions and API billing are separate
- if you save the key during onboarding, future runs can work without extra shell setup

### Manual setup

Start from the example file:

```bash
cp .env.example .env
```

Then set your API key:

```env
OPENAI_API_KEY=your_openai_api_key_here
```

You can also store the key globally for `sortdocs` in:

```text
~/.config/sortdocs/.env
```

with:

```env
OPENAI_API_KEY=your_openai_api_key_here
```

## Everyday Usage

### Default Flow

```bash
cd ~/Documents
sortdocs .
```

This command:

- scans the folder recursively
- analyzes supported files
- shows live progress while scanning and classifying
- shows the planned actions
- asks `Proceed with these actions?`
- applies changes only if you confirm

### First Run Experience

On the first run, `sortdocs` can show:

- a short welcome panel
- a guided prompt to paste your OpenAI API key
- the official link to create the key
- the option to save the key for future runs

### Ignore Paths Explicitly

You can place a `.sortdocsignore` file in the root you are organizing:

```text
Projects
Obsidian
*.heic
```

This is useful for folders or file types that should never be touched, even if they are not software projects.

### Project Folder Protection

By default, `sortdocs` protects software projects:

- if the root folder looks like a project, the run is blocked
- nested project folders like Git repositories, `node_modules`, `.venv`, `dist`, `build`, and similar trees are skipped automatically

If you intentionally want to scan a project-like root, you can use:

```bash
sortdocs . --allow-project-root
```

### Preview Without Changes

```bash
sortdocs . --dry-run
```

### Limit The Number Of Files

```bash
sortdocs . --max-files 50
```

### Disable Recursive Scanning

```bash
sortdocs . --no-recursive
```

### Skip The Confirmation Prompt

```bash
sortdocs . --yes
```

### Show Technical Details

```bash
sortdocs . --verbose
```

In normal mode, `sortdocs` focuses on the plan and final summary. Internal AI `INFO` logs are hidden by default to keep the output clean.

## Configuration File

You can create a `sortdocs.yaml` or `.sortdocs.yaml` file in the current directory, or pass one with `--config`.

Minimal example:

```yaml
cli:
    dry_run: false
    recursive_default: true
    review_dir: '.'
    library_dir: '.'
    max_files_per_run: 100

scanner:
    ignore_filename: '.sortdocsignore'
    exclude:
        - 'Projects'
        - '*.heic'

extraction:
    max_excerpt_chars: 4000

openai:
    model: 'gpt-4.1-mini'
    temperature: 0.1

planner:
    confidence_threshold: 0.65
    folder_pattern: '{category}/{subcategory}'

logging:
    level: INFO
```

Main fields:

- `cli.dry_run`
- `cli.recursive_default`
- `cli.review_dir`
- `cli.library_dir`
- `cli.max_files_per_run`
- `scanner.ignore_filename`
- `scanner.exclude`
- `extraction.max_excerpt_chars`
- `openai.model`
- `openai.temperature`
- `planner.confidence_threshold`
- `planner.allowed_categories`
- `planner.folder_pattern`
- `logging.level`

Supported folder patterns:

- `{category}/{subcategory}`
- `{category}`
- `{year}/{category}`

See also [sortdocs.example.yaml](/Users/davdifr/Workspace/sortdocs/sortdocs.example.yaml).

## Planner Behavior

By default, `sortdocs` works directly inside the folder you pass in:

- it does not automatically create separate `Library/` and `Review/` roots
- it creates new subfolders when needed
- it tries to reuse equivalent existing folders when the context matches
- it avoids collisions by adding incremental suffixes
- it never overwrites existing files
- it shows a plan before touching the filesystem

For files with weak evidence:

- confidence is lowered
- the file may stay in place with `skip` or `review`
- scanned PDFs can use a visual fallback through OpenAI when no text is extractable

For repeat runs:

- `sortdocs` stores a local `.sortdocs-state.json` cache for unchanged files
- unchanged files can skip extraction and reclassification entirely
- the cache is invalidated automatically when relevant AI/planner settings change

It can also create:

- `.sortdocs-memory.json` to improve folder consistency over time
- `.sortdocs-state.json` to skip unchanged files efficiently

## Logging

Default behavior:

- output is centered on the plan and final summary
- progress feedback is shown during analysis and apply steps
- important warnings and errors remain visible
- internal AI informational logs are hidden

If you want technical details:

```bash
sortdocs . --verbose
```

## Troubleshooting

### `sortdocs: command not found`

- run `bash scripts/install-path.sh`
- then run `hash -r`
- or use `.venv/bin/sortdocs`

### `OPENAI_API_KEY is not set`

- rerun `sortdocs .` in an interactive terminal and follow the onboarding flow
- or create `.env` from `.env.example`
- or save a global key in `~/.config/sortdocs/.env`
- if you use a project-local `.env` with `.venv/bin/sortdocs`, run:

```bash
set -a
source .env
set +a
```

### The Root Folder Looks Like A Software Project

`sortdocs` protects project-like roots by default. If you really want to continue:

```bash
sortdocs . --allow-project-root
```

### The Plan Is Not What You Expected

- try `sortdocs . --dry-run` first
- use `--max-files` if you want to test a smaller batch
- use `--verbose` if you want more technical context

### Some PDFs Have No Extractable Text

`sortdocs` first tries text extraction. If the PDF is image-based or scanned, it can use a visual fallback through OpenAI to classify the file more safely.

## Local Development

Install dependencies:

```bash
make install
```

Run tests:

```bash
make test
```

Run lint:

```bash
make lint
```

Quick example:

```bash
make run-example INPUT=~/Documents/Inbox
```

## Project Status

The project is ready for local macOS usage as a production-minded MVP:

- full `scan -> extract -> classify -> plan -> execute` pipeline
- unit and end-to-end test coverage
- launcher available in `PATH`
- first-run onboarding for API key setup
- readable terminal UI
- filesystem guardrails around planning and execution
