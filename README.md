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
- guardrails for renames, extensions, path traversal, and collisions
- conservative fallback behavior for weak or ambiguous files
- local memory to improve path reuse across runs

## Requirements

- macOS
- Python 3.11+
- `OPENAI_API_KEY`

## Installation

### With `uv`

```bash
git clone <your-repo-url> sortdocs
cd sortdocs
uv sync --extra dev
```

### With `pip`

```bash
git clone <your-repo-url> sortdocs
cd sortdocs
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
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

- the launcher created by `scripts/install-path.sh` automatically loads the project's `.env` file if it exists
- if you run `.venv/bin/sortdocs` directly, you must export `OPENAI_API_KEY` yourself

## OpenAI Setup

Start from the example file:

```bash
cp .env.example .env
```

Then set your API key:

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
- shows the planned actions
- asks `Proceed with these actions?`
- applies changes only if you confirm

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

For files with weak evidence:

- confidence is lowered
- the file may stay in place with `skip` or `review`
- scanned PDFs can use a visual fallback through OpenAI when no text is extractable

## Logging

Default behavior:

- output is centered on the plan and final summary
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

- create `.env` from `.env.example`
- if you use the global launcher, `.env` is loaded automatically
- if you use `.venv/bin/sortdocs`, run:

```bash
set -a
source .env
set +a
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
- readable terminal UI
- filesystem guardrails around planning and execution
