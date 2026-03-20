# Release Checklist

Practical checklist for preparing `sortdocs` for a local release or an initial project handoff.

## Before Tagging

- make sure `.env` is not tracked
- verify the version in `pyproject.toml` and `src/sortdocs/__init__.py`
- update `README.md` if the CLI flow changed
- review `sortdocs.example.yaml`

## Technical Verification

Run:

```bash
make test
make lint
```

Also verify the real command:

```bash
hash -r
sortdocs . --dry-run
```

## Packaging

Confirm the console script is available:

```bash
.venv/bin/sortdocs --help
```

Confirm the launcher works from `PATH`:

```bash
bash scripts/install-path.sh
hash -r
sortdocs --help
```

## Recommended Manual Checks

- run on a small folder with `--dry-run`
- run a confirmed apply on a test folder
- verify filename collision handling
- verify PDFs with real extractable text
- verify scanned or image-based PDFs
- verify files that are already in the correct place

## After Release

- note real-world cases that ended up in review unexpectedly
- adjust heuristics or the AI prompt only after collecting concrete examples
- consider cleaning or migrating local memory if the path strategy changes
